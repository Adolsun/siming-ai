package com.siming.mobile.data.network

import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest

class DirectApiClientTest {
    @Test
    fun `model discovery falls back to v1 and keeps authorization private`() = withServer(
        object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                assertEquals("Bearer secret-test-key", request.getHeader("Authorization"))
                return if (request.path == "/v1/models") {
                    jsonResponse("""{"data":[{"id":"model-b"},{"id":"model-a"}]}""")
                } else {
                    MockResponse().setResponseCode(405)
                }
            }
        },
    ) { server ->
        val models = runBlocking {
            testClient().discoverModels(server.url("/").toString(), "secret-test-key")
        }
        assertEquals(listOf("model-a", "model-b"), models)
    }

    @Test
    fun `responses API extracts output text`() = withServer(
        pathDispatcher(
            "/responses" to jsonResponse(
                """{"output":[{"type":"message","content":[{"type":"output_text","text":"独立模式可用"}]}]}""",
            ),
        ),
    ) { server ->
        val result = runBlocking {
            testClient().complete(
                config(server, DirectApiConfig.PROTOCOL_RESPONSES),
                "system",
                "user",
            )
        }
        assertEquals("独立模式可用", result)
    }

    @Test
    fun `responses API falls back to v1 after method mismatch at root`() = withServer(
        pathDispatcher(
            "/responses" to MockResponse().setResponseCode(405),
            "/v1/responses" to jsonResponse("""{"output_text":"v1 路径可用"}"""),
        ),
    ) { server ->
        val result = runBlocking {
            testClient().complete(
                config(server, DirectApiConfig.PROTOCOL_RESPONSES),
                "system",
                "user",
            )
        }
        assertEquals("v1 路径可用", result)
    }

    @Test
    fun `automatic protocol falls back to chat completions`() = withServer(
        object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse = when (request.path) {
                "/chat/completions" -> jsonResponse(
                    """{"choices":[{"message":{"role":"assistant","content":"Chat 可用"}}]}""",
                )
                else -> MockResponse().setResponseCode(404)
            }
        },
    ) { server ->
        val result = runBlocking {
            testClient().complete(config(server, DirectApiConfig.PROTOCOL_AUTO), "system", "user")
        }
        assertEquals("Chat 可用", result)
    }

    @Test
    fun `transient upstream errors retry before returning content`() {
        val attempts = AtomicInteger()
        withServer(
            object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    if (request.path != "/responses") return MockResponse().setResponseCode(404)
                    return if (attempts.incrementAndGet() < 3) {
                        jsonResponse(
                            """{"error":{"message":"Upstream request failed","type":"upstream_error"}}""",
                            502,
                        )
                    } else {
                        jsonResponse("""{"output_text":"重试成功"}""")
                    }
                }
            },
        ) { server ->
            val result = runBlocking {
                DirectApiClient(
                    allowCleartextForTests = true,
                    retryDelaysMillis = listOf(0, 0),
                ).complete(config(server, DirectApiConfig.PROTOCOL_RESPONSES), "system", "user")
            }
            assertEquals("重试成功", result)
            assertEquals(3, attempts.get())
        }
    }

    @Test
    fun `production client rejects cleartext credential transport`() {
        val error = assertFailsWith<IllegalArgumentException> {
            runBlocking {
                DirectApiClient(retryDelaysMillis = emptyList()).discoverModels(
                    "http://api.example.test/v1",
                    "secret",
                )
            }
        }
        assertTrue(error.message.orEmpty().contains("HTTPS"))
    }

    private fun testClient() = DirectApiClient(
        allowCleartextForTests = true,
        retryDelaysMillis = emptyList(),
    )

    private fun config(server: MockWebServer, protocol: String) = DirectApiConfig(
        displayName = "test",
        baseUrl = server.url("/").toString(),
        apiKey = "secret-test-key",
        model = "model-a",
        protocol = protocol,
    )

    private fun pathDispatcher(vararg routes: Pair<String, MockResponse>) = object : Dispatcher() {
        private val responses = routes.toMap()
        override fun dispatch(request: RecordedRequest): MockResponse =
            responses[request.path] ?: MockResponse().setResponseCode(404)
    }

    private fun jsonResponse(body: String, status: Int = 200) = MockResponse()
        .setResponseCode(status)
        .setHeader("Content-Type", "application/json")
        .setBody(body)

    private fun withServer(dispatcher: Dispatcher, block: (MockWebServer) -> Unit) {
        MockWebServer().use { server ->
            server.dispatcher = dispatcher
            server.start()
            block(server)
        }
    }
}
