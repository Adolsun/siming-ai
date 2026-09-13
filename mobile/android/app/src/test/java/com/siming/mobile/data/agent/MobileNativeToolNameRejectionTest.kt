package com.siming.mobile.data.agent

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

class MobileNativeToolNameRejectionTest {
    private fun JsonObject.string(key: String): String = (this[key] as? JsonPrimitive)?.content.orEmpty()

    private fun fixture(): JsonObject = requireNotNull(
        javaClass.classLoader?.getResourceAsStream("native-tool-name-rejection.json"),
    ).bufferedReader(Charsets.UTF_8).use { Json.parseToJsonElement(it.readText()) as JsonObject }

    private fun budget(available: Int = 250_000) = buildMobileRequestBudget(
        binding = MobileGenerationModelBinding(
            taskType = "assistant", provider = "test", modelName = "fixture", normalizedModel = "test:fixture",
            protocol = "chat_completions", contextWindowTokens = available + 5_512, maxOutputTokens = 4_000,
            tokenCounterId = MobileUtf8ByteTokenCounter.counterId,
            capacityAssurance = MobileUtf8ByteTokenCounter.assurance,
            promptContractHash = "prompt", toolSchemaHash = "tools", configFingerprint = "config",
        ),
        counter = MobileUtf8ByteTokenCounter,
        components = MobileRequestTokenComponents(systemPromptTokens = 1_000),
        safetyMarginTokens = 512,
    )

    private fun rejection(count: Int = 1, capacity: Int = 250_000): MobileNativeToolNameRejection {
        val fixture = fixture()
        val assistant = fixture.getValue("assistant") as JsonObject
        return assertNotNull(rejectMobileUnopenedToolBatch(
            assistantPayload = assistant,
            orderedToolNames = (assistant.getValue("tool_calls") as JsonArray).map {
                ((it as JsonObject).getValue("function") as JsonObject).string("name")
            },
            offeredToolNames = (fixture.getValue("offered_tools") as JsonArray).map { (it as JsonPrimitive).content }.toSet(),
            requestBudget = budget(capacity), rejectionCount = count,
        ))
    }

    @Test
    fun `captured PC batch gets the same complete denial on standalone mobile`() {
        val fixture = fixture()
        assertEquals(fixture.getValue("max_rejections").toString().toInt(), MAX_NATIVE_TOOL_NAME_REJECTIONS)
        val rejection = rejection()
        assertTrue(rejection.recoveryFits)
        assertEquals(2, rejection.results.size)
        rejection.results.forEach { receipt ->
            assertEquals("error", receipt.string("status"))
            assertEquals(fixture.getValue("denial_data"), receipt["data"])
        }
    }

    @Test
    fun `third rejection stops and insufficient space stops without trimming provider state`() {
        assertTrue(rejection(count = 2).recoveryFits)
        for (rejected in listOf(rejection(count = 3), rejection(capacity = 100))) {
            assertFalse(rejected.recoveryFits)
            assertEquals(MobileConversationContextErrorCode.PROTOCOL_INVALID, rejected.failure.code)
            rejected.results.forEach {
                assertEquals(JsonPrimitive(false), (it.getValue("data") as JsonObject)["retryable"])
            }
        }
        assertTrue(rejection(count = 3).failure.message.orEmpty().contains("两次自动修正"))
    }

    @Test
    fun `malformed IDs or arguments cannot become recoverable name failures`() {
        val original = fixture().getValue("assistant") as JsonObject
        val calls = original.getValue("tool_calls") as JsonArray
        for (mutation in listOf("missing_id", "duplicate_id", "invalid_json", "array_arguments")) {
            val altered = (calls[1] as JsonObject).toMutableMap()
            if (mutation.endsWith("id")) {
                altered["id"] = JsonPrimitive(if (mutation == "missing_id") "" else (calls[0] as JsonObject).string("id"))
            } else {
                val function = (altered.getValue("function") as JsonObject).toMutableMap()
                function["arguments"] = JsonPrimitive(if (mutation == "invalid_json") "{bad" else "[]")
                altered["function"] = JsonObject(function)
            }
            assertFailsWith<MobileConversationContextException> {
                rejectMobileUnopenedToolBatch(
                    assistantPayload = JsonObject(original + ("tool_calls" to JsonArray(listOf(calls[0], JsonObject(altered))))),
                    orderedToolNames = listOf("list_chapters", "list_outline_tree"),
                    offeredToolNames = setOf("list_chapters", "search_outline_tree"),
                    requestBudget = budget(), rejectionCount = 1,
                )
            }
        }
    }

