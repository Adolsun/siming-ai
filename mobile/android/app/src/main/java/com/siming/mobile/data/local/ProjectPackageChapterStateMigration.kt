package com.siming.mobile.data.local

import androidx.sqlite.db.SupportSQLiteDatabase
import com.siming.mobile.data.ProjectPackageChapterCatalogingState
import java.security.MessageDigest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull

/** One-time Room 3 -> 4 data repair, separate from normal snapshot reads and writes. */
internal fun restoreImportedChapterCatalogingState(db: SupportSQLiteDatabase) {
    data class Row(val key: String, val entityId: String, val type: String, val payload: JsonObject)
    val projectIds = buildList {
        db.query("SELECT projectId FROM project_packages").use { cursor ->
            while (cursor.moveToNext()) add(cursor.getString(0))
        }
    }
    for (projectId in projectIds) {
        val projectRows = mutableListOf<Row>()
        db.query(
            "SELECT `key`, entityId, entityType, payloadJson FROM replica_entities " +
                "WHERE projectId = ? AND operation = 'upsert' " +
                "AND entityType IN ('chapter', 'chapter_version', 'summary')",
            arrayOf(projectId),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val payload = runCatching { Json.parseToJsonElement(cursor.getString(3)) as? JsonObject }.getOrNull()
                    ?: continue
                projectRows += Row(cursor.getString(0), cursor.getString(1), cursor.getString(2), payload)
            }
        }
        fun records(type: String, recordType: String) = projectRows.filter {
            it.type == type && (it.payload["_record_type"] as? JsonPrimitive)?.contentOrNull == recordType
        }
        val state = ProjectPackageChapterCatalogingState(
            records("chapter_version", "chapter_snapshot").map(Row::payload),
            records("summary", "chapter_summary").map(Row::payload),
        )
        for (chapter in records("chapter", "chapter")) {
            val known = (chapter.payload["cataloging_required"] as? JsonPrimitive)
                ?.takeUnless { it.isString }?.booleanOrNull
            if (known != null) continue
            val chapterPayload = JsonObject(chapter.payload + mapOf("id" to JsonPrimitive(chapter.entityId)))
            val encoded = JsonObject(chapter.payload + mapOf(
                "cataloging_required" to JsonPrimitive(state.required(chapterPayload)),
            )).toString()
            val hash = MessageDigest.getInstance("SHA-256").digest(encoded.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
            // This is derived state, not an author edit: preserve revision,
            // dirty/conflict flags, timestamps and every existing outbox row.
            db.execSQL("UPDATE replica_entities SET payloadJson = ?, contentHash = ? WHERE `key` = ?",
                arrayOf(encoded, hash, chapter.key))
        }
    }
}
