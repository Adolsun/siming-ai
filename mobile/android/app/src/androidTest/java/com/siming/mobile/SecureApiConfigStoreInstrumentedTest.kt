package com.siming.mobile

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.siming.mobile.data.network.DirectApiConfig
import com.siming.mobile.security.SecureApiConfigStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureApiConfigStoreInstrumentedTest {
    @Test
    fun directApiCredentialRoundTripsWithoutPlaintextStorage() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val store = SecureApiConfigStore(context)
        val config = DirectApiConfig(
            displayName = "测试 API",
            baseUrl = "https://api.example.test/v1",
            apiKey = "secret-key-that-must-stay-encrypted",
            model = "model-private-name",
            protocol = DirectApiConfig.PROTOCOL_AUTO,
        )

        try {
            store.clear()
            store.save(config)
            assertEquals(config, store.read())

            val raw = context.getSharedPreferences(
                "siming_direct_api_credentials",
                android.content.Context.MODE_PRIVATE,
            ).all.values.joinToString()
            assertFalse(raw.contains(config.apiKey))
            assertFalse(raw.contains(config.model))
            assertFalse(raw.contains(config.baseUrl))
        } finally {
            store.clear()
        }
    }
}
