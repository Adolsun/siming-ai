package com.siming.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.siming.mobile.data.observability.TraceInspectionRepository
import com.siming.mobile.data.observability.text
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

@Composable
internal fun ContextInspectorButton(kind: String? = null, scopeId: String? = null, correlationId: String? = null, label: String = "查看调用记录") {
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true }) { Text(label) }
    if (open) Dialog(onDismissRequest = { open = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize().padding(8.dp), shape = MaterialTheme.shapes.large) {
            ContextInspectorWorkspace(kind, scopeId, correlationId) { open = false }
        }
    }
}

@Composable
private fun ContextInspectorWorkspace(kind: String?, scopeId: String?, correlationId: String?, close: () -> Unit) {
    val context = LocalContext.current
    val repository = remember { TraceInspectionRepository(context) }
    val coroutine = rememberCoroutineScope()
    var remote by remember { mutableStateOf(false) }
    var hasGateway by remember { mutableStateOf(false) }
    var refresh by remember { mutableIntStateOf(0) }
    var mode by remember { mutableStateOf("summary") }
    var traces by remember { mutableStateOf(emptyList<JsonObject>()) }
    var next by remember { mutableStateOf<Long?>(null) }
    var before by remember { mutableStateOf<Long?>(null) }
    var selected by remember { mutableStateOf<JsonObject?>(null) }
    var error by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var actionBusy by remember { mutableStateOf(false) }
    var clearPrompt by remember { mutableStateOf(false) }
    var exportPrompt by remember { mutableStateOf(false) }
    var exportTarget by remember { mutableStateOf<Pair<Boolean, String>?>(null) }
    var health by remember { mutableStateOf("") }
    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        val target = exportTarget
        if (uri != null && target != null) coroutine.launch {
            actionBusy = true
            try { withContext(Dispatchers.IO) {
                requireNotNull(context.contentResolver.openOutputStream(uri)) { "无法打开所选保存位置" }
                    .use { repository.export(target.first, target.second, it) }
            } }
            catch (failure: Exception) { if (failure is CancellationException) throw failure; error = failure.message.orEmpty() }
            finally { actionBusy = false }
        }
    }
    LaunchedEffect(remote, refresh, before, kind, scopeId, correlationId) {
        loading = true; error = ""; traces = emptyList(); next = null
        try {
            hasGateway = repository.hasGateway()
            val settings = repository.settings(remote)
            mode = settings["policy"]!!.jsonObject.text("mode")
            health = if ((settings["write_errors"]?.jsonPrimitive?.intOrNull ?: 0) > 0 || (settings["dropped_events"]?.jsonPrimitive?.intOrNull ?: 0) > 0) "部分诊断内容未写入，记录可能不完整。" else ""
            val result = repository.traces(remote, kind, scopeId, correlationId, before)
            traces = result["items"]!!.jsonArray.map { it.jsonObject }
            next = result["next_cursor"]?.jsonPrimitive?.longOrNull
        } catch (failure: Exception) { if (failure is CancellationException) throw failure; error = failure.message.orEmpty() }
        finally { loading = false }
    }
    fun changeMode(value: String, timed: Boolean = false) {
        coroutine.launch {
            actionBusy = true
            try { repository.setMode(remote, value, timed); refresh += 1 }
            catch (failure: Exception) { if (failure is CancellationException) throw failure; error = failure.message.orEmpty() }
            finally { actionBusy = false }
        }
    }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("调用与上下文", style = MaterialTheme.typography.titleLarge)
            TextButton(onClick = close) { Text("关闭") }
        }
        Row {
            FilterChip(selected = !remote, enabled = !actionBusy, onClick = { remote = false; selected = null; before = null }, label = { Text("此手机") })
            Spacer(Modifier.width(8.dp))
            FilterChip(selected = remote, enabled = hasGateway && !actionBusy, onClick = { remote = true; selected = null; before = null }, label = { Text("Gateway") })
        }
        Text("完整记录包含后续任务的正文、历史与工具结果，保存在执行端；密钥会脱敏。未记录的旧请求无法补回。", style = MaterialTheme.typography.bodySmall)
        Row {
            TextButton(enabled = !actionBusy, onClick = { changeMode("summary") }) { Text(if (mode == "summary") "✓ 摘要" else "摘要") }
            TextButton(enabled = !actionBusy, onClick = { changeMode("full", true) }) { Text(if (mode == "full") "✓ 完整记录" else "完整 60 分钟") }
            TextButton(enabled = !actionBusy, onClick = { changeMode("full") }) { Text("持续") }
            TextButton(enabled = !actionBusy, onClick = { changeMode("off") }) { Text(if (mode == "off") "✓ 关闭" else "关闭") }
        }
        if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
        if (health.isNotBlank()) Text(health, color = MaterialTheme.colorScheme.error)
        Row {
            TextButton(onClick = { refresh += 1 }) { Text("刷新") }
            TextButton(enabled = !actionBusy, onClick = { clearPrompt = true }) { Text("清空记录") }
            if (selected != null) {
                TextButton(onClick = { selected = null }) { Text("任务列表") }
                TextButton(enabled = !actionBusy, onClick = { exportPrompt = true }) { Text("导出") }
            }
        }
        if (loading || actionBusy) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (selected != null) key(remote, selected!!.text("id")) {
            TraceDetails(repository, remote, selected!!.text("id"), refresh)
        } else LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (traces.isEmpty() && !loading) item { Text("本轮暂无记录。可开启记录后再次操作；旧记录也可能已过期。") }
            items(traces, key = { it.text("id") }) { trace ->
                OutlinedCard(onClick = { selected = trace }, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(java.time.Instant.ofEpochMilli((trace["started"]!!.jsonPrimitive.double * 1000).toLong()).atZone(java.time.ZoneId.systemDefault()).toLocalDateTime().toString())
                        Text("${trace.text("status")} · ${trace.text("mode")} · 采集 ${trace.text("capture_status")}")
                        Text(trace.text("id").take(12), fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            if (next != null) item { TextButton(onClick = { before = next }) { Text("更早记录") } }
        }
    }
    if (clearPrompt) AlertDialog(onDismissRequest = { clearPrompt = false }, title = { Text("清空已结束任务的诊断记录？") }, text = { Text("聊天、作品和任务恢复数据保留。") }, confirmButton = {
        TextButton(onClick = { clearPrompt = false; coroutine.launch {
            actionBusy = true
            try { repository.clear(remote); selected = null; before = null; refresh += 1 }
            catch (failure: Exception) { if (failure is CancellationException) throw failure; error = failure.message.orEmpty() }
            finally { actionBusy = false }
        } }) { Text("清空") }
    }, dismissButton = { TextButton(onClick = { clearPrompt = false }) { Text("取消") } })
    if (exportPrompt) AlertDialog(onDismissRequest = { exportPrompt = false }, title = { Text("导出这次任务？") }, text = { Text("诊断包可能包含创作正文与历史消息。") }, confirmButton = {
        TextButton(onClick = { exportPrompt = false; selected?.text("id")?.let { exportTarget = remote to it; exportLauncher.launch("siming-trace-$it.zip") } }) { Text("选择保存位置") }
    }, dismissButton = { TextButton(onClick = { exportPrompt = false }) { Text("取消") } })
}

