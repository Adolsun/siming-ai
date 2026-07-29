package com.siming.mobile.data

import android.content.Context
import androidx.room.withTransaction
import com.siming.mobile.data.local.GatewayConnection
import com.siming.mobile.data.local.LocalConflict
import com.siming.mobile.data.local.OutboxMutation
import com.siming.mobile.data.local.ReplicaEntity
import com.siming.mobile.data.local.SimingDatabase
import com.siming.mobile.data.local.SyncCursor
import com.siming.mobile.data.network.GatewayApi
import com.siming.mobile.data.network.PairingCompleteResponse
import com.siming.mobile.data.network.RemoteSyncProject
import com.siming.mobile.data.network.SyncMutationRequest
import com.siming.mobile.data.network.WorkspaceAssistantRequest
import com.siming.mobile.security.PairingSecurity
import com.siming.mobile.security.SecureTokenStore
import com.siming.mobile.security.StoredTokenPair
import com.siming.mobile.security.VerifiedPairing
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

@OptIn(ExperimentalSerializationApi::class)
class SimingRepository(context: Context) {
    private val appContext = context.applicationContext
    private val database = SimingDatabase.get(appContext)
    private val dao = database.dao()
    private val tokenStore = SecureTokenStore(appContext)
    private val api = GatewayApi(tokenStore)
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    val connection: Flow<GatewayConnection?> = dao.observeConnection()
    val projects: Flow<List<ReplicaEntity>> = dao.observeProjects()
    val pendingCount: Flow<Int> = dao.observePendingCount()
    val cursor: Flow<SyncCursor?> = dao.observeCursor()
    val conflicts: Flow<List<LocalConflict>> = dao.observeConflicts()

    fun entities(projectId: String, entityType: String): Flow<List<ReplicaEntity>> =
        dao.observeEntities(projectId, entityType)

    fun verifyPairing(raw: String): VerifiedPairing = PairingSecurity.verify(raw)

    suspend fun requestPairing(
        pairing: VerifiedPairing,
        deviceName: String,
    ): PairingCompleteResponse {
        val response = api.completePairing(
            pairing,
            deviceName.trim().ifBlank { "Android 手机" },
            tokenStore.devicePublicKey(),
        )
        if (response.status == "approved" && response.tokens != null) {
            tokenStore.save(
                StoredTokenPair(
                    response.tokens.accessToken,
                    response.tokens.accessExpiresAt,
                    response.tokens.refreshToken,
                    response.tokens.refreshExpiresAt,
                ),
            )
            dao.saveConnection(
                GatewayConnection(
                    baseUrl = pairing.gatewayUrl,
                    gatewayName = pairing.gatewayName,
                    gatewayFingerprint = pairing.gatewayFingerprint,
                    deviceId = requireNotNull(response.deviceId),
                    deviceRole = response.deviceRole ?: "member",
                    protocolVersion = 1,
                ),
            )
            SyncScheduler.install(appContext)
        }
        return response
    }

    suspend fun availableRemoteProjects(): List<RemoteSyncProject> {
        val connection = requireConnection()
        return api.listSyncProjects(connection).filter { it.status == "enabled" }
    }

    suspend fun bootstrapEnabledProjects(): Int {
        val connection = requireConnection()
        val projectIds = api.listSyncProjects(connection)
            .filter { it.status == "enabled" }
            .map { it.projectId }
        if (projectIds.isEmpty()) {
            dao.saveCursor(SyncCursor(cursor = 0, lastSuccessfulSyncAt = System.currentTimeMillis()))
            return 0
        }
        val response = api.bootstrap(connection, projectIds)
        database.withTransaction {
            for (snapshot in response.entities) {
                val key = ReplicaEntity.key(
                    snapshot.projectId,
                    snapshot.entityType,
                    snapshot.entityId,
                )
                val local = dao.entity(key)
                if (local?.dirty == true || local?.conflicted == true) continue
                dao.saveEntity(
                    ReplicaEntity(
                        key = key,
                        projectId = snapshot.projectId,
                        entityType = snapshot.entityType,
                        entityId = snapshot.entityId,
                        revision = snapshot.revision,
                        operation = snapshot.operation,
                        payloadJson = snapshot.payload?.let(json::encodeToString),
                        contentHash = snapshot.contentHash,
                        serverModifiedAt = snapshot.serverModifiedAt,
                    ),
                )
            }
            dao.saveCursor(
                SyncCursor(
                    cursor = response.cursor,
                    lastSuccessfulSyncAt = System.currentTimeMillis(),
                ),
            )
        }
        return projectIds.size
    }

