package com.siming.mobile.ui

import android.os.Build
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.automirrored.outlined.MenuBook
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.CloudQueue
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Devices
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.FileOpen
import androidx.compose.material.icons.outlined.Fingerprint
import androidx.compose.material.icons.outlined.Hub
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.automirrored.outlined.LibraryBooks
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.MoreHoriz
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Save
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.siming.mobile.data.local.GatewayConnection
import com.siming.mobile.data.local.LocalConflict
import com.siming.mobile.data.local.ReplicaEntity
import com.siming.mobile.BuildConfig
import java.text.DateFormat
import java.util.Date
import kotlinx.serialization.json.JsonObject

private enum class RootTab(val label: String, val icon: ImageVector) {
    Library("作品", Icons.AutoMirrored.Outlined.LibraryBooks),
    Sync("同步", Icons.Outlined.Sync),
    Settings("关于", Icons.Outlined.Settings),
}

private data class EditorTarget(val entityType: String, val record: ReplicaEntity?)

private data class EntitySection(
    val type: String,
    val label: String,
    val icon: ImageVector,
    val emptyText: String,
)

private val entitySections = listOf(
    EntitySection("chapter", "正文", Icons.AutoMirrored.Outlined.MenuBook, "还没有章节，可离线新建正文"),
    EntitySection("outline", "大纲", Icons.Outlined.MoreHoriz, "还没有大纲节点"),
    EntitySection("character", "角色", Icons.Outlined.Person, "还没有角色资料"),
    EntitySection("world", "世界", Icons.Outlined.Hub, "还没有世界观设定"),
    EntitySection("foreshadowing", "伏笔", Icons.Outlined.Link, "还没有伏笔记录"),
    EntitySection("governance", "治理", Icons.Outlined.WarningAmber, "还没有叙事承诺或治理记录"),
)

