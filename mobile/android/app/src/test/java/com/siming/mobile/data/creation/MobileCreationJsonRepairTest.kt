package com.siming.mobile.data.creation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MobileCreationJsonRepairTest {
    @Test
    fun parsesFencedJsonWithTrailingComma() {
        val parsed = MobileCreationJsonRepair.parseObjectDetailed(
            """```json
                {"action":"ok","items":[1,2,],}
                ```""".trimIndent(),
        )

        requireNotNull(parsed)
        assertEquals("deterministic_json", parsed.method)
        assertEquals("ok", parsed.value["action"].toString().trim('"'))
    }

    @Test
    fun stripsThinkingBeforeReadingFinalObject() {
        val parsed = MobileCreationJsonRepair.parseObjectDetailed(
            "<think>{not json}</think>\n{\"ready\":true}",
        )

        requireNotNull(parsed)
        assertTrue(parsed.value["ready"].toString() == "true")
    }

    @Test
    fun normalizesSmartQuotes() {
        val parsed = MobileCreationJsonRepair.parseObjectDetailed("{“name”:“林舟”,“goal”:“找人”}")

        requireNotNull(parsed)
        assertEquals("林舟", parsed.value["name"].toString().trim('"'))
    }

    @Test
    fun repairsTruncatedObjectConservatively() {
        val parsed = MobileCreationJsonRepair.parseObjectDetailed(
            "{\"name\":\"林舟\",\"profile\":{\"goal\":\"找姐姐\"}",
        )

        requireNotNull(parsed)
        assertEquals("deterministic_json", parsed.method)
        assertTrue(parsed.value.containsKey("profile"))
    }

    @Test
    fun doesNotInventSemanticsForBareSchemaNotation() {
        val parsed = MobileCreationJsonRepair.parseObjectDetailed(
            "{\"protagonist_seed\":{name, identity, goal, lack}}",
        )

        assertNull(parsed)
    }
}
