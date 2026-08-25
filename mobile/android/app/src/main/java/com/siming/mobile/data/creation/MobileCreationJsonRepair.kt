package com.siming.mobile.data.creation

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

internal data class MobileJsonObjectParse(
    val value: JsonObject,
    val method: String,
)

/**
 * Kotlin projection of the deterministic JSON recovery used by the PC creation runtime.
 * It is deliberately conservative: repair syntax only, never invent stage semantics.
 */
internal object MobileCreationJsonRepair {
    private val json = Json { ignoreUnknownKeys = true }
    private val thinkingBlock = Regex(
        "<(?:think|thinking|analysis)>[\\s\\S]*?</(?:think|thinking|analysis)>",
        RegexOption.IGNORE_CASE,
    )

    fun parseObjectDetailed(raw: String): MobileJsonObjectParse? {
        val cleaned = stripJsonFences(raw)
        parseLargestObject(cleaned)?.let { return MobileJsonObjectParse(it, "direct") }

        val escaped = escapeJsonStringValues(cleaned)
        if (escaped != cleaned) {
            parseLargestObject(escaped)?.let { return MobileJsonObjectParse(it, "deterministic_json") }
        }

        val normalized = removeTrailingCommas(normalizeJsonPunctuation(cleaned))
        parseLargestObject(normalized)?.let { return MobileJsonObjectParse(it, "deterministic_json") }

        val start = normalized.indexOf('{')
        if (start >= 0) {
            repairTruncatedJson(normalized.substring(start))?.let { repaired ->
                parseLargestObject(repaired)?.let {
                    return MobileJsonObjectParse(it, "deterministic_json")
                }
            }
        }
        return null
    }

    private fun stripJsonFences(raw: String): String {
        var value = raw.trim().trimStart('\uFEFF')
        value = thinkingBlock.replace(value, "").trim()
        repeat(2) {
            value = when {
                value.startsWith("```json", ignoreCase = true) -> value.drop(7)
                value.startsWith("```") -> value.drop(3)
                else -> value
            }.trim()
            if (value.endsWith("```")) value = value.dropLast(3).trim()
        }
        return value
    }

    private fun parseLargestObject(text: String): JsonObject? {
        if (text.isBlank()) return null
        val candidates = buildList {
            add(text.trim())
            addAll(balancedObjects(text))
        }.distinct()
        return candidates.mapNotNull { candidate ->
            runCatching { json.parseToJsonElement(candidate) as? JsonObject }
                .getOrNull()
                ?.let { candidate.length to it }
        }.maxByOrNull { it.first }?.second
    }

    private fun balancedObjects(text: String): List<String> {
        val result = mutableListOf<String>()
        var start = -1
        var depth = 0
        var inString = false
        var escape = false
        text.forEachIndexed { index, char ->
            if (inString) {
                when {
                    escape -> escape = false
                    char == '\\' -> escape = true
                    char == '"' -> inString = false
                }
                return@forEachIndexed
            }
            when (char) {
                '"' -> inString = true
                '{' -> {
                    if (depth == 0) start = index
                    depth += 1
                }
                '}' -> if (depth > 0) {
                    depth -= 1
                    if (depth == 0 && start >= 0) {
                        result += text.substring(start, index + 1)
                        start = -1
                    }
                }
            }
        }
        return result
    }

    private fun normalizeJsonPunctuation(text: String): String = text
        .replace('“', '"')
        .replace('”', '"')
        .replace('‘', '\'')
        .replace('’', '\'')

    private fun removeTrailingCommas(text: String): String =
        Regex(",(\\s*[}\\]])").replace(text, "$1")

    private fun escapeJsonStringValues(text: String): String {
        val result = StringBuilder(text.length + 16)
        var inString = false
        var escapeNext = false
        var index = 0
        while (index < text.length) {
            val char = text[index]
            if (!inString) {
                result.append(char)
                if (char == '"') inString = true
                index += 1
                continue
            }
            when {
                escapeNext -> {
                    result.append(char)
                    escapeNext = false
                }
                char == '\\' -> {
                    result.append(char)
                    escapeNext = true
                }
                char == '"' -> {
                    var ahead = index + 1
                    while (ahead < text.length && text[ahead].isWhitespace()) ahead += 1
                    if (ahead >= text.length || text[ahead] in charArrayOf(',', '}', ':', ']')) {
                        inString = false
                        result.append(char)
                    } else {
                        result.append("\\\"")
                    }
                }
                else -> result.append(char)
            }
            index += 1
        }
        return result.toString()
    }

    private fun repairTruncatedJson(candidate: String): String? {
        var repaired = candidate.trim()
        if (!repaired.startsWith('{')) return null
        val stack = mutableListOf<Char>()
        var inString = false
        var escape = false
        var changed = false
        repaired.forEach { char ->
            if (inString) {
                when {
                    escape -> escape = false
                    char == '\\' -> escape = true
                    char == '"' -> inString = false
                }
            } else {
                when (char) {
                    '"' -> inString = true
                    '{' -> stack += '}'
                    '[' -> stack += ']'
                    '}', ']' -> if (stack.lastOrNull() == char) stack.removeAt(stack.lastIndex)
                }
            }
        }
        if (inString) {
            repaired += '"'
            changed = true
        }
        repeat(3) {
            val next = Regex(",?\\s*\"[^\"\\\\]*(?:\\\\.[^\"\\\\]*)*\"\\s*:\\s*$")
                .replace(repaired, "")
                .trimEnd()
            if (next == repaired) return@repeat
            repaired = next
            changed = true
        }
        val trimmed = Regex("[:,]\\s*$").replace(repaired, "").trimEnd()
        if (trimmed != repaired) changed = true
        repaired = trimmed
        if (stack.isNotEmpty()) {
            repaired += stack.asReversed().joinToString("")
            changed = true
        }
        if (!changed) return null
        return removeTrailingCommas(repaired)
    }
}
