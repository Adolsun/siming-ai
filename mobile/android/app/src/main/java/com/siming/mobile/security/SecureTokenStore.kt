package com.siming.mobile.security

import android.annotation.SuppressLint
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.spec.ECGenParameterSpec
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

data class StoredTokenPair(
    val accessToken: String,
    val accessExpiresAt: String,
    val refreshToken: String,
    val refreshExpiresAt: String,
)

class SecureTokenStore(context: Context) {
    private val preferences = context.applicationContext.getSharedPreferences(
        "siming_secure_credentials",
        Context.MODE_PRIVATE,
    )
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    @Synchronized
    @SuppressLint("ApplySharedPref")
    fun save(pair: StoredTokenPair) {
        // A refresh-token rotation is a single security transaction. Commit
        // all four encrypted values atomically before the caller proceeds.
        check(
            preferences.edit()
                .putString("access_token", encrypt(pair.accessToken))
                .putString("access_expires_at", encrypt(pair.accessExpiresAt))
                .putString("refresh_token", encrypt(pair.refreshToken))
                .putString("refresh_expires_at", encrypt(pair.refreshExpiresAt))
                .commit(),
        ) { "无法持久化 Gateway 凭据" }
    }

    @Synchronized
    fun read(): StoredTokenPair? {
        val access = getDecrypted("access_token") ?: return null
        val accessExpiry = getDecrypted("access_expires_at") ?: return null
        val refresh = getDecrypted("refresh_token") ?: return null
        val refreshExpiry = getDecrypted("refresh_expires_at") ?: return null
        return StoredTokenPair(access, accessExpiry, refresh, refreshExpiry)
    }

    @Synchronized
    @SuppressLint("ApplySharedPref")
    fun clear() {
        check(preferences.edit().clear().commit()) { "无法清除 Gateway 凭据" }
    }

    fun devicePublicKey(): String {
        val alias = "siming_mobile_device_identity"
        if (!keyStore.containsAlias(alias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(
                    KeyGenParameterSpec.Builder(
                        alias,
                        KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
                    )
                        .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                        .setDigests(KeyProperties.DIGEST_SHA256)
                        .setUserAuthenticationRequired(false)
                        .build(),
                )
            }.generateKeyPair()
        }
        val certificate = keyStore.getCertificate(alias)
        return Base64.encodeToString(certificate.publicKey.encoded, Base64.NO_WRAP)
    }

    private fun secretKey(): SecretKey {
        val alias = "siming_mobile_token_encryption"
        val existing = keyStore.getKey(alias, null) as? SecretKey
        if (existing != null) return existing
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(
                    alias,
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

    private fun getDecrypted(name: String): String? = runCatching {
        val encoded = preferences.getString(name, null) ?: return null
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        require(bytes.size > 12)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.DECRYPT_MODE,
            secretKey(),
            GCMParameterSpec(128, bytes.copyOfRange(0, 12)),
        )
        String(cipher.doFinal(bytes.copyOfRange(12, bytes.size)), Charsets.UTF_8)
    }.getOrNull()
}
