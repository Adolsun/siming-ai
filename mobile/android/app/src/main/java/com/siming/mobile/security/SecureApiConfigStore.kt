package com.siming.mobile.security

import android.annotation.SuppressLint
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.siming.mobile.data.network.DirectApiConfig
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/** Keeps a standalone provider credential out of Room, logs, and Android backups. */
class SecureApiConfigStore(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences(
        "siming_direct_api_credentials",
        Context.MODE_PRIVATE,
    )
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val json = Json { ignoreUnknownKeys = true }

    @Synchronized
    @SuppressLint("ApplySharedPref")
    fun save(config: DirectApiConfig) {
        val encoded = json.encodeToString(config)
        check(preferences.edit().putString(CONFIG_KEY, encrypt(encoded)).commit()) {
            "无法安全保存 API 配置"
        }
    }

    @Synchronized
    fun read(): DirectApiConfig? = runCatching {
        val encrypted = preferences.getString(CONFIG_KEY, null) ?: return null
        json.decodeFromString<DirectApiConfig>(decrypt(encrypted))
    }.getOrNull()

    @Synchronized
    @SuppressLint("ApplySharedPref")
    fun clear() {
        check(preferences.edit().clear().commit()) { "无法清除 API 配置" }
    }

    private fun secretKey(): SecretKey {
        val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        if (existing != null) return existing
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                )
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setRandomizedEncryptionRequired(true)
                    .setUserAuthenticationRequired(false)
                    .build(),
            )
        }.generateKey()
    }

    private fun encrypt(value: String): String {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val ciphertext = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(cipher.iv + ciphertext, Base64.NO_WRAP)
    }

    private fun decrypt(value: String): String {
        val bytes = Base64.decode(value, Base64.NO_WRAP)
        require(bytes.size > IV_BYTES)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            secretKey(),
            GCMParameterSpec(128, bytes.copyOfRange(0, IV_BYTES)),
        )
        return String(cipher.doFinal(bytes.copyOfRange(IV_BYTES, bytes.size)), Charsets.UTF_8)
    }

    companion object {
        private const val CONFIG_KEY = "encrypted_config"
        private const val KEY_ALIAS = "siming_mobile_direct_api_encryption"
        private const val IV_BYTES = 12
    }
}
