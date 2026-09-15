package com.siming.mobile.data

import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneOffset
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull

/** The same v1 import evidence contract as ProjectPackageChapterCatalogingState on PC. */
internal class ProjectPackageChapterCatalogingState(
    snapshots: List<JsonObject>,
    summaries: List<JsonObject>,
) {
    private val snapshotsByChapter = snapshots.groupBy { it.text("chapter_id") }
    private val summariesByChapter = summaries.groupBy { it.text("chapter_id") }

    fun required(chapter: JsonObject): Boolean {
        val content = chapter.text("content")
        if (content.isBlank()) return false
        val chapterId = chapter.text("id")
        val version = (chapter["current_version"] as? JsonPrimitive)?.takeUnless { it.isString }?.intOrNull
        if (chapterId.isBlank() || version == null || version < 1) return true
        val summaryTimes = summariesByChapter[chapterId].orEmpty()
            .filter { it.text("summary_text").isNotBlank() }
            .mapNotNull { timestamp(it.text("updated_at").ifEmpty { it.text("created_at") }) }
        return snapshotsByChapter[chapterId].orEmpty().none { snapshot ->
            val snapshotVersion = (snapshot["version_number"] as? JsonPrimitive)?.takeUnless { it.isString }?.intOrNull
            val savedAt = timestamp(snapshot.text("created_at"))
            snapshotVersion == version && snapshot.text("content") == content && savedAt != null &&
                summaryTimes.any { !it.isBefore(savedAt) }
        }
    }

    private fun timestamp(value: String): Instant? =
        runCatching { OffsetDateTime.parse(value).toInstant() }.getOrNull()
            ?: runCatching { LocalDateTime.parse(value).toInstant(ZoneOffset.UTC) }.getOrNull()

    private fun JsonObject.text(field: String): String =
        (get(field) as? JsonPrimitive)?.contentOrNull.orEmpty()
}
