package com.siming.mobile

import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.siming.mobile.data.MobileProjectPackageFile
import com.siming.mobile.data.MobileProjectPackageWriter
import com.siming.mobile.data.SimingRepository
import com.siming.mobile.data.sha256File
import com.siming.mobile.data.local.GatewayConnection
import com.siming.mobile.data.local.LocalConflict
import com.siming.mobile.data.local.OutboxMutation
import com.siming.mobile.data.local.ProjectDeletionResult
import com.siming.mobile.data.local.ProjectSyncStatus
import com.siming.mobile.data.local.ReplicaEntity
import com.siming.mobile.data.local.SimingDatabase
import com.siming.mobile.data.local.syncStatus
import java.io.File
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ProjectDeletionInstrumentedTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    private fun project(id: String, revision: Long = 0, dirty: Boolean = false) = ReplicaEntity(
        key = ReplicaEntity.key(id, "project", id), projectId = id, entityType = "project", entityId = id,
        revision = revision, operation = "upsert", payloadJson = """{"_record_type":"project","id":"$id","title":"Deletion fixture"}""",
        contentHash = "hash", serverModifiedAt = "2026-09-14T00:00:00Z", dirty = dirty,
    )

    @Test
    fun anOfflineImportCanBeDeletedWithItsArchiveAndQueuedEditsOnly() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, SimingDatabase::class.java).build()
        val source = File.createTempFile("delete-import-", ".siming-project", context.cacheDir)
        var retained: File? = null
        try {
            val dao = db.dao()
            val repository = SimingRepository(context, db)
            MobileProjectPackageWriter.write("source", listOf(project("source")), null, "full", source)
            val result = repository.importProjectPackage(MobileProjectPackageFile(
                source.name, source, source.length(), sha256File(source),
            ))
            val id = result.projectId
            assertFalse(result.remote)
            val initial = repository.projects.first().single()
            assertFalse(initial.project.dirty)
            assertEquals(0L, initial.project.revision)
            assertEquals(ProjectSyncStatus.LOCAL_ONLY, initial.syncStatus)
            retained = File(dao.projectPackage(id)!!.localFilePath)
            assertTrue(retained.isFile)
            dao.saveMutation(OutboxMutation("edit", id, "chapter", "chapter", "upsert", 0, "{}", "now"))
            dao.saveEntity(project(id).copy(
                key = ReplicaEntity.key(id, "chapter", "chapter"), entityType = "chapter", entityId = "chapter", dirty = true,
            ))
            dao.saveConflict(LocalConflict("closed", id, "chapter", "chapter", "{}", "{}", 0, status = "resolved"))
            dao.saveEntity(project("other", revision = 8))
            assertEquals(2, dao.pendingMutationCount())

            assertEquals(ProjectDeletionResult.LOCAL_ONLY, repository.deleteProject(id, localOnly = true))
            assertNull(dao.projectSyncRecord(id))
            assertNull(dao.projectPackage(id))
            assertTrue(dao.projectPackageSnapshot(id).isEmpty())
            assertEquals(0, dao.pendingMutationCount())
            assertNull(dao.pendingMutation(id, "chapter", "chapter"))
            assertFalse(retained.exists())
            db.openHelper.readableDatabase.query("SELECT COUNT(*) FROM local_conflicts").use {
                assertTrue(it.moveToFirst())
                assertEquals(0, it.getInt(0))
            }
            assertEquals(listOf("other"), repository.projects.first().map { it.project.projectId })
            assertEquals(ProjectDeletionResult.ALREADY_ABSENT, repository.deleteProject(id, localOnly = true))
        } finally {
            db.close()
            source.delete()
            retained?.delete()
        }
    }

    @Test
    fun aConfiguredButUnavailableGatewayDoesNotReceiveAnUnuploadedProjectForDeletion() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, SimingDatabase::class.java).build()
        val source = File.createTempFile("delete-configured-", ".siming-project", context.cacheDir)
        var retained: File? = null
        try {
            val dao = db.dao()
            val repository = SimingRepository(context, db)
            MobileProjectPackageWriter.write("source", listOf(project("source")), null, "full", source)
            val result = repository.importProjectPackage(MobileProjectPackageFile(
                source.name, source, source.length(), sha256File(source),
            ))
            retained = File(dao.projectPackage(result.projectId)!!.localFilePath)
            dao.saveConnection(GatewayConnection(baseUrl = "http://127.0.0.1:1", gatewayName = "Unavailable fixture",
                gatewayFingerprint = "fixture", deviceId = "fixture", deviceRole = "owner", protocolVersion = 1))
            assertEquals(ProjectDeletionResult.LOCAL_ONLY, repository.deleteProject(result.projectId, localOnly = true))
            assertFalse(retained.exists())
            assertEquals(0, dao.pendingMutationCount())
        } finally {
            db.close()
            source.delete()
            retained?.delete()
        }
    }

    @Test
    fun offlineDeletionPreservesSyncedProjectsAndUnconfirmedUploads() = runBlocking {
        val db = Room.inMemoryDatabaseBuilder(context, SimingDatabase::class.java).build()
        val source = File.createTempFile("delete-uncertain-", ".siming-project", context.cacheDir)
        var retained: File? = null
        try {
            val dao = db.dao()
            val repository = SimingRepository(context, db)
            MobileProjectPackageWriter.write("source", listOf(project("source")), null, "full", source)
            val imported = repository.importProjectPackage(MobileProjectPackageFile(
                source.name, source, source.length(), sha256File(source),
            ))
            val stored = dao.projectPackage(imported.projectId)!!
            retained = File(stored.localFilePath)
            suspend fun blocked(id: String) {
                val result = runCatching { repository.deleteProject(id, localOnly = false) }
                assertTrue(result.exceptionOrNull() is IllegalStateException)
                assertNotNull(dao.projectSyncRecord(id))
            }
            dao.saveProjectPackage(stored.copy(syncState = "uploading"))
            assertEquals(ProjectSyncStatus.UNCONFIRMED, dao.projectSyncRecord(imported.projectId)!!.syncStatus)
            blocked(imported.projectId)
            dao.saveProjectPackage(stored.copy(lastError = "Upload response lost"))
            blocked(imported.projectId)
            dao.saveProjectPackage(stored.copy(syncState = "succeeded", uploadedAt = 1))
            blocked(imported.projectId)
            val staleConfirmation = runCatching { repository.deleteProject(imported.projectId, localOnly = true) }
            assertTrue(staleConfirmation.exceptionOrNull()?.message.orEmpty().contains("同步状态已改变"))
            assertTrue(retained.exists())
            for (dirty in listOf(false, true)) {
                dao.saveEntity(project("remote", revision = 8, dirty = dirty))
                blocked("remote")
            }
            dao.saveEntity(project("local", dirty = true))
            val mutation = OutboxMutation("create", "local", "project", "local", "upsert", 0, "{}", "now")
            dao.saveMutation(mutation.copy(state = "sending", sentPayloadHash = "hash"))
            blocked("local")
            dao.saveMutation(mutation.copy(lastError = "Response lost", sentPayloadHash = "hash"))
            blocked("local")
            dao.saveMutation(mutation)
            assertEquals(ProjectSyncStatus.LOCAL_ONLY, dao.projectSyncRecord("local")!!.syncStatus)
            assertEquals(ProjectDeletionResult.LOCAL_ONLY, repository.deleteProject("local", localOnly = true))
            assertNotNull(dao.projectSyncRecord("remote"))
            assertNotNull(dao.projectSyncRecord(imported.projectId))
        } finally {
            db.close()
            source.delete()
            retained?.delete()
        }
    }
}
