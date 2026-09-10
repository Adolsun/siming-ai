package com.siming.mobile.data.agent

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class MobileProjectReadContractTest {
    @Test
    fun `long settings are explicitly paged and reconstruct without splitting unicode`() {
        val text = "𠮷".repeat(5201)
        val source = buildJsonObject {
            put("id", "project-1")
            put("title", "作品")
            put("description", text)
            put("creation", buildJsonObject { put("private", "excluded") })
        }
        val overview = mobileProjectInfoPage(source, buildJsonObject {})
        assertFalse(overview["data"]!!.jsonObject.containsKey("creation"))
        assertEquals(100, overview["data"]!!.jsonObject["description"]!!.jsonPrimitive.content.codePointCount(0, 200))
        var args = overview["field_ranges"]!!.jsonObject["description"]!!.jsonObject["read_arguments"]!!.jsonObject
        val content = StringBuilder()
        var pages = 0
        do {
            val page = mobileProjectInfoPage(source, args)
            assertTrue(MobileNativeToolBudgetContract.actualResultFits("get_project_info", page, args))
            content.append(page["data"]!!.jsonObject["description"]!!.jsonPrimitive.content)
            pages++
            val range = page["field_ranges"]!!.jsonObject["description"]!!.jsonObject
            assertEquals("5201", range["total_chars"].toString())
            args = range["next_arguments"] as? JsonObject ?: break
            assertEquals(JsonPrimitive("project-1"), args["project_id"])
        } while (true)
        assertEquals(text, content.toString())
        assertEquals(3, pages)
    }

    @Test
    fun `outline windows use code point offsets on every platform`() {
        val page = mobileTextRange("A𠮷中文", 1, 2)
        assertEquals("𠮷中", page.text)
        assertEquals("4", page.metadata["total_chars"].toString())
        assertEquals("3", page.metadata["next_offset_chars"].toString())
        assertEquals("", mobileTextRange("A𠮷", 20, 2).text)
    }

    @Test
    fun `outline text budget charges larger windows and keeps structural overhead`() {
        val small = MobileNativeToolBudgetContract.declaredResultJsonBytes("search_outline", buildJsonObject {
            put("limit", 1); put("summary_chars", 200)
        })
        val large = MobileNativeToolBudgetContract.declaredResultJsonBytes("search_outline", buildJsonObject {
            put("limit", 1); put("summary_chars", 1000)
        })
        assertEquals(24 * 800, large - small)
        assertTrue(large > 24 * 1000)
    }

    @Test
    fun `long local text is read completely without a PC or splitting supplementary characters`() {
        for (length in listOf(10_000, 20_000, 50_000)) {
            for (character in listOf("文", "𠮷", "\u0001")) {
                val source = character.repeat(length)
                val restored = StringBuilder()
                var offset = 0
                do {
                    val page = mobileTextRange(source, offset, 4000)
                    restored.append(page.text)
                    assertEquals(length.toString(), page.metadata["total_chars"].toString())
                    val next = page.metadata["next_offset_chars"].toString().toIntOrNull() ?: break
                    assertTrue(next > offset)
                    offset = next
                } while (true)
                assertEquals(source, restored.toString())
            }
        }
    }
}
