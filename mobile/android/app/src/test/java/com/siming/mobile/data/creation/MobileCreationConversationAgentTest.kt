package com.siming.mobile.data.creation

import com.siming.mobile.data.agent.MobileAssistantConversationStore
import com.siming.mobile.data.agent.MobileConversationContextErrorCode
import com.siming.mobile.data.agent.MobileConversationContextException
import com.siming.mobile.data.agent.MobileToolTransactionState
import com.siming.mobile.data.network.DirectApiClient
import com.siming.mobile.data.network.DirectApiConfig
import java.io.File
import java.nio.file.Files
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest

class MobileCreationConversationAgentTest {
    @Test
    fun `standalone generation returns reference diagnostics without calling the generator`() {
        val cases = listOf(
            Triple("context_entity_ids", JsonArray(listOf(JsonPrimitive("world_style:worldbuilding:99"))), "creation_context_entity_unavailable"),
            Triple("context_artifacts", JsonArray(listOf(JsonPrimitive("unknown_artifact"))), "creation_context_artifact_invalid"),
            Triple("entity_type", JsonPrimitive("characters"), "creation_entity_type_invalid"),
        )
        cases.forEach { (field, value, reason) ->
            val requests = AtomicInteger()
            var modelReceipt = ""
            fun tool(name: String, args: JsonObject): MockResponse = chatStreamResponse(buildJsonObject {
                put("choices", JsonArray(listOf(buildJsonObject { put("message", buildJsonObject {
                    put("role", "assistant")
                    put("tool_calls", JsonArray(listOf(buildJsonObject {
                        put("id", "call-$name")
                        put("type", "function")
                        put("function", buildJsonObject { put("name", name); put("arguments", args.toString()) })
                    })))
                }) })))
            }.toString())
            withServer(object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse = when (requests.getAndIncrement()) {
                    0 -> tool("set_tool_categories", buildJsonObject {
                        put("enabled_categories", JsonArray(listOf(JsonPrimitive("creation_flow"))))
                    })
                    1 -> tool("generate_creation_artifact", buildJsonObject {
                        put("artifact", "characters"); put("expected_revision", 1); put(field, value)
                    })
                    else -> {
                        check(requests.get() == 3)
                        val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                        modelReceipt = body.getValue("messages").jsonArray.map { it.jsonObject }
                            .last { it.string("role") == "tool" }.string("content")
                        chatStreamResponse("""{"choices":[{"message":{"role":"assistant","content":"引用无效，本轮未写入。"}}]}""")
                    }
                }
            }) { server ->
                val initial = session()
                val outcome = runBlocking { agent().run(initial, "生成主角档案", config(server)) }
                assertEquals(3, requests.get())
                assertTrue(modelReceipt.contains(reason), modelReceipt)
                assertTrue(modelReceipt.contains("$.$field"), modelReceipt)
                assertEquals(1, outcome.session.getValue("revision").jsonPrimitive.content.toInt())
                assertEquals(initial.getValue("draft"), outcome.session.getValue("draft"))
                val receipt = outcome.toolResults.map { it.jsonObject }.last()
                assertEquals(reason, receipt.getValue("data").jsonObject.string("reason"))
            }
        }
    }

    @Test
    fun `standalone entity refinement replaces only the selected second entity`() {
        exerciseEntityRefinement(valid = true)
    }

    @Test
    fun `standalone entity refinement cannot use the old baseline as a generated result`() {
        exerciseEntityRefinement(valid = false)
    }

    @Test
    fun `standalone generation passes explicitly selected context entities to the provider`() {
        exerciseEntityRefinement(valid = true, includeContext = true)
    }

    private fun exerciseEntityRefinement(valid: Boolean, includeContext: Boolean = false) {
        val calls = AtomicInteger()
        val first = buildJsonObject {
            put("title", "不应变动的条目")
            put("dimension", "culture")
            put("content", "保持这条原始内容")
        }
        val second = buildJsonObject {
            put("title", "待修订条目")
            put("dimension", "culture")
            put("content", "原始第二条")
        }
        val replacement = JsonObject(second.toMutableMap().apply { put("content", JsonPrimitive("经过核验的新内容")) })
        val world = buildJsonObject {
            put("writing_style", "克制")
            put("world_tone", "现实")
            put("story_structure", "线性")
            put("pacing", "稳健")
            put("style_rules", "保持限知")
            put("forbidden_patterns", "不使用巧合")
            put("worldbuilding", JsonArray(listOf(first, second)))
        }
        val initial = session()
        val source = JsonObject(initial.toMutableMap().apply {
            put("draft", JsonObject(initial["draft"]!!.jsonObject.toMutableMap().apply {
                put("stages", buildJsonObject {
                    put("world_style", buildJsonObject { put("status", "generated"); put("data", world) })
                })
            }))
        })
        fun response(message: JsonObject, streaming: Boolean): MockResponse {
            val body = buildJsonObject {
                put("choices", JsonArray(listOf(buildJsonObject { put("message", message) })))
                put("usage", buildJsonObject { put("prompt_tokens", 100); put("completion_tokens", 50) })
            }.toString()
            return if (streaming) chatStreamResponse(body) else
                MockResponse().setHeader("Content-Type", "application/json").setBody(body)
        }
        fun toolMessage(name: String, arguments: JsonObject) = buildJsonObject {
            put("role", "assistant")
            put("tool_calls", JsonArray(listOf(buildJsonObject {
                put("id", "call-" + name)
                put("type", "function")
                put("function", buildJsonObject { put("name", name); put("arguments", arguments.toString()) })
            })))
        }
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                val index = calls.getAndIncrement()
                val message = when (index) {
                    0 -> toolMessage("set_tool_categories", buildJsonObject {
                        put("enabled_categories", JsonArray(listOf(JsonPrimitive("creation_flow"))))
                    })
                    1 -> toolMessage("refine_creation_artifact", buildJsonObject {
                        put("artifact", "world_style")
                        put("entity_id", "world_style:worldbuilding:1")
                        put("instruction", "修订所选实体")
                        put("expected_revision", 1)
                        if (includeContext) put("context_entity_ids", JsonArray(listOf(JsonPrimitive("world_style:worldbuilding:0"))))
                    })
                    2, 3 -> if (index == 2 || !valid) {
                        if (index == 2) {
                            val prompt = body.getValue("messages").jsonArray.last().jsonObject.string("content")
                            assertTrue(prompt.contains("world_style:worldbuilding:1"))
                            assertEquals(includeContext, prompt.contains("保持这条原始内容"))
                            if (includeContext) assertTrue(prompt.contains("retrieved_entities"))
                        }
                        buildJsonObject {
                            put("role", "assistant")
                            put("content", buildJsonObject {
                                put("data", if (valid) buildJsonObject {
                                    put("worldbuilding", JsonArray(listOf(replacement)))
                                } else buildJsonObject {
                                    put("world_style", buildJsonObject { put("worldbuilding", JsonArray(listOf(replacement))) })
                                })
                            }.toString())
                        }
                    } else buildJsonObject { put("role", "assistant"); put("content", "已完成本轮") }
                    else -> buildJsonObject { put("role", "assistant"); put("content", "模型格式无效，原资料未修改") }
                }
                return response(message, body["stream"]?.jsonPrimitive?.content == "true")
            }
        }) { server ->
            val outcome = runBlocking { agent().run(source, "修订所选实体", config(server)) }
            val rows = outcome.session["draft"]!!.jsonObject["stages"]!!.jsonObject["world_style"]!!
                .jsonObject["data"]!!.jsonObject["worldbuilding"]!!.jsonArray
            assertEquals(first, rows[0])
            assertEquals(if (valid) replacement else second, rows[1])
            assertEquals(if (valid) 4 else 5, calls.get())
            val receipt = outcome.toolResults.map { it.jsonObject }.first { it.string("tool") == "refine_creation_artifact" }
            assertEquals(if (valid) "ok" else "error", receipt.string("status"))
            assertEquals(if (valid) 2 else 1, outcome.session["revision"]!!.jsonPrimitive.content.toInt())
        }
    }

    @Test
    fun `standalone agent selects categories before reading and preserves complete rounds`() {
        val requests = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                assertTrue(body.getValue("stream").jsonPrimitive.content.toBoolean())
                return when (requests.getAndIncrement()) {
                    0 -> {
                        assertEquals("required", body.getValue("tool_choice").jsonPrimitive.content)
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}],"usage":{"prompt_tokens":88}}""",
                        )
                    }
                    1 -> {
                        assertEquals("auto", body.getValue("tool_choice").jsonPrimitive.content)
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-read","type":"function","function":{"name":"get_creation_snapshot","arguments":"{}"}}]}}],"usage":{"prompt_tokens":100}}""",
                        )
                    }
                    else -> {
                        assertEquals("auto", body.getValue("tool_choice").jsonPrimitive.content)
                        val messages = body.getValue("messages").jsonArray.map { it.jsonObject }
                        assertTrue(messages.any { (it["tool_calls"] as? JsonArray)?.isNotEmpty() == true })
                        val toolMessage = messages.first {
                            it.string("role") == "tool" && it.string("tool_call_id") == "call-read"
                        }
                        val toolResult = Json.parseToJsonElement(toolMessage.string("content")).jsonObject
                        val visibleDraft = toolResult.getValue("data").jsonObject.getValue("draft").jsonObject
                        assertFalse("agent_turns" in visibleDraft)
                        assertFalse("agent_conversation_id" in visibleDraft)
                        assertFalse("execution_route" in visibleDraft)
                        assertFalse("execution_host" in visibleDraft)
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":"已读取当前立项资料，没有修改数据。"}}],"usage":{"prompt_tokens":144}}""",
                        )
                    }
                }
            }
        }) { server ->
            val result = runBlocking { agent().run(
                source = session(),
                message = "先看看当前资料",
                config = config(server),
            ) }

            assertEquals(3, requests.get())
            assertEquals("completed", result.status)
            assertTrue(result.replayable)
            assertEquals("已读取当前立项资料，没有修改数据。", result.reply)
            assertEquals(
                listOf("user", "assistant", "tool", "assistant", "tool", "assistant"),
                result.modelMessages.map { (it as JsonObject).string("role") },
            )
            assertEquals(88, result.promptMetrics[0].jsonObject.getValue("prompt_tokens").jsonPrimitive.content.toInt())
            assertEquals(100, result.promptMetrics[1].jsonObject.getValue("prompt_tokens").jsonPrimitive.content.toInt())
            assertEquals(144, result.promptMetrics[2].jsonObject.getValue("prompt_tokens").jsonPrimitive.content.toInt())
        }
    }

    @Test
    fun `standalone agent can select no business tools and reply without writing`() {
        val requests = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                assertEquals(
                    listOf("set_tool_categories"),
                    body.getValue("tools").jsonArray.map {
                        it.jsonObject.getValue("function").jsonObject.string("name")
                    },
                )
                return when (requests.getAndIncrement()) {
                    0 -> {
                        assertEquals("required", body.getValue("tool_choice").jsonPrimitive.content)
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-empty-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[]}"}}]}}]}""",
                        )
                    }
                    else -> {
                        assertEquals(2, requests.get())
                        assertEquals("auto", body.getValue("tool_choice").jsonPrimitive.content)
                        val receipt = body.getValue("messages").jsonArray.map { it.jsonObject }.first {
                            it.string("role") == "tool" && it.string("tool_call_id") == "call-empty-categories"
                        }
                        assertEquals("ok", Json.parseToJsonElement(receipt.string("content")).jsonObject.string("status"))
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":"你好！你想讨论怎样的故事？"}}]}""",
                        )
                    }
                }
            }
        }) { server ->
            val source = session()
            val result = runBlocking { agent().run(source, "你好？", config(server)) }
            assertEquals(2, requests.get())
            assertEquals("completed", result.status)
            assertEquals("你好！你想讨论怎样的故事？", result.reply)
            assertEquals(source["revision"], result.session["revision"])
            assertEquals(listOf("set_tool_categories"), result.toolResults.map { it.jsonObject.string("tool") })
            assertEquals("ok", result.toolResults.single().jsonObject.string("status"))
        }
    }

    @Test
    fun `standalone agent continues past the old six step limit`() {
        val requests = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                return when (val step = requests.getAndIncrement()) {
                    0 -> chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
                    )
                    in 1..6 -> {
                        assertTrue(body.getValue("tools").jsonArray.isNotEmpty())
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-read-$step","type":"function","function":{"name":"get_creation_snapshot","arguments":"{}"}}]}}]}""",
                        )
                    }
                    else -> chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":"已在超过旧上限后完成检查。"}}]}""",
                    )
                }
            }
        }) { server ->
            val result = runBlocking { agent().run(
                source = session(),
                message = "连续检查多轮",
                config = config(server),
            ) }

            assertEquals(8, requests.get())
            assertEquals("completed", result.status)
            assertEquals("已在超过旧上限后完成检查。", result.reply)
        }
    }

    @Test
    fun `deepseek standalone conversation preserves thinking and omits unsupported tool choice`() {
        val requests = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                assertFalse("tool_choice" in body)
                assertFalse("thinking" in body)
                return if (requests.getAndIncrement() == 0) {
                    chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
                    )
                } else {
                    chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":"思考模式与工具调用可以共同工作。"}}]}""",
                    )
                }
            }
        }) { server ->
            val result = runBlocking {
                agent().run(
                    source = session(),
                    message = "先检查当前资料",
                    config = config(server).copy(
                        displayName = "DeepSeek",
                        model = "deepseek-v4-pro",
                    ),
                )
            }

            assertEquals(2, requests.get())
            assertEquals("思考模式与工具调用可以共同工作。", result.reply)
        }
    }

    @Test
    fun `standalone agent rejects text before selecting tool categories`() {
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                assertEquals("required", body.getValue("tool_choice").jsonPrimitive.content)
                assertTrue(body.getValue("stream").jsonPrimitive.content.toBoolean())
                return chatStreamResponse(
                    """{"choices":[{"message":{"role":"assistant","content":"我已经读取并保存了设定。"}}]}""",
                )
            }
        }) { server ->
            val error = assertFailsWith<IllegalStateException> {
                runBlocking { agent().run(
                    source = session(),
                    message = "加入一个新设定",
                    config = config(server),
                ) }
            }
            assertTrue(error.message.orEmpty().contains("set_tool_categories"))
        }
    }

    @Test
    fun `standalone agent persists only one successful write per user message`() {
        val requests = AtomicInteger()
        val persisted = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                assertTrue(body.getValue("stream").jsonPrimitive.content.toBoolean())
                return when (requests.getAndIncrement()) {
                    0 -> chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
                    )
                    1 -> chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-write-one","type":"function","function":{"name":"patch_creation_session","arguments":"{\"changes\":{\"genre\":\"玄幻\"}}"}},{"id":"call-write-two","type":"function","function":{"name":"patch_creation_session","arguments":"{\"changes\":{\"target_chapters\":1000}}"}}]}}]}""",
                    )
                    else -> {
                        assertTrue(body.getValue("tools").jsonArray.isEmpty())
                        assertFalse("tool_choice" in body)
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":"本轮只记录了题材。下一步想补充什么？"}}]}""",
                        )
                    }
                }
            }
        }) { server ->
            val client = DirectApiClient(allowCleartextForTests = true, retryDelaysMillis = emptyList())
            val contract = contractJson()
            val store = MobileAssistantConversationStore(Files.createTempDirectory("creation-agent-test").toFile())
            val standalone = MobileCreationConversationAgent(
                contract = PcCreationAgentContract(contract),
                stageAgent = MobileCreationAgent(contract, client),
                directApi = client,
                conversationStore = store,
                persistSession = { persisted.incrementAndGet() },
                finalizeSession = { source -> source to "project-1" },
            )
            val result = runBlocking { AgentHarness(standalone, store).run(
                source = session(),
                message = "继续",
                config = config(server),
            ) }

            assertEquals(3, requests.get())
            assertEquals(1, persisted.get())
            assertEquals(2, result.session.getValue("revision").jsonPrimitive.content.toInt())
            val businessResults = result.toolResults.map { it.jsonObject }
                .filter { it.string("tool") == "patch_creation_session" }
            assertEquals(listOf("ok", "denied"), businessResults.map { it.string("status") })
            assertEquals("本轮只记录了题材。下一步想补充什么？", result.reply)
        }
    }

    @Test
    fun `oversized declared creation results reject the whole batch before any handler`() {
        val requests = AtomicInteger()
        val persisted = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                return when (requests.getAndIncrement()) {
                    0 -> chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
                    )
                    1 -> {
                        val calls = (1..60).joinToString(",") { index ->
                            """{"id":"call-write-$index","type":"function","function":{"name":"patch_creation_session","arguments":"{\"changes\":{\"genre\":\"类型$index\"}}"}}"""
                        }
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[$calls]}}]}""",
                        )
                    }
                    else -> {
                        val messages = body.getValue("messages").jsonArray.map { it.jsonObject }
                        assertEquals(
                            60,
                            messages.count { it.string("role") == "tool" && it.string("tool_call_id").startsWith("call-write-") },
                        )
                        chatStreamResponse(
                            """{"choices":[{"message":{"role":"assistant","content":"批次过大，未修改立项资料。"}}]}""",
                        )
                    }
                }
            }
        }) { server ->
            val client = DirectApiClient(allowCleartextForTests = true, retryDelaysMillis = emptyList())
            val contract = contractJson()
            val store = MobileAssistantConversationStore(Files.createTempDirectory("creation-agent-test").toFile())
            val standalone = MobileCreationConversationAgent(
                contract = PcCreationAgentContract(contract),
                stageAgent = MobileCreationAgent(contract, client),
                directApi = client,
                conversationStore = store,
                persistSession = { persisted.incrementAndGet() },
                finalizeSession = { source -> source to "project-1" },
            )

            val result = runBlocking {
                AgentHarness(standalone, store).run(
                    source = session(),
                    message = "一次改很多字段",
                    config = config(server),
                )
            }

            assertEquals(3, requests.get())
            assertEquals(0, persisted.get())
            assertEquals(1, result.session.getValue("revision").jsonPrimitive.content.toInt())
            assertEquals(60, result.toolResults.count {
                it.jsonObject.string("status") == "error" &&
                    it.jsonObject["data"]?.jsonObject?.string("reason") == "tool_result_batch_over_capacity"
            })
        }
    }

    @Test
    fun `oversized creation rejection remains delivered without a ledger after restart`() {
        val oversizedContent = "x".repeat(250_000)
        val persisted = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = chatStreamResponse(
                """{"choices":[{"message":{"role":"assistant","content":"$oversizedContent","tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
            )
        }) { server ->
            val client = DirectApiClient(allowCleartextForTests = true, retryDelaysMillis = emptyList())
            val contract = contractJson()
            val directory = Files.createTempDirectory("creation-oversized-restart-test").toFile()
            val store = MobileAssistantConversationStore(directory)
            val standalone = MobileCreationConversationAgent(
                contract = PcCreationAgentContract(contract),
                stageAgent = MobileCreationAgent(contract, client),
                directApi = client,
                conversationStore = store,
                persistSession = { persisted.incrementAndGet() },
                finalizeSession = { source -> source to "project-1" },
            )

            val error = assertFailsWith<MobileConversationContextException> {
                runBlocking {
                    AgentHarness(standalone, store).run(
                        source = session(),
                        message = "选择立项能力",
                        config = config(server),
                    )
                }
            }
            assertEquals(MobileConversationContextErrorCode.TOOL_TRANSACTION_OVER_CAPACITY, error.code)
            assertEquals(0, persisted.get())

            val restarted = MobileAssistantConversationStore(directory)
            val snapshot = runBlocking {
                checkNotNull(restarted.snapshot("creation-session-1", "creation-session-1"))
            }
            val runtime = snapshot.toolRuntimeStates.single()
            assertEquals(MobileToolTransactionState.DELIVERED, runtime.transactions.single().state)
            assertEquals(runtime.transactions, runtime.activeTransactions)
            assertTrue(runtime.executionLedger.isEmpty())
            assertTrue(runtime.transactions.single().results.all { result ->
                result.resultRef == null && result.persistedStepId == null
            })
        }
    }

    @Test
    fun `duplicate creation call ids reject the whole batch before any handler`() {
        val requests = AtomicInteger()
        val persisted = AtomicInteger()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                if (requests.getAndIncrement() == 0) {
                    chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call-categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
                    )
                } else {
                    chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"duplicate","type":"function","function":{"name":"patch_creation_session","arguments":"{\"changes\":{\"genre\":\"玄幻\"}}"}},{"id":"duplicate","type":"function","function":{"name":"patch_creation_session","arguments":"{\"changes\":{\"genre\":\"科幻\"}}"}}]}}]}""",
                    )
                }
        }) { server ->
            val client = DirectApiClient(allowCleartextForTests = true, retryDelaysMillis = emptyList())
            val contract = contractJson()
            val store = MobileAssistantConversationStore(Files.createTempDirectory("creation-agent-test").toFile())
            val standalone = MobileCreationConversationAgent(
                contract = PcCreationAgentContract(contract),
                stageAgent = MobileCreationAgent(contract, client),
                directApi = client,
                conversationStore = store,
                persistSession = { persisted.incrementAndGet() },
                finalizeSession = { source -> source to "project-1" },
            )

            val error = assertFailsWith<MobileConversationContextException> {
                runBlocking {
                    AgentHarness(standalone, store).run(
                        source = session(),
                        message = "重复调用不得执行",
                        config = config(server),
                    )
                }
            }

            assertEquals(MobileConversationContextErrorCode.PROTOCOL_INVALID, error.code)
            assertEquals(0, persisted.get())
            assertEquals(2, requests.get())
        }
    }

    @Test
    fun `standalone summary rejects DSML before displaying any provider delta`() {
        listOf(
            DSML,
            "已经保存。\n$DSML",
            DSML.replace("｜｜", "｜"),
            DSML.replace("｜", "|"),
            DSML.replace("<", "&lt;"),
            "<｜｜DSML  ",
        ).forEach { invalid -> exerciseSummary(invalid, persistentFailure = false) }
    }

    @Test
    fun `standalone summary stops after one correction and retains committed data`() {
        exerciseSummary(DSML, persistentFailure = true)
    }

    @Test
    fun `standalone summary never executes an unexpected native call`() {
        exerciseSummary("", persistentFailure = false, nativeCall = true)
    }

    @Test
    fun `standalone empty summary is corrected without replaying a write`() {
        exerciseSummary("", persistentFailure = false)
    }

    @Test
    fun `standalone summary request failure preserves the successful write`() {
        exerciseSummary("", persistentFailure = false, transportFailure = true)
    }

    @Test
    fun `standalone failed write limit enters summary without another tool step`() {
        val requests = AtomicInteger()
        val expectedReply = "修改未保存，请检查当前资料版本。"
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                return when (requests.getAndIncrement()) {
                    0 -> chatStreamResponse(
                        """{"choices":[{"message":{"role":"assistant","tool_calls":[{"id":"categories","type":"function","function":{"name":"set_tool_categories","arguments":"{\"enabled_categories\":[\"creation_data\"]}"}}]}}]}""",
                    )
                    1 -> {
                        val calls = (1..4).joinToString(",") { index ->
                            """{"id":"write-$index","type":"function","function":{"name":"patch_creation_session","arguments":"{\"expected_revision\":999,\"changes\":{\"genre\":\"玄幻\"}}"}}"""
                        }
                        chatStreamResponse("""{"choices":[{"message":{"role":"assistant","tool_calls":[$calls]}}]}""")
                    }
                    else -> {
                        check(requests.get() == 3)
                        assertTrue(body.getValue("tools").jsonArray.isEmpty())
                        assertFalse("tool_choice" in body)
                        assertTrue(body.getValue("messages").jsonArray.first().jsonObject.string("content").contains("工具已关闭"))
                        chatStreamResponse("""{"choices":[{"message":{"role":"assistant","content":"$expectedReply"}}]}""")
                    }
                }
            }
        }) { server ->
            val outcome = runBlocking { agent().run(session(), "把题材设为玄幻", config(server)) }
            assertEquals(3, requests.get())
            assertEquals(1, outcome.session.getValue("revision").jsonPrimitive.content.toInt())
            assertEquals(expectedReply, outcome.reply)
            assertEquals(listOf("error", "error", "error", "denied"), outcome.toolResults.map { it.jsonObject }
                .filter { it.string("tool") == "patch_creation_session" }.map { it.string("status") })
            assertEquals("summary", outcome.promptMetrics.last().jsonObject.string("phase"))
        }
    }

    private fun exerciseSummary(
        invalid: String,
        persistentFailure: Boolean,
        nativeCall: Boolean = false,
        transportFailure: Boolean = false,
    ) {
        val requests = AtomicInteger()
        val persisted = AtomicInteger()
        val progress = mutableListOf<CreationAgentProgressEvent>()
        val expectedReply = "题材已更新为玄幻。主角有什么目标？"
        fun response(content: String, call: String? = null): MockResponse = chatStreamResponse(
            buildJsonObject {
                put("choices", JsonArray(listOf(buildJsonObject {
                    put("message", buildJsonObject {
                        put("role", "assistant")
                        put("content", content)
                        if (call != null) put("tool_calls", JsonArray(listOf(Json.parseToJsonElement(call))))
                    })
                })))
            }.toString(),
        )
        fun call(id: String, name: String, arguments: String): String = buildJsonObject {
            put("id", id)
            put("type", "function")
            put("function", buildJsonObject { put("name", name); put("arguments", arguments) })
        }.toString()
        withServer(object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                assertEquals("/chat/completions", request.path)
                val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
                assertEquals("deepseek-flash", body.string("model"))
                return when (val step = requests.getAndIncrement()) {
                    0 -> response("", call("categories", "set_tool_categories", """{"enabled_categories":["creation_data"]}"""))
                    1 -> response("", call("read", "get_creation_snapshot", "{}"))
                    2 -> response("", call("write", "patch_creation_session", """{"changes":{"genre":"玄幻"}}"""))
                    else -> {
                        check(step in 3..4) { "Summary correction must be bounded" }
                        assertTrue(body.getValue("tools").jsonArray.isEmpty())
                        assertFalse("tool_choice" in body)
                        val messages = body.getValue("messages").jsonArray.map { it.jsonObject }
                        val system = messages.first().string("content")
                        assertTrue(system.contains("[SERVER_RUNTIME_INSTRUCTION]"))
                        assertTrue(system.contains("工具已关闭"))
                        assertEquals("把题材设为玄幻", messages.last { it.string("role") == "user" }.string("content"))
                        assertTrue(messages.any { it.string("role") == "tool" && it.string("tool_call_id") == "write" })
                        assertFalse(progress.any { it.type == "reply_delta" })
                        if (step == 4) assertTrue(system.contains("上一条总结未通过输出协议校验"))
                        if (transportFailure) {
                            MockResponse().setResponseCode(401).setBody("""{"error":{"message":"summary request unavailable"}}""")
                        } else if (step == 3 && nativeCall) {
                            response("", call("unoffered-write", "patch_creation_session", """{"changes":{"genre":"科幻"}}"""))
                        } else response(if (step == 3 || persistentFailure) invalid else expectedReply)
                    }
                }
            }
        }) { server ->
            val client = DirectApiClient(allowCleartextForTests = true, retryDelaysMillis = emptyList())
            val contract = contractJson()
            val store = MobileAssistantConversationStore(Files.createTempDirectory("creation-summary-test").toFile())
            val standalone = MobileCreationConversationAgent(
                contract = PcCreationAgentContract(contract),
                stageAgent = MobileCreationAgent(contract, client),
                directApi = client,
                conversationStore = store,
                persistSession = { persisted.incrementAndGet() },
                finalizeSession = { source -> source to "project-1" },
            )
            val outcome = runBlocking { AgentHarness(standalone, store).run(
                source = session(), message = "把题材设为玄幻",
                config = config(server).copy(model = "deepseek-flash"),
                onProgress = { progress += it },
            ) }
            assertEquals(if (transportFailure) 4 else 5, requests.get())
            assertEquals(1, persisted.get())
            assertEquals(2, outcome.session.getValue("revision").jsonPrimitive.content.toInt())
            assertEquals(1, outcome.toolResults.count { it.jsonObject.string("tool") == "patch_creation_session" })
            if (!transportFailure) {
                assertEquals(listOf("summary", "summary"), outcome.promptMetrics.takeLast(2).map { it.jsonObject.string("phase") })
            }
            assertEquals(if (persistentFailure || transportFailure) "receipt_only" else "model", outcome.replyStatus)
            assertEquals(if (persistentFailure) 2 else 1, outcome.replyDiagnostics.size)
            if (persistentFailure || transportFailure) {
                assertTrue(outcome.reply.contains("已保存"))
                assertTrue(outcome.reply.contains("模型未能生成有效总结"))
            } else assertEquals(expectedReply, outcome.reply)
            assertFalse(outcome.reply.contains("DSML"))
            assertFalse(outcome.modelMessages.toString().contains("DSML"))
            assertEquals(outcome.reply, progress.filter { it.type == "reply_delta" }.joinToString("") { it.data.string("delta") })
            val record = CreationAgentTurnRecords.complete(
                pending = CreationAgentTurnRecords.pending("把题材设为玄幻"),
                reply = outcome.reply,
                modelMessages = outcome.modelMessages,
                toolResults = outcome.toolResults,
                replayable = outcome.replayable,
                executionRoute = "mobile",
                replyStatus = outcome.replyStatus,
                replyDiagnostics = outcome.replyDiagnostics,
            )
            assertEquals(outcome.replyStatus, record.string("reply_status"))
            assertEquals(outcome.replyDiagnostics, record["reply_diagnostics"])
        }
    }

    private data class AgentHarness(
        val agent: MobileCreationConversationAgent,
        val store: MobileAssistantConversationStore,
    )

    private fun agent(): AgentHarness {
        val client = DirectApiClient(allowCleartextForTests = true, retryDelaysMillis = emptyList())
        val contract = contractJson()
        val store = MobileAssistantConversationStore(Files.createTempDirectory("creation-agent-test").toFile())
        return AgentHarness(
            agent = MobileCreationConversationAgent(
                contract = PcCreationAgentContract(contract),
                stageAgent = MobileCreationAgent(contract, client),
                directApi = client,
                conversationStore = store,
                persistSession = {},
                finalizeSession = { source -> source to "project-1" },
            ),
            store = store,
        )
    }

    private suspend fun AgentHarness.run(
        source: JsonObject,
        message: String,
        config: DirectApiConfig,
        onProgress: suspend (CreationAgentProgressEvent) -> Unit = {},
    ): MobileCreationConversationResult {
        val storageId = "creation-session-1"
        val conversationId = storageId
        store.ensureConversationArchive(
            projectId = storageId,
            conversationId = conversationId,
            conversationKind = "creation",
            creationSessionId = source.string("id"),
            title = "测试立项",
            archivedTurns = CreationAgentTurnRecords.archivedTurns(source),
        )
        val turnContext = store.beginTurn(
            projectId = storageId,
            conversationId = conversationId,
            prompt = message,
            conversationKind = "creation",
            creationSessionId = source.string("id"),
        )
        val conversation = checkNotNull(store.snapshot(storageId, conversationId))
        return agent.run(
            source = source,
            message = message,
            storageId = storageId,
            conversation = conversation,
            turnContext = turnContext,
            config = config,
            onProgress = onProgress,
        )
    }

    private fun config(server: MockWebServer) = DirectApiConfig(
        displayName = "test",
        baseUrl = server.url("/").toString(),
        apiKey = "secret",
        model = "test-model",
        protocol = DirectApiConfig.PROTOCOL_CHAT_COMPLETIONS,
        contextWindowTokens = 200_000,
        maxOutputTokens = 6_000,
        safetyMarginTokens = 4_096,
    )

    private fun session() = buildJsonObject {
        put("id", "session-1")
        put("revision", 1)
        put("display_title", "测试立项")
        put("draft", buildJsonObject {
            put("form", buildJsonObject {})
            put("stages", buildJsonObject {})
            put("agent_turns", JsonArray(listOf(buildJsonObject {
                put("schema", CreationAgentTurnRecords.SCHEMA)
                put("user_content", "不应递归进入工具快照")
            })))
            put("agent_conversation_id", "conversation-1")
            put("execution_route", "mobile")
            put("execution_host", "device")
        })
    }

    private fun contractJson(): String {
        val candidates = listOf(
            File("src/main/assets/pc_workspace_prompt_contract.json"),
            File("app/src/main/assets/pc_workspace_prompt_contract.json"),
        )
        return candidates.first(File::isFile).readText(Charsets.UTF_8)
    }

    private companion object {
        const val DSML = "<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name=\"get_creation_entity\">" +
            "<｜｜DSML｜｜ parameter name=\"entity_id\" string=\"true\">entity-1" +
            "</｜｜DSML｜｜ parameter></｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>"
    }

    private fun chatStreamResponse(body: String): MockResponse {
        val root = Json.parseToJsonElement(body).jsonObject
        val message = root.getValue("choices").jsonArray.first().jsonObject.getValue("message").jsonObject
        val finishReason = if ((message["tool_calls"] as? JsonArray).orEmpty().isNotEmpty()) {
            "tool_calls"
        } else {
            "stop"
        }
        val event = buildJsonObject {
            put("choices", JsonArray(listOf(buildJsonObject {
                put("delta", message)
                put("finish_reason", finishReason)
            })))
            root["usage"]?.let { put("usage", it) }
        }
        return MockResponse()
            .setResponseCode(200)
            .setHeader("Content-Type", "text/event-stream")
            .setBody("data: $event\n\ndata: [DONE]\n\n")
    }

    private fun withServer(dispatcher: Dispatcher, block: (MockWebServer) -> Unit) {
        MockWebServer().use { server ->
            server.dispatcher = dispatcher
            server.start()
            block(server)
        }
    }

    private fun JsonObject.string(name: String): String =
        (get(name) as? JsonPrimitive)?.contentOrNull.orEmpty()
}
