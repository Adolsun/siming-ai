package com.siming.mobile.security

import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.time.Instant
import java.util.Base64
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingSecurityTest {
    @Test
    fun verifiesSignedQrAndAcceptsPrivateHttpGateway() {
        val pair = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()
        val rawPublicKey = pair.public.encoded.takeLast(32).toByteArray()
        val fingerprint = MessageDigest.getInstance("SHA-256")
            .digest(rawPublicKey)
            .joinToString("") { "%02x".format(it) }
        val unsigned = JsonObject(
            mapOf(
                "type" to JsonPrimitive("siming-gateway-pairing"),
                "protocol_version" to JsonPrimitive(1),
                "gateway_url" to JsonPrimitive("http://192.168.1.20:8765"),
                "gateway_name" to JsonPrimitive("司命 Gateway"),
                "gateway_public_key" to JsonPrimitive(Base64.getUrlEncoder().withoutPadding().encodeToString(rawPublicKey)),
                "gateway_encryption_public_key" to JsonPrimitive(
                    Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 7 }),
                ),
                "gateway_fingerprint" to JsonPrimitive(fingerprint),
                "pairing_id" to JsonPrimitive("00000000-0000-0000-0000-000000000001"),
                "pairing_secret" to JsonPrimitive("smp_test-secret-with-enough-entropy"),
                "expires_at" to JsonPrimitive("2030-01-01T00:00:00Z"),
            ),
        )
        val signer = Signature.getInstance("Ed25519")
        signer.initSign(pair.private)
        signer.update(PairingSecurity.canonicalBytes(unsigned))
        val payload = JsonObject(
            unsigned + ("signature" to JsonPrimitive(
                Base64.getUrlEncoder().withoutPadding().encodeToString(signer.sign()),
            )),
        )

        val verified = PairingSecurity.verify(
            Json.encodeToString(payload),
            Instant.parse("2029-01-01T00:00:00Z"),
        )

        assertEquals("http://192.168.1.20:8765", verified.gatewayUrl)
        assertEquals(fingerprint, verified.gatewayFingerprint)
        assertEquals(
            Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 7 }),
            verified.gatewayEncryptionPublicKey,
        )
    }

    @Test
    fun rejectsCleartextPublicGateway() {
        assertThrows(IllegalArgumentException::class.java) {
            PairingSecurity.validateGatewayUrl("http://203.0.113.10:8765")
        }
        assertEquals(
            "https://siming.example.ts.net",
            PairingSecurity.validateGatewayUrl("https://siming.example.ts.net/"),
        )
    }
}