    suspend fun createProject(title: String, description: String = ""): String {
        val id = UUID.randomUUID().toString()
        saveEntity(
            projectId = id,
            entityType = "project",
            entityId = id,
            payload = buildJsonObject {
                put("_record_type", "project")
                put("id", id)
                put("title", title.trim().ifBlank { "未命名作品" })
                put("description", description.trim())
                put("narrative_perspective", "third_person")
                put("writing_style", "natural")
                put("short_sentences", false)
                put("daily_word_goal", 6000)
            },
        )
        return id
    }

    suspend fun saveEntity(
        projectId: String,
        entityType: String,
        entityId: String = UUID.randomUUID().toString(),
        payload: JsonObject,
    ): String {
        val key = ReplicaEntity.key(projectId, entityType, entityId)
        val encoded = json.encodeToString(payload)
        require(encoded.toByteArray(Charsets.UTF_8).size <= MAX_ENTITY_BYTES) {
            "单条资料不能超过 1 MiB；请把超长正文拆成多个章节"
        }
        val now = Instant.now().toString()
        database.withTransaction {
            val current = dao.entity(key)
            val existingPending = dao.pendingMutation(projectId, entityType, entityId)
            dao.saveEntity(
                ReplicaEntity(
                    key = key,
                    projectId = projectId,
                    entityType = entityType,
                    entityId = entityId,
                    revision = current?.revision ?: 0,
                    operation = "upsert",
                    payloadJson = encoded,
                    contentHash = sha256(encoded),
                    serverModifiedAt = current?.serverModifiedAt ?: now,
                    dirty = true,
                    conflicted = current?.conflicted ?: false,
                ),
            )
            dao.saveMutation(
                (existingPending ?: OutboxMutation(
                    mutationId = UUID.randomUUID().toString(),
                    projectId = projectId,
                    entityType = entityType,
                    entityId = entityId,
                    operation = "upsert",
                    baseRevision = current?.revision ?: 0,
                    payloadJson = encoded,
                    clientModifiedAt = now,
                )).copy(
                    payloadJson = encoded,
                    clientModifiedAt = now,
                    state = "pending",
                    lastError = null,
                ),
            )
        }
        SyncScheduler.enqueue(appContext)
        return entityId
    }

    suspend fun deleteEntity(projectId: String, entityType: String, entityId: String) {
        require(entityType != "project") { "移动端不会直接删除整部作品" }
        val key = ReplicaEntity.key(projectId, entityType, entityId)
        val now = Instant.now().toString()
        database.withTransaction {
            val current = dao.entity(key) ?: return@withTransaction
            val existingPending = dao.pendingMutation(projectId, entityType, entityId)
            dao.saveEntity(
                current.copy(
                    operation = "delete",
                    payloadJson = null,
                    contentHash = sha256("null"),
                    dirty = true,
                    localModifiedAt = System.currentTimeMillis(),
                ),
            )
            dao.saveMutation(
                (existingPending ?: OutboxMutation(
                    mutationId = UUID.randomUUID().toString(),
                    projectId = projectId,
                    entityType = entityType,
                    entityId = entityId,
                    operation = "delete",
                    baseRevision = current.revision,
                    payloadJson = null,
                    clientModifiedAt = now,
                )).copy(
                    operation = "delete",
                    payloadJson = null,
                    clientModifiedAt = now,
                    state = "pending",
                    lastError = null,
                ),
            )
        }
        SyncScheduler.enqueue(appContext)
    }

    suspend fun syncNow(): SyncOutcome = syncMutex.withLock {
        val connection = requireConnection()
        val localProjectIds = dao.localProjectIds()
        try {
            pushPending(connection)
            refreshConflicts(connection)
            if (localProjectIds.isNotEmpty()) pullAll(connection, localProjectIds)
            val current = dao.cursor() ?: SyncCursor()
            dao.saveCursor(
                current.copy(
                    lastSuccessfulSyncAt = System.currentTimeMillis(),
                    lastError = null,
                ),
            )
            SyncOutcome.Success
        } catch (error: Exception) {
            val current = dao.cursor() ?: SyncCursor()
            dao.saveCursor(current.copy(lastError = error.toUserFacingMessage()))
            throw error
        }
    }

