package com.siming.mobile.security

import com.google.crypto.tink.subtle.Ed25519Verify
import java.net.URI
import java.security.MessageDigest
import java.time.Instant
import java.util.Base64
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive

data class VerifiedPairing(
    val gatewayUrl: String,
    val gatewayName: String,
    val gatewayPublicKey: String,
    val gatewayFingerprint: String,
    val pairingId: String,
    val pairingSecret: String,
    val expiresAt: String,
    val raw: String,
)

object PairingSecurity {
    private val json = Json { ignoreUnknownKeys = false }

    fun verify(raw: String, now: Instant = Instant.now()): VerifiedPairing {
        require(raw.toByteArray().size <= 16 * 1024) { "二维码内容过大" }
        val payload = json.parseToJsonElement(raw) as? JsonObject
            ?: error("不是有效的司命配对二维码")
        require(payload["type"]?.jsonPrimitive?.content == "siming-gateway-pairing") {
            "不是司命 Gateway 配对二维码"
        }
        require(payload["protocol_version"]?.jsonPrimitive?.content?.toIntOrNull() == 1) {
            "同步协议版本不兼容，请更新司命手机版"
        }
        val signature = payload.required("signature")
        val publicKeyText = payload.required("gateway_public_key")
        val publicKey = decodeUrlBase64(publicKeyText)
        require(publicKey.size == 32) { "Gateway 公钥格式无效" }
        val unsigned = JsonObject(payload.filterKeys { it != "signature" })
        Ed25519Verify(publicKey).verify(
            decodeUrlBase64(signature),
            canonicalBytes(unsigned),
        )
        val expectedFingerprint = publicKey.sha256Hex()
        val fingerprint = payload.required("gateway_fingerprint").lowercase()
        require(MessageDigest.isEqual(expectedFingerprint.toByteArray(), fingerprint.toByteArray())) {
            "Gateway 指纹与签名公钥不一致"
        }
        val expiresAt = payload.required("expires_at")
        require(Instant.parse(expiresAt).isAfter(now)) { "配对二维码已经过期" }
        val gatewayUrl = validateGatewayUrl(payload.required("gateway_url"))
        return VerifiedPairing(
            gatewayUrl = gatewayUrl,
            gatewayName = payload.required("gateway_name"),
            gatewayPublicKey = publicKeyText,
            gatewayFingerprint = fingerprint,
            pairingId = payload.required("pairing_id"),
            pairingSecret = payload.required("pairing_secret"),
            expiresAt = expiresAt,
            raw = raw,
        )
    }

    fun validateGatewayUrl(value: String): String {
        val uri = URI(value.trim().trimEnd('/'))
        require(uri.scheme in setOf("http", "https") && !uri.host.isNullOrBlank()) {
            "Gateway 地址无效"
        }
        require(uri.userInfo == null && uri.query == null && uri.fragment == null) {
            "Gateway 地址不能包含账号或查询参数"
        }
        require(uri.path.isNullOrBlank() || uri.path == "/") { "Gateway 地址不能包含路径" }
        if (uri.scheme == "http") {
            require(isPrivateGatewayHost(uri.host)) {
                "公网 Gateway 必须使用 HTTPS；HTTP 仅允许局域网或 Tailscale 地址"
            }
        }
        return URI(uri.scheme, null, uri.host, uri.port, null, null, null).toString()
    }

    internal fun canonicalBytes(element: JsonElement): ByteArray =
        Json.encodeToString(JsonElement.serializer(), canonical(element)).toByteArray(Charsets.UTF_8)

    private fun canonical(element: JsonElement): JsonElement = when (element) {
        is JsonObject -> JsonObject(
            element.entries.sortedBy { it.key }.associate { it.key to canonical(it.value) },
        )
        is JsonArray -> JsonArray(element.map(::canonical))
        is JsonPrimitive -> element
    }

    private fun isPrivateGatewayHost(host: String): Boolean {
        val normalized = host.lowercase().trim('[', ']')
        if (normalized == "localhost" || normalized.endsWith(".local")) return true
        if (normalized.contains(':')) {
            return normalized == "::1" || normalized.startsWith("fc") ||
                normalized.startsWith("fd") || normalized.startsWith("fe8") ||
                normalized.startsWith("fe9") || normalized.startsWith("fea") ||
                normalized.startsWith("feb")
        }
        val parts = normalized.split('.').mapNotNull { it.toIntOrNull() }
        if (parts.size != 4 || parts.any { it !in 0..255 }) return false
        return parts[0] == 10 ||
            (parts[0] == 172 && parts[1] in 16..31) ||
            (parts[0] == 192 && parts[1] == 168) ||
            (parts[0] == 100 && parts[1] in 64..127) ||
            (parts[0] == 169 && parts[1] == 254) ||
            parts[0] == 127
    }

    private fun JsonObject.required(name: String): String =
        this[name]?.jsonPrimitive?.content?.takeIf { it.isNotBlank() }
            ?: error("配对二维码缺少 $name")

    private fun decodeUrlBase64(value: String): ByteArray =
        Base64.getUrlDecoder().decode(value.padEnd((value.length + 3) / 4 * 4, '='))

    private fun ByteArray.sha256Hex(): String = MessageDigest.getInstance("SHA-256")
        .digest(this)
        .joinToString("") { "%02x".format(it) }
}
