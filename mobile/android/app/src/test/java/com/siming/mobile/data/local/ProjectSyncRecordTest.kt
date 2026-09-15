package com.siming.mobile.data.local

import kotlin.test.Test
import kotlin.test.assertEquals

class ProjectSyncRecordTest {
    private val project = ReplicaEntity(
        key = "p|project|p", projectId = "p", entityType = "project", entityId = "p",
        revision = 0, operation = "upsert", payloadJson = "{}", contentHash = "hash",
        serverModifiedAt = "2026-09-14T00:00:00Z",
    )
    private val imported = ProjectSyncRecord(project, "pending", null, null, false, false)

    @Test
    fun aCleanUnuploadedImportIsLocalEvenAfterAnOfflineEdit() {
        assertEquals(ProjectSyncStatus.LOCAL_ONLY, imported.syncStatus)
        assertEquals(ProjectSyncStatus.LOCAL_ONLY, imported.copy(project = project.copy(dirty = true)).syncStatus)
    }

    @Test
    fun uploadInProgressOrUncertainReceiptCannotBeDeletedLocally() {
        assertEquals(ProjectSyncStatus.UNCONFIRMED, imported.copy(packageSyncState = "uploading").syncStatus)
        assertEquals(ProjectSyncStatus.UNCONFIRMED, imported.copy(packageLastError = "Response lost").syncStatus)
        assertEquals(ProjectSyncStatus.UNCONFIRMED, imported.copy(packageSyncState = "unknown").syncStatus)
    }

    @Test
    fun anUploadReceiptOrServerRevisionTakesPrecedenceOverLocalFlags() {
        assertEquals(ProjectSyncStatus.SYNCED, imported.copy(packageSyncState = "succeeded").syncStatus)
        assertEquals(ProjectSyncStatus.SYNC_PENDING, imported.copy(packageUploadedAt = 1).syncStatus)
        assertEquals(ProjectSyncStatus.SYNC_PENDING, imported.copy(project = project.copy(revision = 7)).syncStatus)
        val remote = imported.copy(packageSyncState = null, project = project.copy(revision = 7))
        assertEquals(ProjectSyncStatus.SYNCED, remote.syncStatus)
        assertEquals(ProjectSyncStatus.SYNC_PENDING, remote.copy(project = remote.project.copy(dirty = true)).syncStatus)
    }

    @Test
    fun ordinaryLocalCreationRequiresAnUnsentCreationRecord() {
        val ordinary = imported.copy(packageSyncState = null, project = project.copy(dirty = true))
        assertEquals(ProjectSyncStatus.UNCONFIRMED, ordinary.syncStatus)
        assertEquals(ProjectSyncStatus.LOCAL_ONLY, ordinary.copy(hasUnsentCreation = true).syncStatus)
        assertEquals(ProjectSyncStatus.UNCONFIRMED,
            ordinary.copy(hasUnsentCreation = true, creationWasSent = true).syncStatus)
        assertEquals(ProjectSyncStatus.UNCONFIRMED, ordinary.copy(project = project).syncStatus)
    }
}
