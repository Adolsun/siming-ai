package com.siming.mobile.data

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import org.junit.Test
import kotlin.test.assertEquals

class ProjectPackageChapterStateTest {
    @Test
    fun chapterCatalogingStateMatchesTheSharedPcFixture() {
        val fixture = requireNotNull(javaClass.classLoader?.getResourceAsStream("project-package-v1-chapter-state.json"))
            .bufferedReader(Charsets.UTF_8).use { Json.parseToJsonElement(it.readText()) as JsonObject }
        for (value in fixture["cases"] as JsonArray) {
            val case = value as JsonObject
            val state = ProjectPackageChapterCatalogingState(
                (case["snapshots"] as JsonArray).map { it as JsonObject },
                (case["summaries"] as JsonArray).map { it as JsonObject },
            )
            assertEquals((case["required"] as JsonPrimitive).boolean, state.required(case["chapter"] as JsonObject),
                (case["name"] as JsonPrimitive).content)
        }
    }
}