@Composable
private fun ColumnScope.TraceDetails(repository: TraceInspectionRepository, remote: Boolean, id: String, refresh: Int) {
    var events by remember { mutableStateOf(emptyList<JsonObject>()) }
    var after by remember { mutableIntStateOf(0) }
    var more by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf<JsonObject?>(null) }
    var offset by remember { mutableIntStateOf(0) }
    var content by remember { mutableStateOf("") }
    var total by remember { mutableIntStateOf(0) }
    var nextOffset by remember { mutableIntStateOf(0) }
    LaunchedEffect(id, remote, after, refresh) {
        error = ""
        try { val page = repository.events(remote, id, after); events = if (after == 0) page else (events + page).distinctBy { it.text("event_id") }; more = page.size == 100 }
        catch (failure: Exception) { if (failure is CancellationException) throw failure; error = failure.message.orEmpty() }
    }
    LaunchedEffect(id, remote, selected, offset) {
        content = ""; total = 0; error = ""
        val value = selected ?: return@LaunchedEffect
        if (value["data"]!!.jsonObject.text("content_hash").isEmpty()) return@LaunchedEffect
        try { val part = repository.payload(remote, id, value.text("event_id"), offset); content = part.text("content"); total = part["total_characters"]!!.jsonPrimitive.int; nextOffset = part["next_offset"]!!.jsonPrimitive.int }
        catch (failure: Exception) { if (failure is CancellationException) throw failure; error = failure.message.orEmpty() }
    }
    if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
    LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items(events, key = { it.text("event_id") }) { event ->
            val data = event["data"]!!.jsonObject
            if (event.text("event_type") == "payload") {
                OutlinedButton(onClick = { selected = event; offset = 0 }, modifier = Modifier.fillMaxWidth()) {
                    Text("#${event["sequence"]} ${traceLayerName(data.text("layer"))} · ${data.text("capture_source")}")
                }
                if (selected?.text("event_id") == event.text("event_id")) {
                    val reason = data.text("missing_reason")
                    if (reason.isNotBlank()) Text(if (reason == "recording_not_enabled") "当时未开启完整记录" else "内容不完整：$reason")
                    Text("${data.text("completeness")} · ${data.text("stored_bytes")} 字节")
                    if (content.isNotEmpty()) {
                        SelectionContainer { Text(content, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall) }
                        Row {
                            TextButton(enabled = offset > 0, onClick = { offset = (offset - 65536).coerceAtLeast(0) }) { Text("上一段") }
                            TextButton(enabled = nextOffset < total, onClick = { offset = nextOffset }) { Text("下一段") }
                        }
                    }
                }
            } else if (event.text("event_type") == "usage") {
                Text("提供商实报用量：${data["usage"]}；未返回的字段未知", style = MaterialTheme.typography.bodySmall)
            } else if (event.text("event_type") in setOf("span_started", "span_finished", "http_response")) {
                Text("#${event["sequence"]} ${data.text("kind")} ${data.text("label")} ${traceStatusName(data.text("status"))} ${data.text("status_code")}", style = MaterialTheme.typography.labelMedium)
                if (data.text("parent_span_id").isNotBlank()) Text("↳ 上级步骤 ${data.text("parent_span_id").take(8)}", style = MaterialTheme.typography.labelSmall)
            }
        }
        if (more) item { TextButton(onClick = { after = events.last()["sequence"]!!.jsonPrimitive.int }) { Text("加载后续步骤") } }
    }
}

private fun traceLayerName(layer: String) = mapOf("context_frame" to "上下文帧", "logical_request" to "应用请求", "provider_request" to "实际 API 请求", "provider_response" to "提供商返回", "adapter_output" to "适配后输出", "tool_arguments" to "工具参数", "tool_receipt" to "执行器回执", "model_visible_tool_result" to "模型可见结果", "cli_input" to "CLI 输入", "cli_event" to "CLI 事件")[layer] ?: layer

private fun traceStatusName(status: String) = mapOf("running" to "运行中", "completed" to "已完成", "error" to "失败", "cancelled" to "已取消", "partial" to "部分记录", "interrupted" to "采集中断", "recorded" to "已记录")[status] ?: status
