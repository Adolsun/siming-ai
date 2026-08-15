package com.siming.mobile.data.agent

import android.content.Context
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** Runtime view of the build-generated PC PromptSpec and tool catalog. */
internal class PcPromptContract(context: Context) {
    private val json = Json { ignoreUnknownKeys = true }
    private val root = context.assets.open(ASSET_NAME).bufferedReader(Charsets.UTF_8).use { reader ->
        json.parseToJsonElement(reader.readText()) as JsonObject
    }

    val sourceHash: String = root.string("source_sha256")
    val toolSchemas: JsonArray = root["tool_schemas"] as JsonArray
    val toolNames: Set<String> = (root["tool_names"] as JsonArray)
        .mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        .toSet()

    fun workspaceSystem(scope: String): String = root.string("workspace_system_template").fill(
        "scope_label" to SCOPE_LABELS.getOrDefault(scope, "项目规划"),
        "outline_batch_count" to "3",
        "auto_apply" to "是",
    )

    fun initialUserMessage(
        project: JsonObject,
        styleContext: String,
        userMessage: String,
    ): String = root.string("workspace_initial_user_template").fill(
        "project_title" to project.string("title").ifBlank { "未命名作品" },
        "project_description" to project.string("description").ifBlank { "暂无" },
        "style_context" to styleContext,
        "history_text" to "（无历史对话）",
        "selected_context" to "当前没有选中对象。",
        "previous_search_context" to "",
        "memory_context" to "",
        "user_message" to userMessage.trim(),
    )

    fun styleContext(project: JsonObject): String {
        val short = project.boolean("short_sentences")
        val rhetoric = project.string("rhetoric_guidelines")
        val custom = project.string("custom_style_prompt")
        val key = "short=$short;rhetoric=${rhetoric.isNotBlank()};custom=${custom.isNotBlank()}"
        val templates = root["style_templates"] as JsonObject
        val perspective = when (project.string("narrative_perspective")) {
            "first_person" -> "第一人称"
            "omniscient" -> "上帝视角"
            else -> "第三人称"
        }
        val writingStyle = when (project.string("writing_style")) {
            "vivid" -> "华丽生动"
            "concise" -> "白描简洁"
            "serious" -> "严肃"
            "humorous" -> "幽默"
            "poetic" -> "诗意"
            else -> "自然"
        }
        return templates.string(key).fill(
            "perspective" to perspective,
            "writing_style" to writingStyle,
            "rhetoric_guidelines" to rhetoric,
            "custom_style_prompt" to custom,
        )
    }

    fun chapterMessages(
        mode: String,
        project: JsonObject,
        outlineContext: String,
        worldContext: String,
        characterProfiles: String,
        recentSummaries: String,
        requirements: String,
    ): List<JsonObject> {
        val chapter = root["chapter"] as JsonObject
        val style = styleContext(project)
        val directives = writingDirectives(
            project = project,
            outlineContext = outlineContext,
            worldContext = worldContext,
            requirements = requirements,
        )
        val systemTemplate = if (mode == "fast") {
            chapter.string("fast_system_template")
        } else {
            chapter.string("quality_system_template")
        }
        val system = systemTemplate.fill(
            "writing_directives" to directives,
            "style_context" to style,
        )
        var user = chapter.string("user_template").fill(
            "requirements" to requirements,
            "outline_context" to outlineContext,
            "world_context" to worldContext,
            "character_profiles" to characterProfiles,
            "recent_summaries" to recentSummaries,
        )
        if (requirements.isBlank()) {
            user = user.replace("【写作要求】\n\n\n\n", "")
        }
        return listOf(message("system", system), message("user", user))
    }

    fun writerSystem(kind: String, styleContext: String, dimension: String = "culture"): String {
        val systems = root["writer_systems"] as JsonObject
        val template = if (kind == "world") {
            (systems["world"] as JsonObject).string(dimension)
        } else {
            systems.string(kind)
        }
        return template.fill("style_context" to styleContext)
    }

    fun writerOutputTool(kind: String): JsonArray = JsonArray(
        listOf((root["writer_output_tools"] as JsonObject).getValue(kind)),
    )

    fun characterWriterUser(
        requirements: String,
        name: String,
        roleType: String,
        worldContext: String,
        existingCharacters: String,
    ): String {
        val existing = existingCharacters.isNotBlank() && existingCharacters != "暂无角色。"
        val key = "requirements=${requirements.isNotBlank()};name=${name.isNotBlank()};" +
            "role=${roleType.isNotBlank()};existing=$existing"
        val templates = (root["writer_user_templates"] as JsonObject)["character"] as JsonObject
        return templates.string(key).fill(
            "requirements" to requirements,
            "name" to name,
            "role_type" to roleType,
            "world_context" to worldContext,
            "existing_characters" to existingCharacters,
        )
    }

