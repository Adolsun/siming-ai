package com.siming.mobile.data.agent

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal data class MobilePage<T>(
    val values: List<T>,
    val cursor: Int,
    val limit: Int,
    val totalItems: Int,
    val nextCursor: Int?,
) {
    val items: List<T>
        get() = values
}

internal data class MobileTextRange(
    val text: String,
    val metadata: JsonObject,
)

internal fun <T> mobilePage(values: List<T>, cursor: Int, limit: Int): MobilePage<T> {
    val safeCursor = cursor.coerceAtLeast(0)
    val safeLimit = limit.coerceAtLeast(1)
    val visible = values.drop(safeCursor).take(safeLimit)
    val nextCursor = (safeCursor + visible.size).takeIf { it < values.size }
    return MobilePage(
        values = visible,
        cursor = safeCursor,
        limit = safeLimit,
        totalItems = values.size,
        nextCursor = nextCursor,
    )
}

internal fun mobilePageMetadata(page: MobilePage<*>): JsonObject = buildJsonObject {
    put("cursor", page.cursor)
    put("limit", page.limit)
    put("returned_items", page.values.size)
    put("total_items", page.totalItems)
    if (page.nextCursor == null) put("next_cursor", JsonNull)
    else put("next_cursor", page.nextCursor)
    put("has_more", page.nextCursor != null)
}

internal fun mobileTextRange(value: String, offset: Int, maxChars: Int): MobileTextRange {
    val safeOffset = offset.coerceAtLeast(0)
    val totalChars = value.codePointCount(0, value.length)
    val start = safeOffset.coerceAtMost(totalChars)
    val end = (safeOffset.toLong() + maxChars.coerceAtLeast(1))
        .coerceAtMost(totalChars.toLong())
        .toInt()
    return MobileTextRange(
        text = value.substring(value.offsetByCodePoints(0, start), value.offsetByCodePoints(0, end)),
        metadata = buildJsonObject {
            put("offset_chars", safeOffset)
            put("returned_chars", (end - safeOffset).coerceAtLeast(0))
            if (end < totalChars) put("next_offset_chars", end) else put("next_offset_chars", JsonNull)
            put("has_more", end < totalChars)
            put("total_chars", totalChars)
        },
    )
}
