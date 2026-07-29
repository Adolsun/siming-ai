package com.siming.mobile.data.network

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

@Serializable
data class DirectApiConfig(
    val displayName: String,
    val baseUrl: String,
    val apiKey: String,
    val model: String,
    val protocol: String = PROTOCOL_AUTO,
) {
    fun summary() = DirectApiSummary(displayName, baseUrl, model, protocol)

    companion object {
        const val PROTOCOL_AUTO = "auto"
        const val PROTOCOL_RESPONSES = "responses"
        const val PROTOCOL_CHAT_COMPLETIONS = "chat_completions"
        val supportedProtocols = setOf(
            PROTOCOL_AUTO,
            PROTOCOL_RESPONSES,
            PROTOCOL_CHAT_COMPLETIONS,
        )
    }
}

data class DirectApiSummary(
    val displayName: String,
    val baseUrl: String,
    val model: String,
    val protocol: String,
)

class DirectApiHttpException(
    val statusCode: Int,
    message: String,
) : IOException(message)

/** OpenAI-compatible client used only by Android standalone mode. */
class DirectApiClient(
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .callTimeout(150, TimeUnit.SECONDS)
        .build(),
    private val allowCleartextForTests: Boolean = false,
    private val retryDelaysMillis: List<Long> = listOf(700, 1_500, 3_000),
) {
    private val json = Json { ignoreUnknownKeys = true }

    suspend fun discoverModels(baseUrl: String, apiKey: String): List<String> {
        require(apiKey.isNotBlank()) { "请先填写 API Key" }
        val endpoints = endpointCandidates(baseUrl, "models")
        var lastError: Throwable? = null
        for (endpoint in endpoints) {
            try {
                val response = execute(endpoint, apiKey, null)
                if (response.statusCode in PATH_FALLBACK_STATUS_CODES) continue
                ensureSuccess(response)
                return parseModels(response.body)
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                lastError = error
                if (error !is DirectApiHttpException || error.statusCode !in PATH_FALLBACK_STATUS_CODES) break
            }
        }
        throw lastError ?: IOException("接口没有返回可用模型，请手动填写模型名")
    }

    suspend fun test(config: DirectApiConfig): String = complete(
        config,
        systemPrompt = "你正在执行连接测试。请严格按要求简短回复。",
        userPrompt = "只回复：连接成功",
        maxOutputTokens = 64,
    )

    suspend fun complete(
        config: DirectApiConfig,
        systemPrompt: String,
        userPrompt: String,
        maxOutputTokens: Int = 4_000,
    ): String {
        validateConfig(config)
        val protocols = when (config.protocol) {
            DirectApiConfig.PROTOCOL_AUTO -> listOf(
                DirectApiConfig.PROTOCOL_RESPONSES,
                DirectApiConfig.PROTOCOL_CHAT_COMPLETIONS,
            )
            else -> listOf(config.protocol)
        }
        var lastError: Throwable? = null
        for ((index, protocol) in protocols.withIndex()) {
            try {
                val text = completeWithProtocol(
                    config,
                    protocol,
                    systemPrompt,
                    userPrompt,
                    maxOutputTokens,
                )
                require(text.isNotBlank()) { "模型返回了空内容，请检查模型名或切换 API 协议" }
                return text
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                lastError = error
                val canTryNext = index < protocols.lastIndex && error.isProtocolMismatch()
                if (!canTryNext) throw error
            }
        }
        throw lastError ?: IOException("模型调用没有完成")
    }

    private suspend fun completeWithProtocol(
        config: DirectApiConfig,
        protocol: String,
        systemPrompt: String,
        userPrompt: String,
        maxOutputTokens: Int,
    ): String {
        val path = if (protocol == DirectApiConfig.PROTOCOL_RESPONSES) {
            "responses"
        } else {
            "chat/completions"
        }
        val payload = if (protocol == DirectApiConfig.PROTOCOL_RESPONSES) {
            buildJsonObject {
                put("model", config.model.trim())
                put("instructions", systemPrompt)
                put("input", userPrompt)
                put("max_output_tokens", maxOutputTokens)
                put("stream", false)
            }
        } else {
            buildJsonObject {
                put("model", config.model.trim())
                put("messages", buildJsonArray {
                    add(buildJsonObject {
                        put("role", "system")
                        put("content", systemPrompt)
                    })
                    add(buildJsonObject {
                        put("role", "user")
                        put("content", userPrompt)
                    })
                })
                put("max_tokens", maxOutputTokens)
                put("stream", false)
            }
        }
        var lastError: Throwable? = null
        for (endpoint in endpointCandidates(config.baseUrl, path)) {
            try {
                val response = executeWithRetry(
                    endpoint,
                    config.apiKey,
                    json.encodeToString(payload),
                )
                if (response.statusCode in PATH_FALLBACK_STATUS_CODES) continue
                ensureSuccess(response)
                val root = json.parseToJsonElement(response.body).jsonObject
                return if (protocol == DirectApiConfig.PROTOCOL_RESPONSES) {
                    parseResponsesText(root)
                } else {
                    parseChatText(root)
                }
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                lastError = error
                if (error !is DirectApiHttpException || error.statusCode !in PATH_FALLBACK_STATUS_CODES) break
            }
        }
        throw lastError ?: DirectApiHttpException(404, "API 地址没有提供 $path 接口")
    }

    private suspend fun executeWithRetry(
        endpoint: HttpUrl,
        apiKey: String,
        body: String,
    ): RawResponse {
        var response = execute(endpoint, apiKey, body)
        for (delayMillis in retryDelaysMillis) {
            if (response.statusCode !in TRANSIENT_STATUS_CODES) return response
            delay(delayMillis)
            response = execute(endpoint, apiKey, body)
        }
        return response
    }

    private suspend fun execute(
        endpoint: HttpUrl,
        apiKey: String,
        body: String?,
    ): RawResponse = withContext(Dispatchers.IO) {
        val builder = Request.Builder()
            .url(endpoint)
            .header("Accept", "application/json")
            .header("Authorization", "Bearer ${apiKey.trim()}")
        if (body == null) {
            builder.get()
        } else {
            builder.post(body.toRequestBody(JSON_MEDIA_TYPE))
        }
        client.newCall(builder.build()).execute().use { response ->
            RawResponse(response.code, response.body?.string().orEmpty())
        }
    }

    private fun endpointCandidates(baseUrl: String, path: String): List<HttpUrl> {
        val base = validateBaseUrl(baseUrl).toString().trimEnd('/')
        return buildList {
            add(requireNotNull("$base/$path".toHttpUrlOrNull()))
            if (!base.endsWith("/v1")) {
                add(requireNotNull("$base/v1/$path".toHttpUrlOrNull()))
            }
        }.distinct()
    }

    private fun validateBaseUrl(value: String): HttpUrl {
        val parsed = value.trim().trimEnd('/').toHttpUrlOrNull()
            ?: error("请输入完整 API 地址，例如 https://api.example.com/v1")
        require(parsed.username.isEmpty() && parsed.password.isEmpty()) { "API 地址不能包含账号或密码" }
        require(parsed.query == null && parsed.fragment == null) { "API 地址不能包含查询参数或片段" }
        require(parsed.scheme == "https" || allowCleartextForTests) {
            "手机直连 API 必须使用 HTTPS，避免 API Key 被明文传输"
        }
        return parsed
    }

    private fun validateConfig(config: DirectApiConfig) {
        validateBaseUrl(config.baseUrl)
        require(config.apiKey.isNotBlank()) { "请填写 API Key" }
        require(config.model.isNotBlank()) { "请先自动获取或手动填写模型名" }
        require(config.protocol in DirectApiConfig.supportedProtocols) { "不支持的 API 协议" }
    }

    private fun ensureSuccess(response: RawResponse) {
        if (response.statusCode in 200..299) return
        val message = parseError(response.body)
        throw DirectApiHttpException(
            response.statusCode,
            when (response.statusCode) {
                401, 403 -> "API Key 无效或没有访问该模型的权限"
                429 -> "API 请求过于频繁或额度不足，请稍后重试"
                in TRANSIENT_STATUS_CODES -> "API 上游暂时不可用（HTTP ${response.statusCode}），系统已自动重试"
                else -> message ?: "API 请求失败（HTTP ${response.statusCode}）"
            },
        )
    }

    private fun parseModels(raw: String): List<String> {
        val root = json.parseToJsonElement(raw).jsonObject
        val candidates = (root["data"] as? JsonArray)
            ?: (root["models"] as? JsonArray)
            ?: JsonArray(emptyList())
        return candidates.mapNotNull { item ->
            when (item) {
                is JsonPrimitive -> item.contentOrNull
                is JsonObject -> listOf("id", "name", "model")
                    .firstNotNullOfOrNull { key -> (item[key] as? JsonPrimitive)?.contentOrNull }
                else -> null
            }
        }.map(String::trim).filter(String::isNotBlank).distinct().sorted()
    }

    private fun parseResponsesText(root: JsonObject): String {
        (root["output_text"] as? JsonPrimitive)?.contentOrNull?.takeIf(String::isNotBlank)?.let { return it }
        return (root["output"] as? JsonArray).orEmpty().flatMap { item ->
            val content = (item as? JsonObject)?.get("content") as? JsonArray ?: return@flatMap emptyList()
            content.mapNotNull { part ->
                val objectPart = part as? JsonObject ?: return@mapNotNull null
                (objectPart["text"] as? JsonPrimitive)?.contentOrNull
            }
        }.joinToString("").trim()
    }

    private fun parseChatText(root: JsonObject): String {
        val content = ((root["choices"] as? JsonArray)?.firstOrNull() as? JsonObject)
            ?.get("message")
            ?.let { it as? JsonObject }
            ?.get("content")
        return when (content) {
            is JsonPrimitive -> content.contentOrNull.orEmpty().trim()
            is JsonArray -> content.mapNotNull { part ->
                ((part as? JsonObject)?.get("text") as? JsonPrimitive)?.contentOrNull
            }.joinToString("").trim()
            else -> ""
        }
    }

    private fun parseError(raw: String): String? = runCatching {
        val root = json.parseToJsonElement(raw).jsonObject
        val error = root["error"]
        when (error) {
            is JsonPrimitive -> error.contentOrNull
            is JsonObject -> (error["message"] as? JsonPrimitive)?.contentOrNull
            else -> (root["message"] as? JsonPrimitive)?.contentOrNull
        }?.take(300)
    }.getOrNull()

    private fun Throwable.isProtocolMismatch(): Boolean =
        this is DirectApiHttpException && statusCode in setOf(400, 404, 405, 415, 422)

    private data class RawResponse(val statusCode: Int, val body: String)

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
        private val TRANSIENT_STATUS_CODES = setOf(500, 502, 503, 504)
        private val PATH_FALLBACK_STATUS_CODES = setOf(404, 405)
    }
}
