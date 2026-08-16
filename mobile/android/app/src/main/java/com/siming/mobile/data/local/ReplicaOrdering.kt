package com.siming.mobile.data.local

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/**
 * Return unstructured chapter replicas in their canonical PC source order.
 *
 * Room's local write time is a transport detail: a bootstrap can insert every
 * chapter in one transaction, so it cannot be used to reconstruct the source
 * order. Imported, unstructured projects have no outline ordering and use the
 * chapter's immutable PC creation time instead.
 */
fun orderReplicaEntities(entityType: String, records: List<ReplicaEntity>): List<ReplicaEntity> {
    if (entityType != "chapter" || records.size < 2) return records
    return records
        .map { record -> ChapterOrder(record, payload(record)) }
        .sortedWith(
            compareBy<ChapterOrder> { it.createdAt == null }
                .thenBy { it.createdAt.orEmpty() }
                .thenBy { it.titleNumber ?: Int.MAX_VALUE }
                .thenBy { it.record.localModifiedAt }
                .thenBy { it.record.entityId },
        )
        .map(ChapterOrder::record)
}

private data class ChapterOrder(
    val record: ReplicaEntity,
    val payload: JsonObject?,
) {
    val createdAt = payload?.string("created_at")?.takeIf(String::isNotBlank)
    val titleNumber = payload?.string("title")?.let(::chapterNumber)
}

private val chapterNumberPatterns = listOf(
    Regex("""第\s*(\d+)\s*[章节回]"""),
    Regex("""(?:chapter|chap\.?)\s*(\d+)""", RegexOption.IGNORE_CASE),
    Regex("""^\s*(\d+)\b"""),
)

private fun chapterNumber(title: String): Int? = chapterNumberPatterns
    .firstNotNullOfOrNull { pattern -> pattern.find(title)?.groupValues?.getOrNull(1)?.toIntOrNull() }

private fun payload(record: ReplicaEntity): JsonObject? = record.payloadJson?.let { raw ->
    runCatching { replicaJson.parseToJsonElement(raw) as? JsonObject }.getOrNull()
}

private fun JsonObject.string(name: String): String = get(name)?.jsonPrimitive?.contentOrNull.orEmpty()

private val replicaJson = Json {
    ignoreUnknownKeys = true
}
