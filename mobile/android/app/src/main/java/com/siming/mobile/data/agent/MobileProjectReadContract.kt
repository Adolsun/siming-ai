package com.siming.mobile.data.agent

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

internal val mobileProjectInfoFields = listOf(
    "id", "title", "description", "tags", "narrative_perspective", "writing_style",
    "forbidden_sentence_patterns", "rhetoric_guidelines", "short_sentences",
    "custom_style_prompt", "daily_word_goal", "storage_mode", "folder_path", "created_at", "updated_at",
)

/** Exact setting ranges; overview previews are never presented as complete values. */
internal fun mobileProjectInfoPage(source: JsonObject, args: JsonObject): JsonObject {
    fun argument(name: String): String = (args[name] as? JsonPrimitive)?.contentOrNull.orEmpty()
    val field = argument("field")
    require(field.isBlank() || field in mobileProjectInfoFields) { "field 不属于可读取的作品设置字段" }
    val fields = if (field.isBlank()) mobileProjectInfoFields else listOf("id", field).distinct()
    val count = (argument("max_chars").toIntOrNull()?.takeIf { it != 0 } ?: 2000).coerceIn(1, 2000)
    val offset = if (field.isBlank()) 0 else (argument("offset_chars").toIntOrNull() ?: 0).coerceAtLeast(0)
    val ranges = mutableMapOf<String, JsonObject>()
    val data = buildJsonObject {
        fields.forEach { name ->
            var value = source[name] ?: JsonNull
            if (value is JsonObject || value is JsonArray) value = JsonPrimitive(value.toString())
            if (value is JsonPrimitive && value.isString && name != "id") {
                val text = value.content
                val size = if (field.isNotBlank()) count else if (name == "title") 200 else 100
                val total = text.codePointCount(0, text.length)
                val start = text.offsetByCodePoints(0, offset.coerceAtMost(total))
                val visibleCount = minOf(size, (total - offset).coerceAtLeast(0))
                val visible = text.substring(start, text.offsetByCodePoints(start, visibleCount))
                val hasMore = offset + visibleCount < total
                value = JsonPrimitive(visible)
                if (field.isNotBlank() || hasMore) {
                    fun readArguments(nextOffset: Int, chars: Int) = buildJsonObject {
                        put("project_id", source["id"] ?: JsonNull)
                        put("field", name)
                        put("offset_chars", nextOffset)
                        put("max_chars", chars)
                    }
                    ranges[name] = buildJsonObject {
                        put("offset_chars", offset)
                        put("returned_chars", visibleCount)
                        put("total_chars", total)
                        if (hasMore) put("next_offset_chars", offset + visibleCount) else put("next_offset_chars", JsonNull)
                        put("has_more", hasMore)
                        put("read_arguments", readArguments(0, 2000))
                        if (hasMore) put("next_arguments", readArguments(offset + visibleCount, count))
                    }
                }
            }
            put(name, value)
        }
    }
    return buildJsonObject {
        put("data", data)
        put("field_ranges", JsonObject(ranges))
    }
}
