package com.siming.mobile.data.observability

import java.security.MessageDigest
import kotlinx.serialization.json.*

internal object TraceRedaction {
    // Decode/redact at most one bounded payload at a time; never block a model call.
    val processing = java.util.concurrent.Semaphore(1)
    private val keys = setOf("apikey", "authorization", "proxyauthorization", "cookie", "setcookie", "password",
        "secret", "secretkey", "accesstoken", "refreshtoken", "idtoken", "clientsecret", "credential", "credentials", "token")

    /** Inspect existing nodes before copying; conservative escaped UTF-8 allocation bound. */
    fun withinBudget(value: JsonElement, limit: Int = TRACE_PAYLOAD_LIMIT): Boolean {
        var remaining = limit.toLong()
        fun visit(node: JsonElement, depth: Int): Boolean {
            if (depth > 64 || remaining < 0) return false
            remaining -= 2
            return when (node) {
                is JsonObject -> node.all { (key, item) -> remaining -= key.length * 6L + 4; visit(item, depth + 1) }
                is JsonArray -> node.all { visit(it, depth + 1) }
                is JsonPrimitive -> { remaining -= node.content.length * 6L + 1; remaining >= 0 }
            }
        }
        return visit(value, 0) && remaining >= 0
    }
    fun clean(value: JsonElement, secrets: List<String> = emptyList()): JsonElement = when (value) {
        is JsonObject -> JsonObject(value.mapValues { (key, item) ->
            if (key.lowercase().filter { it in 'a'..'z' } in keys) JsonPrimitive("[REDACTED]") else clean(item, secrets)
        })
        is JsonArray -> JsonArray(value.map { clean(it, secrets) })
        is JsonPrimitive -> if (value.isString) {
            JsonPrimitive(secrets.filter(String::isNotEmpty).fold(value.content) { text, secret -> text.replace(secret, "[REDACTED]") })
        } else value
    }
    fun hash(value: String) = MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") { "%02x".format(it) }

    fun decode(raw: ByteArray, media: String): JsonElement = if (media == "text/event-stream") {
        JsonArray(raw.toString(Charsets.UTF_8).split(Regex("\\r?\\n\\r?\\n")).mapNotNull { block ->
            val data = block.lines().filter { it.startsWith("data:") }.joinToString("\n") { it.drop(5).trimStart() }
            when { data.isEmpty() -> null; data == "[DONE]" -> JsonPrimitive(data); else -> Json.parseToJsonElement(data) }
        })
    } else Json.parseToJsonElement(raw.toString(Charsets.UTF_8))
}
