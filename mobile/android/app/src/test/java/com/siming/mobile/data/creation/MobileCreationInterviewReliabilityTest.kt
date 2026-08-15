package com.siming.mobile.data.creation

import com.siming.mobile.data.network.DirectApiHttpException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class MobileCreationInterviewReliabilityTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun canonicalAskMoreDecisionStaysFreeForm() {
        val result = MobileCreationInterviewReliability.parseDecision(
            """{"action":"ask_more","reason":"关键分岔","question":{"question":"她最怕失去什么？","purpose":"决定情感代价","options":["自由"],"type":"single_select"}}""",
            JsonArray(emptyList()),
        )

        assertEquals("ask_more", result.string("action"))
        val question = result["question"] as JsonObject
        assertEquals("她最怕失去什么？", question.string("question"))
        assertEquals("text", question.string("type"))
        assertTrue((question["options"] as JsonArray).isEmpty())
    }

    @Test
    fun stringQuestionIsNormalizedInsteadOfRejected() {
        val result = MobileCreationInterviewReliability.parseDecision(
            """{"action":"ask_more","question":"你现在最想写下来的画面是什么？"}""",
            JsonArray(emptyList()),
        )

        val question = result["question"] as JsonObject
        assertEquals("你现在最想写下来的画面是什么？", question.string("question"))
        assertEquals("text", question.string("type"))
    }

    @Test
    fun questionsArrayWithStringIsNormalized() {
        val result = MobileCreationInterviewReliability.parseDecision(
            """{"action":"ask_more","questions":["主角第一次主动反抗会付出什么代价？"]}""",
            JsonArray(emptyList()),
        )

        assertEquals(
            "主角第一次主动反抗会付出什么代价？",
            (result["question"] as JsonObject).string("question"),
        )
    }

    @Test
    fun malformedAskMoreCanBeRetried() {
        try {
            MobileCreationInterviewReliability.parseDecision(
                """{"action":"ask_more","reason":"还需要一个分岔"}""",
                JsonArray(emptyList()),
            )
            fail("expected invalid response")
        } catch (error: MobileInterviewDecisionException) {
            assertEquals("invalid_response", error.failureClass)
            assertTrue(error.repairable)
        }
    }

    @Test
    fun repeatedQuestionIsRejectedWithoutRepairingIntoAnotherQuestion() {
        val history = JsonArray(listOf(
            json.parseToJsonElement("""{"question":"主角是谁？","answer":"林舟"}"""),
        ))
        try {
            MobileCreationInterviewReliability.parseDecision(
                """{"action":"ask_more","question":{"question":"主角是谁？"}}""",
                history,
            )
            fail("expected repeated question rejection")
        } catch (error: MobileInterviewDecisionException) {
            assertEquals("invalid_response", error.failureClass)
            assertFalse(error.repairable)
        }
    }

    @Test
    fun quotaFailureUsesPcStyleRecoveryAdvice() {
        val failure = MobileCreationInterviewReliability.failure(
            DirectApiHttpException(429, "API 请求过于频繁或额度不足，请稍后重试"),
        )

        assertEquals("quota_or_rate_limit", failure.failureClass)
        assertTrue(failure.message.contains("回答已保留").not())
        assertTrue(failure.nextAction.contains("切换有额度的模型"))
    }

    @Test
    fun retryPromptKeepsOriginalContextAndStrictShape() {
        val prompt = MobileCreationInterviewReliability.retryUserPrompt(
            "原始上下文：林舟要找姐姐",
            "{\"action\":\"ask_more\"}",
            "没有问题",
        )

        assertTrue(prompt.contains("林舟要找姐姐"))
        assertTrue(prompt.contains("question"))
        assertTrue(prompt.contains("generate"))
    }

    private fun JsonObject.string(name: String): String =
        (get(name) as? JsonPrimitive)?.contentOrNull.orEmpty()
}