    private suspend fun pushPending(connection: GatewayConnection) {
        while (true) {
            val candidates = dao.pendingMutations(100)
            val pending = buildList {
                var estimatedBytes = 0
                for (mutation in candidates) {
                    val mutationBytes = (mutation.payloadJson?.toByteArray(Charsets.UTF_8)?.size ?: 4) + 512
                    if (isNotEmpty() && estimatedBytes + mutationBytes > MAX_PUSH_BYTES) break
                    add(mutation)
                    estimatedBytes += mutationBytes
                }
            }
            if (pending.isEmpty()) return
            database.withTransaction {
                pending.forEach { mutation ->
                    dao.updateMutation(
                        mutation.copy(
                            state = "sending",
                            sentPayloadHash = sha256(mutation.payloadJson ?: "null"),
                        ),
                    )
                }
            }
            val response = try {
                api.push(
                    connection,
                    pending.map { mutation ->
                        SyncMutationRequest(
                            mutationId = mutation.mutationId,
                            projectId = mutation.projectId,
                            entityType = mutation.entityType,
                            entityId = mutation.entityId,
                            operation = mutation.operation,
                            baseRevision = mutation.baseRevision,
                            payload = mutation.payloadJson?.let {
                                json.parseToJsonElement(it) as JsonObject
                            },
                            clientModifiedAt = mutation.clientModifiedAt,
                        )
                    },
                )
            } catch (error: Exception) {
                database.withTransaction {
                    pending.forEach { mutation ->
                        resetForRetry(mutation, error.toUserFacingMessage())
                    }
                }
                throw error
            }
            database.withTransaction {
                val returnedIds = response.results.mapTo(mutableSetOf()) { it.mutationId }
                for (result in response.results) {
                    val sent = pending.firstOrNull { it.mutationId == result.mutationId } ?: continue
                    val key = ReplicaEntity.key(sent.projectId, sent.entityType, sent.entityId)
                    val current = dao.entity(key)
                    when (result.status) {
                        "applied", "duplicate" -> {
                            val revision = result.revision ?: current?.revision ?: sent.baseRevision
                            dao.deleteMutation(sent.mutationId)
                            if (current != null) {
                                val unchanged = sha256(current.payloadJson ?: "null") ==
                                    sha256(sent.payloadJson ?: "null") && current.operation == sent.operation
                                dao.saveEntity(
                                    current.copy(
                                        revision = revision,
                                        dirty = !unchanged,
                                        conflicted = false,
                                    ),
                                )
                                if (!unchanged && dao.pendingMutation(
                                        sent.projectId,
                                        sent.entityType,
                                        sent.entityId,
                                    ) == null
                                ) {
                                    dao.saveMutation(
                                        OutboxMutation(
                                            mutationId = UUID.randomUUID().toString(),
                                            projectId = sent.projectId,
                                            entityType = sent.entityType,
                                            entityId = sent.entityId,
                                            operation = current.operation,
                                            baseRevision = revision,
                                            payloadJson = current.payloadJson,
                                            clientModifiedAt = Instant.now().toString(),
                                        ),
                                    )
                                }
                            }
                        }
                        "conflict" -> {
                            dao.updateMutation(
                                sent.copy(
                                    state = "conflict",
                                    lastError = result.message ?: "双方均有离线修改",
                                ),
                            )
                            if (current != null) dao.saveEntity(current.copy(conflicted = true))
                            dao.saveConflict(
                                LocalConflict(
                                    id = result.conflictId ?: UUID.randomUUID().toString(),
                                    projectId = sent.projectId,
                                    entityType = sent.entityType,
                                    entityId = sent.entityId,
                                    clientPayloadJson = sent.payloadJson,
                                    serverPayloadJson = (result.serverSnapshot?.get("payload") as? JsonObject)
                                        ?.let(json::encodeToString),
                                    serverRevision = result.revision ?: sent.baseRevision,
                                ),
                            )
                        }
                        else -> dao.updateMutation(
                            sent.copy(state = "pending", lastError = result.message ?: "内容未通过校验"),
                        )
                    }
                }
                pending.filterNot { it.mutationId in returnedIds }.forEach { mutation ->
                    resetForRetry(mutation, "Gateway 未返回该修订的处理结果")
                }
            }
            if (response.results.none { it.status in setOf("applied", "duplicate") }) return
        }
    }

