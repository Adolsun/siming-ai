package com.siming.mobile.data.observability

import android.content.Context
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

internal class ContextTraceStore private constructor(context: Context) : ContextTraceSink {
    private val app = context.applicationContext
    private val preferences = app.getSharedPreferences("context_trace_settings", Context.MODE_PRIVATE)
    private val database = ContextTraceDatabase.create(app)
    private val dao = database.traces()
    private val writer = ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS, ArrayBlockingQueue(256))
    private val pending = AtomicLong()
    val dropped = AtomicInteger()
    val writeErrors = AtomicInteger()
    @Volatile private var configuredMode = preferences.getString("mode", "summary") ?: "summary"
    @Volatile private var fullUntil = preferences.getLong("full_until", 0)
    init {
        writer.execute { runCatching {
            val sqlite = database.openHelper.writableDatabase
            val pageSize = sqlite.query("PRAGMA page_size").use { it.moveToFirst(); it.getLong(0) }
            sqlite.execSQL("PRAGMA max_page_count=${64L * 1024 * 1024 / pageSize}")
            dao.interrupt(System.currentTimeMillis() / 1000.0); prune()
        }.onFailure { writeErrors.incrementAndGet() } }
    }
    override fun mode() = if (configuredMode == "full" && fullUntil > 0 && System.currentTimeMillis() > fullUntil) "summary" else configuredMode
    fun policy() = buildJsonObject {
        put("mode", mode())
        put("full_until", fullUntil.takeIf { it > 0 }?.let { JsonPrimitive(it / 1000.0) } ?: JsonNull)
    }
    fun setMode(mode: String, timed: Boolean) {
        require(mode in setOf("off", "summary", "full"))
        configuredMode = mode
        fullUntil = if (mode == "full" && timed) System.currentTimeMillis() + 3_600_000 else 0
        preferences.edit().putString("mode", mode).putLong("full_until", fullUntil).apply()
    }
    override fun submit(event: JsonObject, content: String?): Boolean {
        val size = (content?.toByteArray()?.size ?: 0).toLong() + event.toString().toByteArray().size
        if (pending.addAndGet(size) > 32 * 1024 * 1024) {
            pending.addAndGet(-size); dropped.incrementAndGet(); return false
        }
        return runCatching {
            writer.execute {
                try { write(event, content) }
                catch (_: Exception) { writeErrors.incrementAndGet(); runCatching { dao.partial(event.text("trace_id")) } }
                finally { pending.addAndGet(-size) }
            }
            true
        }.getOrElse { pending.addAndGet(-size); dropped.incrementAndGet(); false }
    }
    private fun write(event: JsonObject, content: String?) {
        val data = event["data"]!!.jsonObject
        val traceId = event.text("trace_id")
        if (content != null) prune()
        database.runInTransaction {
            when (event.text("event_type")) {
                "trace_started" -> {
                    val scope = data["scope"]!!.jsonObject
                    dao.insertTrace(TraceRow(id = traceId, scopeKind = scope.text("kind"), scopeId = scope.text("id"),
                        started = data["started_at"]!!.jsonPrimitive.double, mode = data.text("mode"), correlations = data["correlations"].toString()))
                    dao.insertCorrelations((data["correlations"] as? JsonObject)?.values.orEmpty().mapNotNull { value ->
                        (value as? JsonPrimitive)?.contentOrNull?.let { TraceCorrelationRow(traceId, it) }
                    })
                }
                "trace_finished" -> dao.finish(traceId, data["finished_at"]!!.jsonPrimitive.double, data.text("status"), data.text("capture_status"))
            }
            if (data.text("missing_reason").isNotEmpty() && data.text("missing_reason") != "recording_not_enabled") dao.partial(traceId)
            dao.insertEvent(TraceEventRow(event.text("event_id"), traceId, event["sequence"]!!.jsonPrimitive.int, event.toString(), content))
        }
        if (event.text("event_type") == "trace_finished") prune()
    }
    private fun prune() {
        dao.expire(System.currentTimeMillis() / 1000.0 - 7 * 86400)
        val sqlite = database.openHelper.writableDatabase
        fun number(pragma: String) = sqlite.query("PRAGMA $pragma").use { it.moveToFirst(); it.getLong(0) }
        fun liveBytes() = (number("page_count") - number("freelist_count")) * number("page_size")
        // Reuse freed pages without VACUUM's additional full-database temporary copy.
        while (liveBytes() > 48 * 1024 * 1024 && dao.deleteOldest() > 0) { /* bounded by completed traces */ }
    }
    suspend fun traces(kind: String?, scopeId: String?, correlationId: String?, before: Long? = null) = withContext(Dispatchers.IO) { dao.list(kind, scopeId, correlationId, before) }
    suspend fun events(id: String, after: Int = 0) = withContext(Dispatchers.IO) { dao.events(id, after).map { Json.parseToJsonElement(it).jsonObject } }
    suspend fun payload(traceId: String, payloadId: String, offset: Int) = withContext(Dispatchers.IO) {
        val content = requireNotNull(dao.payload(traceId, payloadId, offset)) { "本段内容未记录或已清理" }
        buildJsonObject { put("content", content); put("total_characters", dao.payloadSize(traceId, payloadId) ?: 0)
            put("next_offset", offset + content.codePointCount(0, content.length)) }
    }
    suspend fun clear() = withContext(Dispatchers.IO) { dao.clear() }
    suspend fun trace(id: String) = withContext(Dispatchers.IO) { dao.trace(id) }
    companion object {
        @Volatile private var instance: ContextTraceStore? = null
        fun get(context: Context): ContextTraceStore = instance ?: synchronized(this) {
            instance ?: ContextTraceStore(context).also { instance = it; MobileTrace.sink = it }
        }
    }
}

internal fun JsonObject.text(key: String): String = (get(key) as? JsonPrimitive)?.contentOrNull.orEmpty()
