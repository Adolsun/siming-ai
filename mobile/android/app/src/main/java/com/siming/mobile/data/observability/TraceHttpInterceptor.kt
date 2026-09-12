package com.siming.mobile.data.observability

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicLong
import java.util.zip.GZIPInputStream
import java.util.zip.InflaterInputStream
import kotlinx.serialization.json.*
import okhttp3.Interceptor
import okhttp3.RequestBody
import okhttp3.Response
import okhttp3.ResponseBody
import okio.Buffer
import okio.BufferedSink
import okio.BufferedSource
import okio.ForwardingSink
import okio.ForwardingSource
import okio.buffer

internal class TraceHttpInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val trace = MobileTrace.current.get() ?: return chain.proceed(chain.request())
        if (trace.mode == "off") return chain.proceed(chain.request())
        val original = chain.request()
        val span = ContextSpan(trace, "provider_request", original.method)
        original.header("Authorization")?.let { trace.secrets.add(it); trace.secrets.add(it.removePrefix("Bearer ")) }
        original.header("x-api-key")?.let(trace.secrets::add)
        val metadata = buildJsonObject {
            put("endpoint", original.url.newBuilder().username("").password("").query(null).fragment(null).build().toString())
            put("method", original.method); put("attempt_id", span.id)
        }
        val requestCapture = WireCapture(trace, span, "provider_request", "application/json", "", metadata)
        val body = original.body
        val request = if (body == null) original.also { requestCapture.finish(true) } else original.newBuilder()
            .method(original.method, object : RequestBody() {
                override fun contentType() = body.contentType()
                override fun contentLength() = body.contentLength()
                override fun isDuplex() = body.isDuplex()
                override fun isOneShot() = body.isOneShot()
                override fun writeTo(sink: BufferedSink) {
                    val observed = object : ForwardingSink(sink) {
                        override fun write(source: Buffer, byteCount: Long) {
                            requestCapture.append(source, 0, byteCount)
                            super.write(source, byteCount)
                        }
                    }.buffer()
                    try { body.writeTo(observed); observed.flush(); requestCapture.finish(true) }
                    catch (error: Throwable) { requestCapture.finish(false); throw error }
                }
            }).build()
        val response = try { chain.proceed(request) } catch (error: Throwable) {
            requestCapture.finish(false); span.finish("error", error.javaClass.simpleName); throw error
        }
        trace.event("http_response", buildJsonObject { put("span_id", span.id); put("status_code", response.code) })
        val responseBody = response.body ?: return response.also { span.finish("completed") }
        val capture = WireCapture(trace, span, "provider_response", responseBody.contentType()?.toString()?.substringBefore(';').orEmpty(), response.header("Content-Encoding").orEmpty())
        val source = object : ForwardingSource(responseBody.source()) {
            override fun read(sink: Buffer, byteCount: Long): Long {
                return try {
                    val before = sink.size
                    super.read(sink, byteCount).also { count ->
                        if (count == -1L) { capture.finish(true); span.finish("completed") }
                        else capture.append(sink, before, count)
                    }
                } catch (error: Throwable) {
                    capture.finish(false); span.finish("error", error.javaClass.simpleName); throw error
                }
            }
            override fun close() {
                try { super.close() } finally { capture.finish(false); span.finish("partial") }
            }
        }.buffer()
        return response.newBuilder().body(object : ResponseBody() {
            override fun contentType() = responseBody.contentType()
            override fun contentLength() = responseBody.contentLength()
            override fun source(): BufferedSource = source
        }).build()
    }
}

private class WireCapture(
    val trace: ContextTrace, val span: ContextSpan, val layer: String,
    val media: String, val encoding: String, val metadata: JsonObject = buildJsonObject {},
) {
    private val bytes = ByteArrayOutputStream()
    private var reason: String? = if (trace.mode == "full") null else "recording_not_enabled"
    private var finished = false
    fun append(source: Buffer, offset: Long, count: Long) {
        if (reason != null) return
        runCatching {
            synchronized(memory) {
                if (count > TRACE_PAYLOAD_LIMIT - bytes.size() || memory.get() + count > 32 * 1024 * 1024) {
                    reason = "size_limit"; return
                }
                val copy = Buffer()
                source.copyTo(copy, offset, count)
                bytes.write(copy.readByteArray())
                memory.addAndGet(count)
            }
        }.onFailure { reason = "capture_failed" }
    }
    @Synchronized fun finish(complete: Boolean) {
        if (finished) return
        finished = true
        var ownsProcessing = false
        try {
            if (reason == null) {
                ownsProcessing = TraceRedaction.processing.tryAcquire()
                if (!ownsProcessing) reason = "capture_busy"
            }
            if (reason == null) {
                val raw = decodeCompression(bytes.toByteArray())
                val value = TraceRedaction.decode(raw, media)
                if (!TraceRedaction.withinBudget(value)) reason = "size_limit"
                else {
                    val clean = TraceRedaction.clean(value, synchronized(trace.secrets) { trace.secrets.toList() }).toString()
                    if (clean.toByteArray().size > TRACE_PAYLOAD_LIMIT) {
                        reason = "size_limit"
                        return
                    }
                    // Consumers may stop on [DONE] before requesting EOF. Keep safely parsed
                    // bytes, while stating the transport boundary was only partially read.
                    trace.payloadRecord(layer, clean, "http_transport", span.id,
                        if (complete) null else "stream_interrupted", metadata)
                    MobileTrace.usage(value, trace, span.id)
                }
            }
        } catch (_: Exception) { reason = "unparseable_body" }
        finally {
            if (ownsProcessing) TraceRedaction.processing.release()
            reason?.let { trace.payloadRecord(layer, null, "http_transport", span.id, it, metadata) }
            synchronized(memory) { memory.addAndGet(-bytes.size().toLong()); bytes.reset() }
        }
    }
    private fun decodeCompression(raw: ByteArray): ByteArray {
        val source = when (encoding.lowercase()) {
            "", "identity" -> return raw
            "gzip" -> GZIPInputStream(ByteArrayInputStream(raw))
            "deflate" -> InflaterInputStream(ByteArrayInputStream(raw))
            else -> error("unsupported encoding")
        }
        return source.use { input ->
            val result = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                check(result.size() + count <= TRACE_PAYLOAD_LIMIT)
                result.write(buffer, 0, count)
            }
            result.toByteArray()
        }
    }
    companion object { val memory = AtomicLong() }
}