    private suspend fun pullAll(connection: GatewayConnection, projectIds: List<String>) {
        var cursorValue = dao.cursor()?.cursor ?: 0
        do {
            val response = api.pull(connection, cursorValue, projectIds)
            database.withTransaction {
                for (change in response.changes) {
                    val key = ReplicaEntity.key(change.projectId, change.entityType, change.entityId)
                    val local = dao.entity(key)
                    if (local?.dirty == true || local?.conflicted == true) continue
                    dao.saveEntity(
                        ReplicaEntity(
                            key = key,
                            projectId = change.projectId,
                            entityType = change.entityType,
                            entityId = change.entityId,
                            revision = change.revision,
                            operation = change.operation,
                            payloadJson = change.payload?.let(json::encodeToString),
                            contentHash = change.contentHash,
                            serverModifiedAt = change.changedAt,
                        ),
                    )
                }
                cursorValue = response.nextCursor
                dao.saveCursor(
                    (dao.cursor() ?: SyncCursor()).copy(cursor = cursorValue),
                )
            }
        } while (response.hasMore)
    }

    private suspend fun refreshConflicts(connection: GatewayConnection) {
        val remote = api.listConflicts(connection)
        database.withTransaction {
            val remoteIds = remote.mapTo(mutableSetOf()) { it.id }
            dao.openConflictsSnapshot()
                .filterNot { it.id in remoteIds }
                .forEach { resolved ->
                    dao.resolveConflict(resolved.id)
                    dao.deleteConflictMutation(
                        resolved.projectId,
                        resolved.entityType,
                        resolved.entityId,
                    )
                    val key = ReplicaEntity.key(
                        resolved.projectId,
                        resolved.entityType,
                        resolved.entityId,
                    )
                    dao.entity(key)?.let {
                        dao.saveEntity(it.copy(dirty = false, conflicted = false))
                    }
                }
            for (conflict in remote) {
                dao.saveConflict(
                    LocalConflict(
                        id = conflict.id,
                        projectId = conflict.projectId,
                        entityType = conflict.entityType,
                        entityId = conflict.entityId,
                        clientPayloadJson = conflict.clientPayload?.let(json::encodeToString),
                        serverPayloadJson = conflict.serverPayload?.let(json::encodeToString),
                        serverRevision = conflict.serverRevision,
                        status = conflict.status,
                    ),
                )
                val key = ReplicaEntity.key(
                    conflict.projectId,
                    conflict.entityType,
                    conflict.entityId,
                )
                dao.entity(key)?.let { dao.saveEntity(it.copy(conflicted = true)) }
            }
        }
    }

    private suspend fun resetForRetry(mutation: OutboxMutation, error: String) {
        val newer = dao.pendingMutation(
            mutation.projectId,
            mutation.entityType,
            mutation.entityId,
        )
        if (newer != null && newer.mutationId != mutation.mutationId) {
            // A save made while this request was in flight already contains the
            // latest payload at the same base revision, so the older send can
            // be discarded instead of creating an avoidable self-conflict.
            dao.deleteMutation(mutation.mutationId)
        } else {
            dao.resetMutationForRetry(mutation.mutationId, error)
        }
    }

    suspend fun resolveConflict(conflict: LocalConflict, choice: String) {
        val connection = requireConnection()
        api.resolveConflict(connection, conflict.id, choice)
        dao.resolveConflict(conflict.id)
        dao.deleteConflictMutation(conflict.projectId, conflict.entityType, conflict.entityId)
        val key = ReplicaEntity.key(conflict.projectId, conflict.entityType, conflict.entityId)
        dao.entity(key)?.let { dao.saveEntity(it.copy(dirty = false, conflicted = false)) }
        syncNow()
    }

    suspend fun runAssistant(
        projectId: String,
        scope: String,
        prompt: String,
        onEvent: suspend (String) -> Unit,
    ) {
        api.streamAssistant(
            requireConnection(),
            projectId,
            WorkspaceAssistantRequest(scope = scope, message = prompt),
            onEvent,
        )
        syncNow()
    }

    suspend fun disconnect(clearOfflineData: Boolean): Boolean {
        val connection = dao.connection()
        val revokedRemotely = connection != null && runCatching {
            api.revokeSelf(connection)
        }.isSuccess
        tokenStore.clear()
        database.withTransaction {
            dao.deleteConnection()
            dao.clearCursor()
            if (clearOfflineData) {
                dao.clearOutbox()
                dao.clearConflicts()
                dao.clearReplicas()
            }
        }
        SyncScheduler.cancel(appContext)
        return revokedRemotely
    }

    private suspend fun requireConnection(): GatewayConnection =
        dao.connection() ?: error("请先连接自己的 Gateway")

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }

    companion object {
        private const val MAX_ENTITY_BYTES = 1024 * 1024
        private const val MAX_PUSH_BYTES = 6 * 1024 * 1024
        private val syncMutex = Mutex()
    }
}

sealed interface SyncOutcome {
    data object Success : SyncOutcome
}
