package com.siming.mobile.data.agent

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class MobileOutlineWriterContractTest {
    @Test
    fun `writer uses the reviewed count without inheriting cataloging scene expansion`() {
        val asset = generateSequence(File(System.getProperty("user.dir"))) { it.parentFile }
            .map { File(it, "mobile/android/app/src/main/assets/pc_workspace_prompt_contract.json") }
            .first(File::isFile)
        val contract = Json.parseToJsonElement(asset.readText()).jsonObject
        val template = JsonArray(listOf(contract.getValue("writer_output_tools").jsonObject.getValue("outline")))
        val original = template.toString()
        for (count in listOf(1, 6, 11)) {
            val tool = bindOutlineOutputNodeCount(template, count).single().jsonObject
            val nodes = tool.getValue("function").jsonObject.getValue("parameters").jsonObject
                .getValue("properties").jsonObject.getValue("nodes").jsonObject
            assertEquals(count, nodes.getValue("minItems").jsonPrimitive.int)
            assertEquals(count, nodes.getValue("maxItems").jsonPrimitive.int)
        }
        assertEquals(original, template.toString())
        assertFailsWith<IllegalArgumentException> { bindOutlineOutputNodeCount(template, 0) }
        assertFailsWith<IllegalArgumentException> { bindOutlineOutputNodeCount(template, 13) }
        val system = contract.getValue("writer_systems").jsonObject.getValue("outline").jsonPrimitive.content
        assertTrue(system.contains("精确总数"))
        assertTrue(system.contains("章 summary"))
        assertFalse(system.contains("必须额外输出"))
    }
}