    fun outlineWriterUser(
        requirements: String,
        parentContext: String,
        existingOutline: String,
        worldContext: String,
        existingCharacters: String,
        batchCount: Int,
    ): String {
        val world = worldContext.isNotBlank() && worldContext != "暂无世界观设定。"
        val existing = existingCharacters.isNotBlank() && existingCharacters != "暂无角色。"
        val key = "requirements=${requirements.isNotBlank()};parent=${parentContext.isNotBlank()};" +
            "world=$world;existing=$existing"
        val templates = (root["writer_user_templates"] as JsonObject)["outline"] as JsonObject
        return templates.string(key).fill(
            "requirements" to requirements,
            "parent_context" to parentContext,
            "existing_outline" to existingOutline,
            "world_context" to worldContext,
            "existing_characters" to existingCharacters,
            "batch_count" to batchCount.toString(),
        )
    }

    fun worldWriterUser(
        requirements: String,
        title: String,
        dimension: String,
        worldContext: String,
    ): String {
        val normalizedDimension = dimension.takeIf { it in WORLD_DIMENSIONS } ?: "culture"
        val key = "requirements=${requirements.isNotBlank()};title=${title.isNotBlank()};" +
            "dimension=$normalizedDimension"
        val templates = (root["writer_user_templates"] as JsonObject)["world"] as JsonObject
        return templates.string(key).fill(
            "requirements" to requirements,
            "title" to title,
            "world_context" to worldContext,
        )
    }

    private fun writingDirectives(
        project: JsonObject,
        outlineContext: String,
        worldContext: String,
        requirements: String,
    ): String {
        val rules = root["writing_rules"] as JsonObject
        val tags = project.tags()
        val genreText = listOf(
            project.string("title"),
            project.string("description"),
            tags.joinToString(" "),
            worldContext.take(2_000),
            requirements,
        ).joinToString("\n").lowercase()
        val taskText = listOf(requirements, outlineContext.take(2_000), "", "", "")
            .joinToString("\n")
            .lowercase()
        val genres = selectRules(rules["genres"] as JsonArray, genreText, tags, 2)
        var tasks = selectRules(rules["tasks"] as JsonArray, taskText, emptyList(), 3)
        if (genres.isEmpty() && tasks.isEmpty()) tasks = listOf(rules["default"] as JsonObject)
        return buildList {
            add("【本次写作专项提示】")
            if (genres.isNotEmpty()) {
                add("类型路由：" + genres.joinToString("、") { it.string("label") })
                genres.forEach { add("【${it.string("label")}写法】\n${it.string("body")}") }
            }
            if (tasks.isNotEmpty()) {
                add("任务路由：" + tasks.joinToString("、") { it.string("label") })
                tasks.forEach { add("【${it.string("label")}写法】\n${it.string("body")}") }
            }
            add("以上规则只用于生成正文；不要复述规则、不要输出分析、不要改变既定事实。")
        }.joinToString("\n")
    }

    private fun selectRules(
        rules: JsonArray,
        text: String,
        tags: List<String>,
        limit: Int,
    ): List<JsonObject> = rules.mapIndexedNotNull { index, raw ->
        val rule = raw as? JsonObject ?: return@mapIndexedNotNull null
        val keywords = (rule["keywords"] as? JsonArray).orEmpty()
            .mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        val score = keywords.sumOf { keyword ->
            (if (tags.any { tag -> keyword == tag || keyword in tag }) 3 else 0) +
                (if (keyword.lowercase() in text) 1 else 0)
        }
        if (score > 0) Triple(score, index, rule) else null
    }.sortedWith(compareByDescending<Triple<Int, Int, JsonObject>> { it.first }.thenBy { it.second })
        .take(limit)
        .map { it.third }

    private fun JsonObject.tags(): List<String> {
        val value = get("tags")
        if (value is JsonArray) return value.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
        val raw = (value as? JsonPrimitive)?.contentOrNull.orEmpty().trim()
        if (raw.isBlank()) return emptyList()
        val parsed = runCatching { json.parseToJsonElement(raw) as? JsonArray }.getOrNull()
        return parsed?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            ?: raw.replace('，', ',').split(',').map(String::trim).filter(String::isNotBlank)
    }

    private fun message(role: String, content: String) = JsonObject(
        mapOf("role" to JsonPrimitive(role), "content" to JsonPrimitive(content)),
    )

    private fun String.fill(vararg values: Pair<String, String>): String =
        values.fold(this) { current, (key, value) -> current.replace("{{${key}}}", value) }

    private fun JsonObject.string(name: String): String =
        (get(name) as? JsonPrimitive)?.contentOrNull.orEmpty()

    private fun JsonObject.boolean(name: String): Boolean =
        (get(name) as? JsonPrimitive)?.contentOrNull?.toBooleanStrictOrNull() ?: false

    companion object {
        const val ASSET_NAME = "pc_workspace_prompt_contract.json"
        private val SCOPE_LABELS = mapOf(
            "outline" to "大纲规划",
            "characters" to "角色管理",
            "worldbuilding" to "世界观管理",
            "project" to "项目规划",
        )
        private val WORLD_DIMENSIONS = setOf(
            "geography",
            "history",
            "factions",
            "power_system",
            "races",
            "culture",
        )
    }
}
