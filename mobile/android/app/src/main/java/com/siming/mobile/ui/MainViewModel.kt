package com.siming.mobile.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.siming.mobile.data.SimingRepository
import com.siming.mobile.data.AssistantRoute
import com.siming.mobile.data.toUserFacingMessage
import com.siming.mobile.data.local.LocalConflict
import com.siming.mobile.data.local.ReplicaEntity
import com.siming.mobile.security.VerifiedPairing
import com.siming.mobile.data.network.DirectApiConfig
import com.siming.mobile.data.network.DirectApiSummary
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

data class MobileUiState(
    val busy: Boolean = false,
    val activity: String = "",
    val error: String? = null,
    val notice: String? = null,
    val pairing: VerifiedPairing? = null,
    val pairingStatus: String? = null,
    val assistantOutput: String = "",
    val assistantRunning: Boolean = false,
    val directApi: DirectApiSummary? = null,
    val discoveredModels: List<String> = emptyList(),
)

@OptIn(ExperimentalSerializationApi::class)
class MainViewModel(application: Application) : AndroidViewModel(application) {
    private val repository = SimingRepository(application)
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    val connection = repository.connection.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        null,
    )
    val projects = repository.projects.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        emptyList(),
    )
    val pendingCount = repository.pendingCount.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        0,
    )
    val cursor = repository.cursor.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        null,
    )
    val conflicts = repository.conflicts.stateIn(
        viewModelScope,
        SharingStarted.WhileSubscribed(5_000),
        emptyList(),
    )

    var uiState = androidx.compose.runtime.mutableStateOf(
        MobileUiState(directApi = repository.directApiSummary()),
    )
        private set

    fun entities(projectId: String, entityType: String) =
        repository.entities(projectId, entityType)

    fun acceptPairingQr(raw: String) {
        runCatching { repository.verifyPairing(raw) }
            .onSuccess { verified ->
                uiState.value = uiState.value.copy(
                    pairing = verified,
                    pairingStatus = "已验证 Gateway 签名，请核对地址与指纹",
                    error = null,
                )
            }
            .onFailure(::showError)
    }

    fun cancelPairing() {
        uiState.value = uiState.value.copy(pairing = null, pairingStatus = null, error = null)
    }

    fun discoverDirectModels(baseUrl: String, apiKey: String) {
        viewModelScope.launch {
            uiState.value = uiState.value.copy(
                busy = true,
                activity = "正在安全获取模型列表…",
                error = null,
                discoveredModels = emptyList(),
            )
            try {
                val models = repository.discoverDirectModels(baseUrl, apiKey)
                uiState.value = uiState.value.copy(
                    busy = false,
                    activity = "",
                    discoveredModels = models,
                    notice = if (models.isEmpty()) {
                        "接口返回了空模型列表，请手动填写模型名"
                    } else {
                        "已获取 ${models.size} 个模型"
                    },
                )
            } catch (error: Exception) {
                uiState.value = uiState.value.copy(
                    busy = false,
                    activity = "",
                    discoveredModels = emptyList(),
                    error = "自动获取模型失败：${error.toUserFacingMessage()}；仍可手动填写模型名",
                )
            }
        }
    }

    fun configureDirectApi(
        displayName: String,
        baseUrl: String,
        apiKey: String,
        model: String,
        protocol: String,
        onConfigured: () -> Unit,
    ) {
        viewModelScope.launch {
            uiState.value = uiState.value.copy(
                busy = true,
                activity = "正在用当前模型进行真实对话测试…",
                error = null,
            )
            try {
                val effectiveModel = model.trim().ifBlank {
                    val models = repository.discoverDirectModels(baseUrl, apiKey)
                    uiState.value = uiState.value.copy(discoveredModels = models)
                    models.firstOrNull()
                        ?: error("接口没有返回可用模型，请手动填写模型名后重试")
                }
                val summary = repository.configureDirectApi(
                    displayName,
                    baseUrl,
                    apiKey,
                    effectiveModel,
                    protocol,
                )
                uiState.value = uiState.value.copy(
                    busy = false,
                    activity = "",
                    directApi = summary,
                    discoveredModels = emptyList(),
                    notice = "API 已加密保存，手机独立模式可以使用",
                )
                onConfigured()
            } catch (error: Exception) {
                val message = error.toUserFacingMessage()
                uiState.value = uiState.value.copy(
                    busy = false,
                    activity = "",
                    error = if (model.isBlank() && !message.contains("手动填写")) {
                        "$message；自动获取模型失败，请手动填写模型名后重试"
                    } else {
                        message
                    },
                )
            }
        }
    }

    fun testDirectApi() = launchActivity("正在测试手机直连 API…") {
        val summary = repository.testDirectApi()
        uiState.value = uiState.value.copy(directApi = summary)
        "${summary.displayName} · ${summary.model} 真实对话成功"
    }

    fun clearDirectApi() {
        runCatching { repository.clearDirectApi() }
            .onSuccess {
                uiState.value = uiState.value.copy(
                    directApi = null,
                    discoveredModels = emptyList(),
                    assistantOutput = "",
                    notice = "已清除手机直连 API 配置",
                )
            }
            .onFailure(::showError)
    }

    fun connectPairing(deviceName: String) {
        val pairing = uiState.value.pairing ?: return
        viewModelScope.launch {
            uiState.value = uiState.value.copy(
                busy = true,
                activity = "正在提交设备申请…",
                error = null,
            )
            try {
                while (Instant.parse(pairing.expiresAt).isAfter(Instant.now())) {
                    val result = repository.requestPairing(pairing, deviceName)
                    when (result.status) {
                        "approved" -> {
                            uiState.value = uiState.value.copy(
                                busy = true,
                                activity = "授权完成，正在下载已启用作品…",
                                pairingStatus = "电脑已批准",
                            )
                            val count = repository.bootstrapEnabledProjects()
                            uiState.value = uiState.value.copy(
                                busy = false,
                                activity = "",
                                pairing = null,
                                pairingStatus = null,
                                notice = "已安全连接，并下载 $count 部作品",
                            )
                            return@launch
                        }
                        "expired" -> error("二维码已经过期，请重新扫描")
                        else -> {
                            uiState.value = uiState.value.copy(
                                activity = "已提交申请，请在电脑上确认这台手机…",
                                pairingStatus = "等待电脑批准",
                            )
                            delay(4_000)
                        }
                    }
                }
                error("二维码已经过期，请重新扫描")
            } catch (error: Exception) {
                showError(error)
                uiState.value = uiState.value.copy(busy = false, activity = "")
            }
        }
    }

    fun bootstrap() = launchActivity("正在校验并下载作品…") {
        val count = repository.bootstrapEnabledProjects()
        "已校验并更新 $count 部作品的离线副本"
    }

    fun syncNow() = launchActivity("正在先上传本机修改，再拉取新修订…") {
        repository.syncNow()
        "同步完成"
    }

    fun createProject(title: String, description: String, onCreated: (String) -> Unit) {
        viewModelScope.launch {
            try {
                val id = repository.createProject(title, description)
                uiState.value = uiState.value.copy(notice = "新作品已保存到离线库")
                onCreated(id)
            } catch (error: Exception) {
                showError(error)
            }
        }
    }

    fun importNovel(fileName: String, content: String, onCreated: (String) -> Unit) {
        viewModelScope.launch {
            uiState.value = uiState.value.copy(busy = true, activity = "正在离线拆分并建档…")
            try {
                require(content.length <= 20_000_000) { "单个导入文件不能超过 2000 万字符" }
                val title = fileName.substringBeforeLast('.').ifBlank { "导入作品" }
                val projectId = repository.createProject(title, "由手机导入的已有小说")
                val chapters = splitChapters(content)
                chapters.forEachIndexed { index, (chapterTitle, chapterContent) ->
                    saveRecordInternal(
                        projectId,
                        "chapter",
                        null,
                        mapOf(
                            "title" to chapterTitle.ifBlank { "第 ${index + 1} 章" },
                            "content" to chapterContent,
                            "word_count" to chapterContent.count { !it.isWhitespace() },
                            "current_version" to 1,
                        ),
                    )
                }
                uiState.value = uiState.value.copy(
                    busy = false,
                    activity = "",
                    notice = "已离线导入 ${chapters.size} 章，联网后自动同步",
                )
                onCreated(projectId)
            } catch (error: Exception) {
                uiState.value = uiState.value.copy(busy = false, activity = "")
                showError(error)
            }
        }
    }

    fun saveRecord(
        projectId: String,
        entityType: String,
        entityId: String?,
        fields: Map<String, Any?>,
        basePayload: JsonObject? = null,
        onSaved: () -> Unit,
    ) {
        viewModelScope.launch {
            try {
                saveRecordInternal(projectId, entityType, entityId, fields, basePayload)
                uiState.value = uiState.value.copy(notice = "已保存到手机；联网后自动同步")
                onSaved()
            } catch (error: Exception) {
                showError(error)
            }
        }
    }

    private suspend fun saveRecordInternal(
        projectId: String,
        entityType: String,
        entityId: String?,
        fields: Map<String, Any?>,
        basePayload: JsonObject? = null,
    ): String {
        val id = entityId ?: UUID.randomUUID().toString()
        val recordType = when (entityType) {
            "project" -> "project"
            "chapter" -> "chapter"
            "outline" -> "outline_node"
            "character" -> "character"
            "world" -> "world_entry"
            "foreshadowing" -> "foreshadowing"
            "governance" -> "narrative_debt"
            "summary" -> "chapter_summary"
            "timeline" -> "character_timeline"
            else -> error("暂不支持的资料类型")
        }
        val payload = buildJsonObject {
            basePayload?.forEach { (key, value) -> put(key, value) }
            put("_record_type", recordType)
            put("id", id)
            if (entityType in setOf("chapter", "outline", "character", "world", "foreshadowing", "governance")) {
                put("project_id", projectId)
            }
            fields.forEach { (key, value) -> putAny(key, value) }
            if (entityType == "foreshadowing" && fields["dedupe_key"] == null) {
                put("dedupe_key", "mobile-$id")
                put("source", "manual")
            }
            if (entityType == "governance" && fields["dedupe_key"] == null) {
                put("dedupe_key", "mobile-$id")
                put("source", "manual")
                put("debt_type", "promise")
            }
        }
        repository.saveEntity(projectId, entityType, id, payload)
        return id
    }

    fun deleteRecord(projectId: String, entityType: String, entityId: String, onDeleted: () -> Unit) {
        viewModelScope.launch {
            try {
                repository.deleteEntity(projectId, entityType, entityId)
                uiState.value = uiState.value.copy(notice = "删除已记入离线修订")
                onDeleted()
            } catch (error: Exception) {
                showError(error)
            }
        }
    }

    fun runAssistant(projectId: String, scope: String, prompt: String) {
        if (prompt.isBlank()) return
        viewModelScope.launch {
            uiState.value = uiState.value.copy(
                assistantRunning = true,
                assistantOutput = "",
                error = null,
            )
            try {
                val route = repository.runAssistant(projectId, scope, prompt) { event ->
                    uiState.value = uiState.value.copy(
                        assistantOutput = uiState.value.assistantOutput + parseAssistantEvent(event),
                    )
                }
                uiState.value = uiState.value.copy(
                    assistantRunning = false,
                    notice = if (route == AssistantRoute.Gateway) {
                        "AI 任务完成，相关修改已同步到离线库"
                    } else {
                        "AI 生成完成；结果尚未写入正文，可复制或保存为新章节"
                    },
                )
            } catch (error: Exception) {
                uiState.value = uiState.value.copy(assistantRunning = false)
                showError(error)
            }
        }
    }

    fun saveAssistantAsChapter(projectId: String, onSaved: () -> Unit = {}) {
        val content = uiState.value.assistantOutput.trim()
        if (content.isBlank()) return
        viewModelScope.launch {
            try {
                val stamp = Instant.now().toString().take(16).replace('T', ' ')
                saveRecordInternal(
                    projectId,
                    "chapter",
                    null,
                    mapOf(
                        "title" to "AI 生成 $stamp",
                        "content" to content,
                        "word_count" to content.count { !it.isWhitespace() },
                        "current_version" to 1,
                    ),
                )
                uiState.value = uiState.value.copy(notice = "AI 结果已保存为本机新章节")
                onSaved()
            } catch (error: Exception) {
                showError(error)
            }
        }
    }

    fun resolveConflict(conflict: LocalConflict, choice: String) = launchActivity("正在处理版本分岔…") {
        repository.resolveConflict(conflict, choice)
        "冲突已处理；双方原始版本仍保留在 Gateway"
    }

    fun disconnect(clearOfflineData: Boolean) = launchActivity("正在断开设备…") {
        val revokedRemotely = repository.disconnect(clearOfflineData)
        when {
            !revokedRemotely -> "本机已断开；Gateway 当前不可达，请稍后在管理页撤销这台设备"
            clearOfflineData -> "已撤销设备授权并清除本机离线副本"
            else -> "已撤销设备授权，离线副本仍保留"
        }
    }

    fun clearNotice() {
        uiState.value = uiState.value.copy(notice = null, error = null)
    }

    fun reportError(message: String) {
        uiState.value = uiState.value.copy(error = message)
    }

    private fun launchActivity(label: String, action: suspend () -> String) {
        viewModelScope.launch {
            uiState.value = uiState.value.copy(busy = true, activity = label, error = null)
            try {
                val notice = action()
                uiState.value = uiState.value.copy(busy = false, activity = "", notice = notice)
            } catch (error: Exception) {
                uiState.value = uiState.value.copy(busy = false, activity = "")
                showError(error)
            }
        }
    }

    private fun showError(error: Throwable) {
        uiState.value = uiState.value.copy(error = error.toUserFacingMessage())
    }

    private fun splitChapters(content: String): List<Pair<String, String>> {
        val marker = Regex("(?m)^(第[\\p{L}\\p{N}一二三四五六七八九十百千万零〇两]{1,16}[章节卷回部].*)$")
        val matches = marker.findAll(content).toList()
        val chapters = if (matches.isEmpty()) {
            content.chunked(5_000).mapIndexed { index, text ->
                "第 ${index + 1} 章" to text.trim()
            }.filter { it.second.isNotBlank() }
        } else {
            matches.mapIndexed { index, match ->
                val start = match.range.last + 1
                val end = matches.getOrNull(index + 1)?.range?.first ?: content.length
                match.value.trim() to content.substring(start, end).trim()
            }.filter { it.second.isNotBlank() }
        }
        return chapters.flatMap { (title, body) ->
            body.chunked(200_000).mapIndexed { index, part ->
                (if (index == 0) title else "$title（续 ${index + 1}）") to part
            }
        }
    }

    private fun parseAssistantEvent(raw: String): String = runCatching {
        val objectValue = json.parseToJsonElement(raw) as? JsonObject ?: return@runCatching raw
        val candidateKeys = listOf("content", "text", "message", "detail", "reply")
        candidateKeys.firstNotNullOfOrNull { key ->
            objectValue[key]?.jsonPrimitive?.contentOrNull
        } ?: if (objectValue["type"]?.jsonPrimitive?.content == "done") "\n\n任务完成。" else ""
    }.getOrDefault(raw)
}

fun ReplicaEntity.payload(): JsonObject? = payloadJson?.let {
    runCatching { Json.parseToJsonElement(it) as JsonObject }.getOrNull()
}

fun ReplicaEntity.text(name: String): String =
    payload()?.get(name)?.jsonPrimitive?.contentOrNull.orEmpty()

fun ReplicaEntity.number(name: String): Int =
    payload()?.get(name)?.jsonPrimitive?.intOrNull ?: 0

private fun kotlinx.serialization.json.JsonObjectBuilder.putAny(key: String, value: Any?) {
    when (value) {
        null -> put(key, kotlinx.serialization.json.JsonNull)
        is String -> put(key, value)
        is Int -> put(key, value)
        is Long -> put(key, value)
        is Float -> put(key, value)
        is Double -> put(key, value)
        is Boolean -> put(key, value)
        is JsonPrimitive -> put(key, value)
        else -> put(key, value.toString())
    }
}
