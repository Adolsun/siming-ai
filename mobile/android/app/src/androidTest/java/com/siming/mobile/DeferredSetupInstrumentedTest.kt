package com.siming.mobile

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/** Run on a fresh installation with no API, Gateway or project data. */
@RunWith(AndroidJUnit4::class)
class DeferredSetupInstrumentedTest {
    @get:Rule
    val composeRule = createEmptyComposeRule()

    @Test
    fun deferredSetupOpensLocalLibraryAndSurvivesANewActivity() {
        ActivityScenario.launch(MainActivity::class.java).use {
            composeRule.onNodeWithText("稍后配置").performScrollTo().performClick()
            composeRule.onNodeWithText("当前离线，仍可继续写作").assertIsDisplayed()
            composeRule.onNodeWithText("导入司命项目包").performScrollTo().assertIsDisplayed()
            composeRule.onNodeWithText("稍后配置").assertDoesNotExist()
        }

        // A new Activity and ViewModel must read the saved preference even
        // while the library is still empty and no credentials exist.
        ActivityScenario.launch(MainActivity::class.java).use {
            composeRule.onNodeWithText("当前离线，仍可继续写作").assertIsDisplayed()
            composeRule.onNodeWithText("稍后配置").assertDoesNotExist()
            composeRule.onNodeWithText("设置").performClick()
            composeRule.onNodeWithText("配置云端 API").performScrollTo().performClick()
            composeRule.onNodeWithText("配置手机直连 API").assertIsDisplayed()
        }
    }
}