@Composable
fun SimingApp(
    viewModel: MainViewModel,
    onScanQr: () -> Unit,
    onPickText: (((String, String) -> Unit) -> Unit),
) {
    val connection by viewModel.connection.collectAsStateWithLifecycle()
    val projects by viewModel.projects.collectAsStateWithLifecycle()
    val ui by viewModel.uiState
    val snackbar = remember { SnackbarHostState() }
    var rootTab by rememberSaveable { mutableStateOf(RootTab.Library) }
    var selectedProjectId by rememberSaveable { mutableStateOf<String?>(null) }

    LaunchedEffect(ui.notice, ui.error) {
        val message = ui.error ?: ui.notice ?: return@LaunchedEffect
        snackbar.showSnackbar(message)
        viewModel.clearNotice()
    }

    val pairingRequired = connection == null && projects.isEmpty()
    if (pairingRequired || ui.pairing != null) {
        PairingScreen(
            viewModel = viewModel,
            allowBack = !pairingRequired,
            onBack = viewModel::cancelPairing,
            onScanQr = onScanQr,
            snackbar = snackbar,
        )
        return
    }

    val selectedProject = projects.firstOrNull { it.projectId == selectedProjectId }
    if (selectedProject != null) {
        ProjectScreen(
            viewModel = viewModel,
            project = selectedProject,
            onBack = { selectedProjectId = null },
            snackbar = snackbar,
        )
        return
    }

    Scaffold(
        containerColor = SimingPaper,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            Column {
                SimingTopBar(connection)
                if (ui.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        },
        bottomBar = {
            NavigationBar(
                containerColor = SimingPaperWarm,
                tonalElevation = 0.dp,
                modifier = Modifier.navigationBarsPadding(),
            ) {
                RootTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = rootTab == tab,
                        onClick = { rootTab = tab },
                        icon = { Icon(tab.icon, contentDescription = null) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        when (rootTab) {
            RootTab.Library -> LibraryScreen(
                modifier = Modifier.padding(padding),
                projects = projects,
                connection = connection,
                viewModel = viewModel,
                onOpenProject = { selectedProjectId = it },
                onScanQr = onScanQr,
                onPickText = onPickText,
            )
            RootTab.Sync -> SyncScreen(
                modifier = Modifier.padding(padding),
                viewModel = viewModel,
                connection = connection,
                onScanQr = onScanQr,
            )
            RootTab.Settings -> AboutScreen(
                modifier = Modifier.padding(padding),
                connection = connection,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SimingTopBar(connection: GatewayConnection?) {
    CenterAlignedTopAppBar(
        title = {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text("司命", fontWeight = FontWeight.SemiBold, letterSpacing = 2.sp)
                Text(
                    if (connection == null) "离线创作" else "自己的 Gateway · 跨设备创作",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        navigationIcon = {
            Surface(
                color = MaterialTheme.colorScheme.primaryContainer,
                shape = CircleShape,
                modifier = Modifier.padding(start = 12.dp).size(34.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("命", color = SimingCinnabar, fontWeight = FontWeight.Bold)
                }
            }
        },
        actions = {
            Icon(
                if (connection == null) Icons.Outlined.CloudOff else Icons.Outlined.CloudQueue,
                contentDescription = if (connection == null) "未连接 Gateway" else "已连接 Gateway",
                tint = if (connection == null) MaterialTheme.colorScheme.onSurfaceVariant else SimingGreen,
                modifier = Modifier.padding(end = 16.dp),
            )
        },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LibraryScreen(
    modifier: Modifier,
    projects: List<ReplicaEntity>,
    connection: GatewayConnection?,
    viewModel: MainViewModel,
    onOpenProject: (String) -> Unit,
    onScanQr: () -> Unit,
    onPickText: (((String, String) -> Unit) -> Unit),
) {
    var showCreate by rememberSaveable { mutableStateOf(false) }
    Column(modifier.fillMaxSize()) {
        if (connection == null) {
            StatusBanner(
                icon = Icons.Outlined.CloudOff,
                title = "当前离线，仍可继续写作",
                detail = "修改已进入本机队列；重新连接自己的 Gateway 后再同步。",
                action = "连接",
                onAction = onScanQr,
                warning = true,
            )
        }
        LazyColumn(
            contentPadding = PaddingValues(18.dp, 18.dp, 18.dp, 96.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxSize(),
        ) {
            item {
                ScreenHeading(
                    kicker = "LOCAL-FIRST LIBRARY",
                    title = "作品库",
                    detail = "创建新小说，或导入已有正文继续二创；资料先落手机，联网后按修订号同步。",
                )
            }
            item {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { showCreate = true }) {
                        Icon(Icons.Outlined.Add, null)
                        Spacer(Modifier.width(7.dp))
                        Text("创作新小说")
                    }
                    OutlinedButton(
                        onClick = {
                            onPickText { name, text ->
                                viewModel.importNovel(name, text, onOpenProject)
                            }
                        },
                    ) {
                        Icon(Icons.Outlined.FileOpen, null)
                        Spacer(Modifier.width(7.dp))
                        Text("导入已有小说")
                    }
                }
            }
            if (projects.isEmpty()) {
                item {
                    EmptyPanel(
                        icon = Icons.AutoMirrored.Outlined.LibraryBooks,
                        title = "这里还没有作品",
                        detail = "可以从零立项，也可以导入 TXT；司命是开源免费的，不需要把正文交给官方服务器。",
                    )
                }
            } else {
                items(projects, key = { it.key }) { project ->
                    ProjectCard(project, onClick = { onOpenProject(project.projectId) })
                }
            }
        }
    }
    if (showCreate) {
        CreateProjectDialog(
            onDismiss = { showCreate = false },
            onCreate = { title, description ->
                showCreate = false
                viewModel.createProject(title, description, onOpenProject)
            },
        )
    }
}

@Composable
private fun ProjectCard(project: ReplicaEntity, onClick: () -> Unit) {
    val title = project.text("title").ifBlank { "未命名作品" }
    val description = project.text("description")
    OutlinedCard(
        onClick = onClick,
        border = BorderStroke(1.dp, if (project.conflicted) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.outlineVariant),
        colors = CardDefaults.outlinedCardColors(containerColor = Color.White),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(15.dp),
        ) {
            Surface(
                color = MaterialTheme.colorScheme.primaryContainer,
                shape = RoundedCornerShape(8.dp),
                modifier = Modifier.size(52.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text(
                        title.take(1),
                        color = SimingCinnabar,
                        fontWeight = FontWeight.Bold,
                        fontSize = 21.sp,
                    )
                }
            }
            Spacer(Modifier.width(13.dp))
            Column(Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (description.isNotBlank()) {
                    Text(
                        description,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (project.dirty) MicroTag("待同步", SimingBlue)
                    if (project.conflicted) MicroTag("有分岔", MaterialTheme.colorScheme.error)
                    if (!project.dirty && !project.conflicted) MicroTag("已落库", SimingGreen)
                }
            }
            Icon(Icons.AutoMirrored.Outlined.ArrowForward, null, Modifier.size(18.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProjectScreen(
    viewModel: MainViewModel,
    project: ReplicaEntity,
    onBack: () -> Unit,
    snackbar: SnackbarHostState,
) {
    var section by rememberSaveable(project.projectId) { mutableStateOf(entitySections.first().type) }
    var editor by remember { mutableStateOf<EditorTarget?>(null) }
    val currentSection = entitySections.first { it.type == section }
    val records by viewModel.entities(project.projectId, section).collectAsStateWithLifecycle(initialValue = emptyList())
    val ui by viewModel.uiState

    if (editor != null) {
        RecordEditorScreen(
            projectId = project.projectId,
            target = requireNotNull(editor),
            viewModel = viewModel,
            onBack = { editor = null },
        )
        return
    }

    Scaffold(
        containerColor = SimingPaper,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            Column {
                CenterAlignedTopAppBar(
                    title = {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(project.text("title").ifBlank { "未命名作品" }, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("离线资料工作台", style = MaterialTheme.typography.labelSmall)
                        }
                    },
                    navigationIcon = {
                        IconButton(onClick = onBack) {
                            Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回作品库")
                        }
                    },
                    actions = {
                        IconButton(onClick = { editor = EditorTarget("project", project) }) {
                            Icon(Icons.Outlined.Edit, "编辑作品资料")
                        }
                    },
                )
                if (ui.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        },
        floatingActionButton = {
            if (section != "assistant") {
                FloatingActionButton(onClick = { editor = EditorTarget(section, null) }) {
                    Icon(Icons.Outlined.Add, "新建${currentSection.label}")
                }
            }
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            Row(
                modifier = Modifier
                    .horizontalScroll(rememberScrollState())
                    .background(SimingPaperWarm)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                entitySections.forEach { item ->
                    AssistChip(
                        onClick = { section = item.type },
                        label = { Text(item.label) },
                        leadingIcon = { Icon(item.icon, null, Modifier.size(17.dp)) },
                        colors = AssistChipDefaults.assistChipColors(
                            containerColor = if (section == item.type) MaterialTheme.colorScheme.primaryContainer else Color.White,
                            labelColor = if (section == item.type) SimingCinnabar else MaterialTheme.colorScheme.onSurface,
                        ),
                        border = AssistChipDefaults.assistChipBorder(
                            enabled = true,
                            borderColor = if (section == item.type) SimingCinnabar else MaterialTheme.colorScheme.outlineVariant,
                        ),
                    )
                }
                AssistChip(
                    onClick = { section = "assistant" },
                    label = { Text("AI") },
                    leadingIcon = { Icon(Icons.Outlined.AutoAwesome, null, Modifier.size(17.dp)) },
                    colors = AssistChipDefaults.assistChipColors(
                        containerColor = if (section == "assistant") MaterialTheme.colorScheme.primaryContainer else Color.White,
                        labelColor = if (section == "assistant") SimingCinnabar else MaterialTheme.colorScheme.onSurface,
                    ),
                )
            }
            if (section == "assistant") {
                AssistantScreen(project.projectId, viewModel)
            } else {
                RecordList(
                    section = currentSection,
                    records = records,
                    onOpen = { editor = EditorTarget(section, it) },
                )
            }
        }
    }
}

@Composable
private fun RecordList(
    section: EntitySection,
    records: List<ReplicaEntity>,
    onOpen: (ReplicaEntity) -> Unit,
) {
    LazyColumn(
        contentPadding = PaddingValues(16.dp, 16.dp, 16.dp, 96.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        item {
            ScreenHeading(
                kicker = section.type.uppercase(),
                title = section.label,
                detail = when (section.type) {
                    "chapter" -> "正文保存在本机 Room 数据库；每次保存都进入可靠同步队列。"
                    "character" -> "角色动机、状态与冲突会随正文一起同步，帮助 AI 减少 OOC。"
                    "world" -> "规则与设定作为独立实体维护，避免二创时漂移。"
                    else -> "这里的修改支持离线保存与版本分岔保护。"
                },
            )
        }
        if (records.isEmpty()) {
            item { EmptyPanel(section.icon, section.emptyText, "点击右下角“＋”开始。") }
        } else {
            items(records, key = { it.key }) { record ->
                RecordCard(section.type, record, onClick = { onOpen(record) })
            }
        }
    }
}

@Composable
private fun RecordCard(entityType: String, record: ReplicaEntity, onClick: () -> Unit) {
    val titleKey = if (entityType == "character") "name" else "title"
    val summaryKey = when (entityType) {
        "chapter" -> "content"
        "outline" -> "summary"
        "character" -> "current_goal"
        "world" -> "content"
        else -> "description"
    }
    OutlinedCard(
        onClick = onClick,
        colors = CardDefaults.outlinedCardColors(containerColor = Color.White),
        border = BorderStroke(
            1.dp,
            when {
                record.conflicted -> MaterialTheme.colorScheme.error
                record.dirty -> MaterialTheme.colorScheme.secondary
                else -> MaterialTheme.colorScheme.outlineVariant
            },
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(15.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    record.text(titleKey).ifBlank { "未命名${entitySections.firstOrNull { it.type == entityType }?.label.orEmpty()}" },
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (record.conflicted) Icon(Icons.Outlined.ErrorOutline, "有版本分岔", tint = MaterialTheme.colorScheme.error)
                else if (record.dirty) Icon(Icons.Outlined.CloudQueue, "等待同步", tint = SimingBlue)
                else Icon(Icons.Outlined.CheckCircle, "已同步", tint = SimingGreen)
            }
            val summary = record.text(summaryKey)
            if (summary.isNotBlank()) {
                Text(
                    summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 3,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Text(
                "修订 ${record.revision} · ${if (record.dirty) "本机有新修改" else "已写入离线库"}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private data class FormField(
    val key: String,
    val label: String,
    val placeholder: String = "",
    val multiline: Boolean = false,
    val numeric: Boolean = false,
)

private fun fieldsFor(type: String): List<FormField> = when (type) {
    "project" -> listOf(
        FormField("title", "作品名"),
        FormField("description", "作品简介", "题材、主线与二创目标", true),
        FormField("custom_style_prompt", "自定义文风约束", "可填写角色口吻与禁忌，帮助减少 OOC", true),
    )
    "chapter" -> listOf(
        FormField("title", "章节名"),
        FormField("content", "正文", "在手机上继续写作…", true),
    )
    "outline" -> listOf(
        FormField("title", "节点标题"),
        FormField("summary", "计划内容", "本章目标、转折与章末钩子", true),
        FormField("sort_order", "顺序", numeric = true),
    )
    "character" -> listOf(
        FormField("name", "角色名"),
        FormField("role_type", "角色定位", "protagonist / supporting / antagonist"),
        FormField("personality", "性格与口吻", "稳定行为方式、表达习惯与禁区", true),
        FormField("background", "背景", multiline = true),
        FormField("current_goal", "当前目标", multiline = true),
        FormField("active_conflict", "当前冲突", multiline = true),
    )
    "world" -> listOf(
        FormField("title", "设定标题"),
        FormField("dimension", "维度", "geography / history / factions / other"),
        FormField("content", "规则与内容", multiline = true),
        FormField("sort_order", "顺序", numeric = true),
    )
    "foreshadowing" -> listOf(
        FormField("title", "伏笔标题"),
        FormField("description", "埋设与回收计划", multiline = true),
        FormField("status", "状态", "open / fulfilled / deferred / abandoned"),
        FormField("importance", "重要度", "low / medium / high"),
        FormField("storyline", "故事线"),
    )
    "governance" -> listOf(
        FormField("title", "叙事承诺"),
        FormField("description", "读者期待与兑现条件", multiline = true),
        FormField("status", "状态", "open / fulfilled / deferred / abandoned"),
        FormField("priority", "优先级", "low / medium / high"),
    )
    else -> emptyList()
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RecordEditorScreen(
    projectId: String,
    target: EditorTarget,
    viewModel: MainViewModel,
    onBack: () -> Unit,
) {
    val fields = remember(target.entityType) { fieldsFor(target.entityType) }
    val values = remember(target.record?.key, target.entityType) {
        mutableStateMapOf<String, String>().apply {
            fields.forEach { field -> put(field.key, target.record?.text(field.key).orEmpty()) }
            when (target.entityType) {
                "outline" -> {
                    putIfAbsent("sort_order", "0")
                }
                "world" -> {
                    putIfAbsent("dimension", "other")
                    putIfAbsent("sort_order", "0")
                }
                "foreshadowing" -> {
                    putIfAbsent("status", "open")
                    putIfAbsent("importance", "medium")
                }
                "governance" -> {
                    putIfAbsent("status", "open")
                    putIfAbsent("priority", "medium")
                }
            }
        }
    }
    var showDelete by remember { mutableStateOf(false) }
    val title = if (target.record == null) "新建${entityLabel(target.entityType)}" else "编辑${entityLabel(target.entityType)}"
    Scaffold(
        containerColor = SimingPaper,
        topBar = {
            CenterAlignedTopAppBar(
                title = { Text(title) },
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
                actions = {
                    if (target.record != null && target.entityType != "project") {
                        IconButton(onClick = { showDelete = true }) {
                            Icon(Icons.Outlined.DeleteOutline, "删除", tint = MaterialTheme.colorScheme.error)
                        }
                    }
                },
            )
        },
        bottomBar = {
            Surface(tonalElevation = 3.dp, color = SimingPaperWarm) {
                Button(
                    onClick = {
                        val mapped = values.mapValues { (key, value) ->
                            if (fields.firstOrNull { it.key == key }?.numeric == true) value.toIntOrNull() ?: 0 else value
                        }.toMutableMap<String, Any?>()
                        when (target.entityType) {
                            "chapter" -> {
                                mapped["word_count"] = values["content"].orEmpty().count { !it.isWhitespace() }
                                mapped["current_version"] = target.record?.number("current_version")?.takeIf { it > 0 } ?: 1
                            }
                            "outline" -> {
                                mapped["node_type"] = target.record?.text("node_type").orEmpty().ifBlank { "chapter" }
                                mapped["status"] = target.record?.text("status").orEmpty().ifBlank { "pending" }
                            }
                            "character" -> mapped["is_evolution_tracked"] = true
                            "world" -> mapped["status"] = target.record?.text("status").orEmpty().ifBlank { "active" }
                        }
                        viewModel.saveRecord(
                            projectId,
                            target.entityType,
                            target.record?.entityId ?: if (target.entityType == "project") projectId else null,
                            mapped,
                            target.record?.payload(),
                            onBack,
                        )
                    },
                    enabled = fields.firstOrNull()?.let { values[it.key].orEmpty().isNotBlank() } ?: false,
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(14.dp),
                ) {
                    Icon(Icons.Outlined.Save, null)
                    Spacer(Modifier.width(8.dp))
                    Text("保存到离线库")
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .imePadding()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(13.dp),
        ) {
            if (target.entityType == "character") {
                StatusBanner(
                    Icons.Outlined.Person,
                    "先写清动机，再让 AI 接着写",
                    "角色目标、冲突、性格与口吻会作为独立资料同步，降低跨章节 OOC。",
                )
            }
            fields.forEach { field ->
                OutlinedTextField(
                    value = values[field.key].orEmpty(),
                    onValueChange = { values[field.key] = it },
                    label = { Text(field.label) },
                    placeholder = { if (field.placeholder.isNotBlank()) Text(field.placeholder) },
                    minLines = if (field.multiline) if (field.key == "content") 14 else 4 else 1,
                    maxLines = if (field.multiline) Int.MAX_VALUE else 1,
                    modifier = Modifier.fillMaxWidth(),
                )
                if (field.key == "content" && target.entityType == "chapter") {
                    Text(
                        "${values[field.key].orEmpty().count { !it.isWhitespace() }} 字 · 自动保存需点击下方按钮确认",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Text(
                "本页不调用本地模型或 CLI。保存立即写入手机数据库；网络不可用时不会丢失。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(24.dp))
        }
    }
    if (showDelete && target.record != null) {
        AlertDialog(
            onDismissRequest = { showDelete = false },
            icon = { Icon(Icons.Outlined.DeleteOutline, null) },
            title = { Text("删除这条${entityLabel(target.entityType)}？") },
            text = { Text("删除会进入同步队列，并在 Gateway 保留 90 天删除标记；不会静默覆盖其他设备的离线修改。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        showDelete = false
                        viewModel.deleteRecord(projectId, target.entityType, target.record.entityId, onBack)
                    },
                ) { Text("确认删除", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { showDelete = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun AssistantScreen(projectId: String, viewModel: MainViewModel) {
    var prompt by rememberSaveable { mutableStateOf("") }
    var scope by rememberSaveable { mutableStateOf("project") }
    val ui by viewModel.uiState
    val connection by viewModel.connection.collectAsStateWithLifecycle()
    Column(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ScreenHeading(
            kicker = "CLOUD AI VIA YOUR GATEWAY",
            title = "项目助手",
            detail = "手机不内置模型、CLI 或 MCP。请求只发给你自己的 Gateway，再由它使用已配置的云模型。",
        )
        if (connection == null) {
            StatusBanner(
                Icons.Outlined.CloudOff,
                "当前处于离线创作",
                "项目资料仍可编辑；连接自己的 Gateway 后才能调用云端 AI。",
                warning = true,
            )
        }
        Row(
            modifier = Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf("project" to "全书", "outline" to "大纲", "characters" to "角色", "worldbuilding" to "世界观").forEach { (value, label) ->
                AssistChip(
                    onClick = { scope = value },
                    label = { Text(label) },
                    colors = AssistChipDefaults.assistChipColors(
                        containerColor = if (scope == value) MaterialTheme.colorScheme.primaryContainer else Color.White,
                    ),
                )
            }
        }
        OutlinedTextField(
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("告诉项目助手要做什么") },
            placeholder = { Text("例如：用质量模式续写下一章，保持林岚的动机与记忆分配规则，并留下章末钩子") },
            minLines = 4,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { viewModel.runAssistant(projectId, scope, prompt) },
            enabled = connection != null && prompt.isNotBlank() && !ui.assistantRunning,
            modifier = Modifier.fillMaxWidth(),
        ) {
            if (ui.assistantRunning) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
            else Icon(Icons.Outlined.AutoAwesome, null)
            Spacer(Modifier.width(8.dp))
            Text(if (ui.assistantRunning) "质量模式执行中…" else "交给自己的 Gateway")
        }
        Card(
            colors = CardDefaults.cardColors(containerColor = Color.White),
            modifier = Modifier.fillMaxWidth().weight(1f),
        ) {
            SelectionContainer {
                Text(
                    ui.assistantOutput.ifBlank { "AI 回复与工具执行过程会显示在这里。电脑关闭时，必须有另一台常开设备在运行 Gateway。" },
                    modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(14.dp),
                    color = if (ui.assistantOutput.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

@Composable
private fun SyncScreen(
    modifier: Modifier,
    viewModel: MainViewModel,
    connection: GatewayConnection?,
    onScanQr: () -> Unit,
) {
    val pending by viewModel.pendingCount.collectAsStateWithLifecycle()
    val cursor by viewModel.cursor.collectAsStateWithLifecycle()
    val conflicts by viewModel.conflicts.collectAsStateWithLifecycle()
    val ui by viewModel.uiState
    var disconnectDialog by remember { mutableStateOf(false) }
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp, 18.dp, 18.dp, 96.dp),
        verticalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        item {
            ScreenHeading(
                kicker = "REVISIONED SYNC",
                title = "同步中枢",
                detail = "先上传本机队列，再拉取 Gateway 修订；同一资料两边都改动时保留双方。",
            )
        }
        item {
            if (connection == null) {
                EmptyPanel(Icons.Outlined.CloudOff, "当前没有 Gateway 授权", "离线副本仍可编辑；扫码后恢复同步。")
                Button(onClick = onScanQr, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Outlined.QrCodeScanner, null)
                    Spacer(Modifier.width(8.dp))
                    Text("扫描新的 Gateway")
                }
            } else {
                GatewayConnectionCard(connection)
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(9.dp), modifier = Modifier.fillMaxWidth()) {
                MetricCard("待上传", pending.toString(), "本机修订", Modifier.weight(1f))
                MetricCard("同步游标", (cursor?.cursor ?: 0).toString(), "全局顺序", Modifier.weight(1f))
                MetricCard("分岔", conflicts.size.toString(), "待选择", Modifier.weight(1f), conflicts.isNotEmpty())
            }
        }
        if (cursor?.lastError != null) {
            item { StatusBanner(Icons.Outlined.ErrorOutline, "上次同步没有完成", cursor?.lastError.orEmpty(), warning = true) }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = viewModel::syncNow,
                    enabled = connection != null && !ui.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Outlined.Sync, null)
                    Spacer(Modifier.width(7.dp))
                    Text("立即同步")
                }
                OutlinedButton(
                    onClick = viewModel::bootstrap,
                    enabled = connection != null && !ui.busy,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Outlined.Refresh, null)
                    Spacer(Modifier.width(7.dp))
                    Text("重新校验")
                }
            }
        }
        item {
            Text("版本分岔", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text("双方原始快照会保留在 Gateway；选择只会追加一个新修订。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (conflicts.isEmpty()) {
            item { StatusBanner(Icons.Outlined.CheckCircle, "没有待处理分岔", "所有设备都沿同一条修订线继续。") }
        } else {
            items(conflicts, key = { it.id }) { conflict -> ConflictCard(conflict, viewModel) }
        }
        if (connection != null) {
            item {
                HorizontalDivider(Modifier.padding(vertical = 5.dp))
                OutlinedButton(onClick = { disconnectDialog = true }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Outlined.CloudOff, null)
                    Spacer(Modifier.width(8.dp))
                    Text("断开这台设备")
                }
            }
        }
    }
    if (disconnectDialog) {
        AlertDialog(
            onDismissRequest = { disconnectDialog = false },
            title = { Text("断开 Gateway？") },
            text = { Text("联网时会同时撤销 Gateway 授权。若 Gateway 暂时不可达，本机会先断开并提示你稍后到管理页补撤销。") },
            confirmButton = {
                TextButton(onClick = { disconnectDialog = false; viewModel.disconnect(false) }) { Text("保留离线作品") }
            },
            dismissButton = {
                TextButton(onClick = { disconnectDialog = false; viewModel.disconnect(true) }) {
                    Text("同时清除本机副本", color = MaterialTheme.colorScheme.error)
                }
            },
        )
    }
}

@Composable
private fun GatewayConnectionCard(connection: GatewayConnection) {
    OutlinedCard(colors = CardDefaults.outlinedCardColors(containerColor = Color.White)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(color = MaterialTheme.colorScheme.tertiaryContainer, shape = CircleShape, modifier = Modifier.size(42.dp)) {
                    Box(contentAlignment = Alignment.Center) { Icon(Icons.Outlined.Devices, null, tint = SimingGreen) }
                }
                Spacer(Modifier.width(11.dp))
                Column(Modifier.weight(1f)) {
                    Text(connection.gatewayName, fontWeight = FontWeight.SemiBold)
                    Text(connection.baseUrl, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                MicroTag("已授权", SimingGreen)
            }
            HorizontalDivider()
            Text("指纹 ${compactFingerprint(connection.gatewayFingerprint)}", fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelSmall)
            Text("角色 ${connection.deviceRole} · 协议 v${connection.protocolVersion}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ConflictCard(conflict: LocalConflict, viewModel: MainViewModel) {
    var expanded by remember { mutableStateOf(false) }
    OutlinedCard(
        colors = CardDefaults.outlinedCardColors(containerColor = Color(0xFFFFFAF0)),
        border = BorderStroke(1.dp, Color(0xFFD8AD6F)),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.WarningAmber, null, tint = Color(0xFFA66A16))
                Spacer(Modifier.width(8.dp))
                Text("${entityLabel(conflict.entityType)}有两个版本", fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text("修订 ${conflict.serverRevision}", style = MaterialTheme.typography.labelSmall)
            }
            TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "收起双方快照" else "比较双方快照") }
            if (expanded) {
                SnapshotBox("Gateway 当前版本", conflict.serverPayloadJson)
                SnapshotBox("手机离线版本", conflict.clientPayloadJson)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { viewModel.resolveConflict(conflict, "server") }, modifier = Modifier.weight(1f)) { Text("保留 Gateway") }
                Button(onClick = { viewModel.resolveConflict(conflict, "client") }, modifier = Modifier.weight(1f)) { Text("采用手机") }
            }
        }
    }
}

@Composable
private fun SnapshotBox(label: String, raw: String?) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
        SelectionContainer {
            Text(
                raw ?: "（删除记录）",
                fontFamily = FontFamily.Monospace,
                fontSize = 11.sp,
                modifier = Modifier.fillMaxWidth().background(Color.White, RoundedCornerShape(6.dp)).padding(9.dp),
                maxLines = 10,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun AboutScreen(modifier: Modifier, connection: GatewayConnection?) {
    val uriHandler = LocalUriHandler.current
    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(18.dp, 18.dp, 18.dp, 96.dp),
        verticalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        item {
            ScreenHeading(
                kicker = "OPEN SOURCE · FREE",
                title = "开源、免费、数据归你",
                detail = "司命手机版没有本地模型、CLI、MCP 或训练模块；它专注于离线创作与连接自己的 Gateway。",
            )
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = SimingPaperWarm)) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
                    AboutRow(Icons.Outlined.Lock, "官方不转接正文", "设备只连接你配置的 Gateway")
                    AboutRow(Icons.AutoMirrored.Outlined.LibraryBooks, "新作与二创", "从零建书，或导入已有 TXT 继续创作")
                    AboutRow(Icons.Outlined.Person, "连续性资料", "角色目标、冲突和世界规则独立同步，帮助减少 OOC")
                    AboutRow(Icons.Outlined.CloudOff, "离线仍可写", "Room 本地库 + WorkManager 可靠队列")
                }
            }
        }
        item {
            OutlinedButton(
                onClick = { uriHandler.openUri("https://github.com/teangtang1122/siming-ai") },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Outlined.Info, null)
                Spacer(Modifier.width(8.dp))
                Text("查看开源代码与许可证")
            }
        }
        item {
            Text("版本 ${BuildConfig.VERSION_NAME} · 同步协议 v${BuildConfig.SYNC_PROTOCOL_VERSION}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                if (connection == null) "当前未连接 Gateway" else "当前连接：${connection.gatewayName}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun AboutRow(icon: ImageVector, title: String, detail: String) {
    Row(verticalAlignment = Alignment.Top) {
        Icon(icon, null, tint = SimingCinnabar, modifier = Modifier.size(21.dp))
        Spacer(Modifier.width(11.dp))
        Column {
            Text(title, fontWeight = FontWeight.SemiBold)
            Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun PairingScreen(
    viewModel: MainViewModel,
    allowBack: Boolean,
    onBack: () -> Unit,
    onScanQr: () -> Unit,
    snackbar: SnackbarHostState,
) {
    val ui by viewModel.uiState
    var deviceName by rememberSaveable { mutableStateOf("${Build.MANUFACTURER} ${Build.MODEL}".trim()) }
    var manual by rememberSaveable { mutableStateOf(false) }
    var raw by rememberSaveable { mutableStateOf("") }
    Scaffold(
        containerColor = SimingPaper,
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            if (allowBack) {
                Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") }
                    Text("连接 Gateway", fontWeight = FontWeight.SemiBold)
                }
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Surface(
                color = MaterialTheme.colorScheme.primaryContainer,
                shape = CircleShape,
                modifier = Modifier.size(76.dp),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Text("司命", color = SimingCinnabar, fontWeight = FontWeight.Bold, fontSize = 21.sp)
                }
            }
            Spacer(Modifier.height(18.dp))
            Text("连接自己的 Gateway", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
            Text(
                "没有司命官方数据服务器。请在电脑或常开设备上启用 Gateway，再用手机完成一次性配对。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.padding(top = 8.dp),
            )
            Spacer(Modifier.height(22.dp))
            if (ui.pairing == null) {
                Button(onClick = onScanQr, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                    Icon(Icons.Outlined.QrCodeScanner, null)
                    Spacer(Modifier.width(9.dp))
                    Text("扫描电脑上的二维码")
                }
                TextButton(onClick = { manual = !manual }) { Text(if (manual) "收起手动粘贴" else "相机不可用？手动粘贴配对内容") }
                if (manual) {
                    OutlinedTextField(
                        value = raw,
                        onValueChange = { if (it.length <= 16_384) raw = it },
                        label = { Text("配对 JSON") },
                        minLines = 5,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedButton(
                        onClick = { viewModel.acceptPairingQr(raw) },
                        enabled = raw.isNotBlank(),
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    ) { Text("验证签名") }
                }
            } else {
                val pairing = requireNotNull(ui.pairing)
                OutlinedCard(colors = CardDefaults.outlinedCardColors(containerColor = Color.White)) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.Fingerprint, null, tint = SimingGreen)
                            Spacer(Modifier.width(8.dp))
                            Text("Gateway 签名已验证", color = SimingGreen, fontWeight = FontWeight.SemiBold)
                        }
                        Text(pairing.gatewayName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text(pairing.gatewayUrl, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
                        HorizontalDivider()
                        Text("指纹", style = MaterialTheme.typography.labelSmall)
                        SelectionContainer { Text(pairing.gatewayFingerprint.chunked(4).joinToString(" "), fontFamily = FontFamily.Monospace, fontSize = 11.sp) }
                    }
                }
                OutlinedTextField(
                    value = deviceName,
                    onValueChange = { if (it.length <= 120) deviceName = it },
                    label = { Text("这台设备的名称") },
                    modifier = Modifier.fillMaxWidth().padding(top = 13.dp),
                )
                if (!ui.pairingStatus.isNullOrBlank()) {
                    StatusBanner(
                        Icons.Outlined.Devices,
                        ui.pairingStatus.orEmpty(),
                        if (ui.busy) ui.activity else "只在确认地址和指纹属于你时继续。",
                        warning = ui.busy,
                        modifier = Modifier.padding(top = 12.dp),
                    )
                }
                Button(
                    onClick = { viewModel.connectPairing(deviceName) },
                    enabled = deviceName.isNotBlank() && !ui.busy,
                    modifier = Modifier.fillMaxWidth().height(50.dp).padding(top = 12.dp),
                ) {
                    if (ui.busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    else Icon(Icons.Outlined.Link, null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (ui.busy) "等待电脑确认…" else "提交配对申请")
                }
                TextButton(onClick = viewModel::cancelPairing, enabled = !ui.busy) { Text("取消并清除二维码") }
            }
            Spacer(Modifier.height(26.dp))
            StatusBanner(
                Icons.Outlined.Info,
                "开源免费，不托管正文",
                "配对密钥只存在于本页内存且十分钟失效；访问令牌由 Android Keystore 加密。",
            )
        }
    }
}

@Composable
private fun CreateProjectDialog(onDismiss: () -> Unit, onCreate: (String, String) -> Unit) {
    var title by rememberSaveable { mutableStateOf("") }
    var description by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { Icon(Icons.Outlined.Add, null) },
        title = { Text("创作新小说") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(title, { title = it.take(200) }, label = { Text("作品名") }, singleLine = true)
                OutlinedTextField(description, { description = it }, label = { Text("一句话创意（可选）") }, minLines = 3)
                Text("无需联网即可建档；首次同步时 Gateway 会把这部作品显式加入同步。", style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = { TextButton(onClick = { onCreate(title, description) }, enabled = title.isNotBlank()) { Text("创建") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}

@Composable
private fun ScreenHeading(kicker: String, title: String, detail: String) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(kicker, color = SimingCinnabar, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.5.sp)
        Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Text(detail, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun EmptyPanel(icon: ImageVector, title: String, detail: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
        modifier = Modifier.fillMaxWidth().height(230.dp).background(Color.White, RoundedCornerShape(10.dp)).padding(24.dp),
    ) {
        Icon(icon, null, tint = SimingCinnabar, modifier = Modifier.size(36.dp))
        Spacer(Modifier.height(10.dp))
        Text(title, fontWeight = FontWeight.SemiBold)
        Text(detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun StatusBanner(
    icon: ImageVector,
    title: String,
    detail: String,
    modifier: Modifier = Modifier,
    action: String? = null,
    onAction: (() -> Unit)? = null,
    warning: Boolean = false,
) {
    val background = if (warning) Color(0xFFFFF7E8) else MaterialTheme.colorScheme.secondaryContainer
    val foreground = if (warning) Color(0xFF704409) else MaterialTheme.colorScheme.onSecondaryContainer
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = modifier.fillMaxWidth().background(background).padding(13.dp),
    ) {
        Icon(icon, null, tint = foreground)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = foreground, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyMedium)
            Text(detail, color = foreground.copy(alpha = 0.84f), style = MaterialTheme.typography.bodySmall)
        }
        if (action != null && onAction != null) TextButton(onClick = onAction) { Text(action) }
    }
}

@Composable
private fun MetricCard(label: String, value: String, detail: String, modifier: Modifier, warning: Boolean = false) {
    Card(
        colors = CardDefaults.cardColors(containerColor = if (warning) Color(0xFFFFF7E8) else Color.White),
        modifier = modifier,
    ) {
        Column(Modifier.padding(11.dp)) {
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, fontFamily = FontFamily.Monospace, fontSize = 22.sp, fontWeight = FontWeight.SemiBold, color = if (warning) Color(0xFFA66A16) else SimingInk)
            Text(detail, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun MicroTag(text: String, color: Color) {
    Text(
        text,
        color = color,
        fontSize = 10.sp,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.background(color.copy(alpha = 0.09f), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

private fun entityLabel(type: String): String = when (type) {
    "project" -> "作品资料"
    "chapter" -> "章节"
    "outline" -> "大纲"
    "character" -> "角色"
    "world" -> "世界观"
    "foreshadowing" -> "伏笔"
    "governance" -> "叙事治理"
    else -> "资料"
}

private fun compactFingerprint(value: String): String =
    if (value.length <= 20) value else "${value.take(10)}…${value.takeLast(8)}"
