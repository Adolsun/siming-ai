package com.siming.mobile.data.local

import kotlin.test.Test
import kotlin.test.assertEquals

class ReplicaOrderingTest {
    @Test
    fun chaptersUseCanonicalCreationTimeInsteadOfLocalBootstrapTime() {
        val records = listOf(
            chapter("third", "第三章", "2026-08-16T10:00:03.000000Z", 9_999),
            chapter("first", "第一章", "2026-08-16T10:00:01.000000Z", 9_997),
            chapter("second", "第二章", "2026-08-16T10:00:02.000000Z", 9_998),
        )

        assertEquals(
            listOf("first", "second", "third"),
            orderReplicaEntities("chapter", records).map(ReplicaEntity::entityId),
        )
    }

    @Test
    fun locallyImportedChaptersFallBackToNumberThenCreationTime() {
        val records = listOf(
            chapter("ten", "第10章", null, 3_000),
            chapter("two", "第2章", null, 2_000),
            chapter("one", "第1章", null, 1_000),
        )

        assertEquals(
            listOf("one", "two", "ten"),
            orderReplicaEntities("chapter", records).map(ReplicaEntity::entityId),
        )
    }

    private fun chapter(id: String, title: String, createdAt: String?, localModifiedAt: Long): ReplicaEntity {
        val createdAtField = createdAt?.let { "\"created_at\":\"$it\"," } ?: ""
        return ReplicaEntity(
            key = ReplicaEntity.key("project", "chapter", id),
            projectId = "project",
            entityType = "chapter",
            entityId = id,
            revision = 1,
            operation = "upsert",
            payloadJson = "{$createdAtField\"title\":\"$title\"}",
            contentHash = id,
            serverModifiedAt = "2026-08-16T10:00:00Z",
            localModifiedAt = localModifiedAt,
        )
    }
}
