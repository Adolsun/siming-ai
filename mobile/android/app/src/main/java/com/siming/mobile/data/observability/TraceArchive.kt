package com.siming.mobile.data.observability

import java.io.OutputStream
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import kotlinx.serialization.json.*

/** One trace, bounded payload pages, same redaction pipeline again at export. */
internal suspend fun writeTraceArchive(
    output: OutputStream, trace: JsonObject, applicationVersion: String,
    events: suspend (Int) -> List<JsonObject>,
    payload: suspend (String, Int) -> JsonObject,
    stillExists: suspend () -> Boolean,
) {
    ZipOutputStream(output).use { zip ->
        val files = mutableListOf<JsonElement>()
        fun inventory(name: String, size: Int, hash: String) {
            files += buildJsonObject { put("path", name); put("bytes", size); put("sha256", hash) }
        }
        fun entry(name: String, text: String) {
            val raw = text.toByteArray()
            zip.putNextEntry(ZipEntry(name)); zip.write(raw); zip.closeEntry()
            inventory(name, raw.size, TraceRedaction.hash(text))
        }
        zip.putNextEntry(ZipEntry("events.jsonl"))
        var after = 0
        var size = 0
        val digest = MessageDigest.getInstance("SHA-256")
        while (true) {
            val page = events(after)
            if (page.isEmpty()) break
            page.forEach {
                val raw = (TraceRedaction.clean(it).toString() + "\n").toByteArray()
                zip.write(raw); digest.update(raw); size += raw.size
            }
            after = page.last()["sequence"]!!.jsonPrimitive.int
        }
        zip.closeEntry()
        inventory("events.jsonl", size, digest.digest().joinToString("") { "%02x".format(it) })
        after = 0
        while (true) {
            val page = events(after)
            if (page.isEmpty()) break
            for (event in page) {
                if (event["data"]!!.jsonObject.text("content_hash").isEmpty()) continue
                val id = event.text("event_id")
                val content = StringBuilder()
                var offset = 0
                do {
                    val part = payload(id, offset)
                    content.append(part.text("content"))
                    check(content.length <= TRACE_PAYLOAD_LIMIT) { "诊断内容超过导出上限" }
                    val next = part["next_offset"]!!.jsonPrimitive.int
                    check(next > offset) { "诊断内容已清理，导出未完成" }
                    offset = next
                } while (offset < part["total_characters"]!!.jsonPrimitive.int)
                entry("payloads/$id.json", TraceRedaction.clean(Json.parseToJsonElement(content.toString())).toString())
            }
            after = page.last()["sequence"]!!.jsonPrimitive.int
        }
        check(stillExists()) { "记录在导出期间已清理，请重新选择" }
        entry("manifest.json", buildJsonObject {
            put("schema", TRACE_SCHEMA); put("application_version", applicationVersion)
            put("trace", TraceRedaction.clean(trace)); put("capture_status", trace.text("capture_status"))
            put("contains_creative_content", trace.text("mode") == "full"); put("files", JsonArray(files))
        }.toString())
    }
}
