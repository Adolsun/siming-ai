package com.siming.mobile.data.creation

import com.siming.mobile.data.network.DirectApiHttpException
import java.io.IOException
import java.net.SocketTimeoutException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

internal data class MobileInterviewFailure(
    val failureClass: String,
    val nextAction: String,
    val message: String,
    val rawResponsePreview: String = "",
)

internal class MobileInterviewDecisionException(
    message: String,
    val failureClass: String,
    val repairable: Boolean,
) : RuntimeException(message)

internal object MobileCreationInterviewReliability {
    private val json = Json { ignoreUnknownKeys = true }

    fun parseDecision(raw: String, history: JsonArray): JsonObject {
        val payload = parseObject(raw)
        return when (payload.string("action").lowercase()) {
            "generate" -> buildJsonObject {
                put("action", "generate")
                put("reason", payload.string("reason"))
            }
            "ask_more" -> {
                val candidate = payload["question"]
                    ?: (payload["questions"] as? JsonArray)?.firstOrNull()
                val question = normalizeQuestion(candidate)
                    ?: throw MobileInterviewDecisionException(
                        "模型决定继续采访，但没有给出有效问题。",
                        failureClass = "invalid_response",
                        repairable = true,
                    )
                val asked = history.mapNotNull { it as? JsonObject }
                    .map { questionKey(it.string("question")) }
                    .filter(String::isNotBlank)
                    .toSet()
                if (questionKey(question.string("question")) in asked) {
                    throw MobileInterviewDecisionException(
                        "模型重复了已经回答过的问题。",
                        failureClass = "invalid_response",
                        repairable = false,
                    )
                }
                buildJsonObject {
                    put("action", "ask_more")
                    put("reason", payload.string("reason"))
                    put("question", question)
                }
            }
            else -> throw MobileInterviewDecisionException(
                "模型没有返回 ask_more 或 generate 决策。",
                failureClass = "invalid_response",
                repairable = true,
            )
        }
    }

    fun retryUserPrompt(originalUserPrompt: String, raw: String, error: String): String = buildString {
        append(originalUserPrompt)
        append("\n\n上一次模型输出没有通过动态采访结构校验。请基于完全相同的上下文重新判断一次。\n")
        append("校验错误：")
        append(error.take(800))
        append("\n上一次输出：")
        append(raw.take(4_000))
        append("\n只允许返回以下两种 JSON 之一：")
        append("{\"action\":\"ask_more\",\"reason\":\"...\",\"question\":{\"question\":\"...\",\"purpose\":\"...\",\"options\":[],\"type\":\"text\"}}")
        append(" 或 {\"action\":\"generate\",\"reason\":\"...\"}。不要输出 Markdown 或 JSON 之外的内容。")
    }

    fun failure(error: Throwable, rawResponse: String = ""): MobileInterviewFailure {
        val cleaned = error.message?.trim().takeUnless(String?::isNullOrBlank) ?: "模型未完成动态提问"
        val lower = cleaned.lowercase()
        val failureClass = when {
            error is MobileInterviewDecisionException -> error.failureClass
            error is DirectApiHttpException && error.statusCode == 429 -> "quota_or_rate_limit"
            error is DirectApiHttpException && error.statusCode in setOf(401, 403) -> "auth"
            error is SocketTimeoutException -> "timeout"
            "rate limit" in lower || "quota" in lower || "usage exceeded" in lower || "额度" in cleaned -> "quota_or_rate_limit"
            "unauthorized" in lower || "forbidden" in lower || "api key" in lower || "鉴权" in cleaned || "权限" in cleaned -> "auth"
            "timeout" in lower || "timed out" in lower || "超时" in cleaned -> "timeout"
            "空内容" in cleaned || "没有收到模型" in cleaned || "empty" in lower -> "empty_response"
            "json" in lower || "ask_more" in lower || "generate" in lower || "问题" in cleaned -> "invalid_response"
            error is IOException -> "network"
            else -> "unknown"
        }
        val advice = when (failureClass) {
            "quota_or_rate_limit" -> "请切换有额度的模型，或等待额度恢复后发送“继续”。"
            "auth" -> "请在设置中重新填写或测试 API 凭据，成功后发送“继续”。"
            "timeout" -> "本轮动态提问已停止；回答已保留，可切换更快的模型后发送“继续”。"
            "empty_response" -> "模型没有返回文字；回答已保留，请发送“继续”重试或切换模型。"
            "invalid_response" -> "模型没有按动态采访格式返回；回答已保留，请发送“继续”重试。"
            "network" -> "回答已保留，请检查网络后发送“继续”重试。"
            else -> "回答已保留，请检查当前模型后发送“继续”重试。"
        }
        return MobileInterviewFailure(
            failureClass = failureClass,
            nextAction = advice,
            message = "动态采访失败：$cleaned $advice",
            rawResponsePreview = rawResponse.take(4_000),
        )
    }

    private fun parseObject(raw: String): JsonObject {
        val trimmed = raw.trim()
        if (trimmed.isBlank()) {
            throw MobileInterviewDecisionException(
                "没有收到模型的文字回复。",
                failureClass = "empty_response",
                repairable = false,
            )
        }
        val unfenced = if (trimmed.startsWith("```")) {
            trimmed.substringAfter('\n', trimmed.removePrefix("```")).removeSuffix("```").trim()
        } else {
            trimmed
        }
        val candidates = buildList {
            add(unfenced)
            val start = unfenced.indexOf('{')
            val end = unfenced.lastIndexOf('}')
            if (start >= 0 && end > start) add(unfenced.substring(start, end + 1))
        }.distinct()
        candidates.forEach { candidate ->
            val parsed = runCatching { json.parseToJsonElement(candidate) as? JsonObject }.getOrNull()
            if (parsed != null) return parsed
        }
        throw MobileInterviewDecisionException(
            "模型返回的动态采访 JSON 无法解析。",
            failureClass = "invalid_response",
            repairable = true,
        )
    }

    private fun normalizeQuestion(value: JsonElement?): JsonObject? {
        val source = when (value) {
            is JsonObject -> value
            is JsonPrimitive -> value.contentOrNull?.takeIf(String::isNotBlank)?.let { text ->
                buildJsonObject { put("question", text.trim()) }
            }
            else -> null
        } ?: return null
        val question = source.string("question").ifBlank { source.string("text") }.trim()
        if (question.isBlank()) return null
        return buildJsonObject {
            put("question", question)
            put("purpose", source.string("purpose"))
            put("options", buildJsonArray {})
            put("type", "text")
        }
    }

    private fun questionKey(value: String): String =
        value.lowercase().replace(Regex("[^\\p{L}\\p{N}]+"), "")

    private fun JsonObject.string(name: String): String =
        (get(name) as? JsonPrimitive)?.contentOrNull.orEmpty()
}