    @Test
    fun `corrected names proceed and closed registered names remain unavailable`() {
        assertNull(rejectMobileUnopenedToolBatch(
            assistantPayload = JsonObject(emptyMap()), orderedToolNames = listOf("search_outline_tree"),
            offeredToolNames = setOf("search_outline_tree"), requestBudget = budget(), rejectionCount = 2,
        )) // Normal calls proceed to the existing strict admission validator.
        val fixture = fixture()
        val assistant = Json.parseToJsonElement(mobileCanonicalJson(fixture.getValue("assistant"))
            .replace("list_outline_tree", "list_cataloging_jobs")) as JsonObject
        val denied = assertNotNull(rejectMobileUnopenedToolBatch(
            assistantPayload = assistant, orderedToolNames = listOf("list_chapters", "list_cataloging_jobs"),
            offeredToolNames = setOf("list_chapters", "search_outline_tree"), requestBudget = budget(), rejectionCount = 1,
        ))
        assertEquals(JsonArray(listOf(JsonPrimitive("list_cataloging_jobs"))),
            (denied.results[0].getValue("data") as JsonObject)["unavailable_tools"])
    }

    @Test
    fun `mobile denial survives restart with exact call IDs and provider continuation`() = runBlocking {
        val directory = Files.createTempDirectory("siming-tool-name-test").toFile()
        try {
            val store = MobileAssistantConversationStore(directory)
            val turn = store.beginTurn("project", null, "继续写下一章")
            val original = fixture().getValue("assistant") as JsonObject
            val calls = original.getValue("tool_calls") as JsonArray
            val rejection = rejection(count = 3)
            val transaction = MobileToolTransaction(
                transactionId = "denied", assistantMessageId = "assistant-denied", assistantContent = "",
                assistantReasoningContent = original.string("reasoning_content"),
                assistantProviderState = (original.getValue("provider_state") as JsonArray).map { it as JsonObject },
                state = MobileToolTransactionState.DELIVERED,
                calls = calls.map {
                    val call = it as JsonObject
                    val function = call.getValue("function") as JsonObject
                    MobileToolCallRecord(call.string("id"), function.string("name"), function.string("arguments"))
                },
                results = calls.zip(rejection.results).map { (call, result) ->
                    MobileToolResultRecord((call as JsonObject).string("id"), mobileCanonicalJson(result))
                },
            )
            val caught = assertFailsWith<MobileConversationContextException> {
                persistRejectedMobileNativeToolBatch(
                    conversationStore = store, projectId = "project", turnContext = turn,
                    transaction = transaction, recoveryFits = rejection.recoveryFits,
                    terminalError = rejection.failure, afterPersist = {},
                )
            }
            assertEquals(MobileConversationContextErrorCode.PROTOCOL_INVALID, caught.code)
            val restarted = MobileAssistantConversationStore(directory)
            val snapshot = assertNotNull(restarted.snapshot("project", turn.conversationId))
            val runtime = assertNotNull(snapshot.toolRuntimeState(turn.turnId))
            assertTrue(runtime.executionLedger.isEmpty())
            val retained = runtime.activeTransactions.single()
            assertEquals(MobileToolTransactionState.DELIVERED, retained.state)
            assertEquals(original, retained.nativeMessages().first())
            assertEquals(calls.map { (it as JsonObject).string("id") }, retained.results.map { it.toolCallId })
        } finally {
            directory.deleteRecursively()
        }
    }
}
