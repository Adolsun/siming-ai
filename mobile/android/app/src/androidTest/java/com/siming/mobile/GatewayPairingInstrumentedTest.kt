package com.siming.mobile

import android.util.Base64
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextReplacement
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class GatewayPairingInstrumentedTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<MainActivity>()

    @Test
    fun pairsThroughTheRenderedManualFlowWhenPayloadIsProvided() {
        val encoded = InstrumentationRegistry.getArguments()
            .getString("pairingPayloadBase64")
            .orEmpty()
        assumeTrue("pairingPayloadBase64 was not supplied", encoded.isNotBlank())
        val payload = String(Base64.decode(encoded, Base64.DEFAULT), Charsets.UTF_8)

        composeRule.onNodeWithText("相机不可用？手动粘贴配对内容").performClick()
        composeRule.onNode(hasSetTextAction()).performTextReplacement(payload)
        composeRule.onNodeWithText("验证签名").performClick()
        composeRule.waitUntil(timeoutMillis = 15_000) {
            composeRule.onAllNodesWithText("Gateway 签名已验证")
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("Gateway 签名已验证").assertIsDisplayed()
        composeRule.onNodeWithText("提交配对申请").performClick()

        composeRule.waitUntil(timeoutMillis = 120_000) {
            composeRule.onAllNodesWithText("自己的 Gateway · 跨设备创作")
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNodeWithText("自己的 Gateway · 跨设备创作").assertIsDisplayed()
    }
}
