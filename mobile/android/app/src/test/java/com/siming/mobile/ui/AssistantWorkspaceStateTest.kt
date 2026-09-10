package com.siming.mobile.ui

import com.siming.mobile.data.MobileAssistantMessage
import com.siming.mobile.data.MobilePendingChapterDraft
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class AssistantWorkspaceStateTest {
    private val draft = MobilePendingChapterDraft("draft-1", "p1", "标题", "正文")

    @Test
    fun `old tool logs stay with their reply before a newer user message`() {
        val oldReply = MobileAssistantMessage("reply-1", "assistant", "已完成建档", toolLogs = listOf("建档开始", "建档完成"), sequenceNo = 2)
        val next = MobileAssistantMessage("user-2", "user", "继续下一章", sequenceNo = 3)
        val loaded = MobileUiState(assistantOutput = "已完成建档", assistantToolLog = oldReply.toolLogs,
            assistantLiveTurnId = "live-1", assistantCurrentPrompt = "继续下一章")
            .withAssistantHistory("conversation-1", listOf(next, oldReply), null)
        assertEquals(listOf("reply-1", "user-2"), loaded.assistantMessages.map { it.id })
        assertEquals(oldReply.toolLogs, loaded.assistantMessages.first().toolLogs)
        assertTrue(loaded.assistantToolLog.isEmpty())
        assertTrue(loaded.assistantOutput.isEmpty())
        assertNull(loaded.assistantLiveTurnId)
    }

    @Test
    fun `identical author messages retain their individual identities and sequence overrides clock skew`() {
        val first = MobileAssistantMessage("user-1", "user", "继续下一章", createdAt = "2026-09-10T04:30:00Z", sequenceNo = 1)
        val second = first.copy(id = "user-2", createdAt = "2026-09-10T03:30:00Z", sequenceNo = 3)
        assertEquals(listOf(first, second), orderedAssistantMessages(listOf(second, first)))
        val live = MobileUiState(assistantMessages = listOf(first), assistantCurrentPrompt = first.content, assistantLiveTurnId = "new-turn")
        assertEquals(first.content, live.assistantCurrentPrompt)
        assertTrue(live.assistantLiveTurnId != null)
    }

    @Test
    fun `timestamp ordering accepts PC UTC timestamps and partially ordered histories retain source order`() {
        val older = MobileAssistantMessage("a", "assistant", "旧消息", createdAt = "2026-09-10 03:27:00")
        val newer = MobileAssistantMessage("b", "user", "新消息", createdAt = "2026-09-10T11:28:00+08:00")
        assertEquals(listOf(older, newer), orderedAssistantMessages(listOf(newer, older)))
        val partial = listOf(newer.copy(createdAt = ""), older.copy(sequenceNo = 1))
        assertEquals(partial, orderedAssistantMessages(partial))
    }

    @Test
    fun `authoritative empty draft response is accepted but late reads cannot resurrect a saved draft`() {
        val guard = PendingChapterDraftRefreshGuard()
        val refresh = guard.begin(draft)
        assertTrue(guard.accepts(refresh, draft)) // A successful null response is allowed to clear this draft.
        val beforeSave = guard.begin(draft)
        guard.invalidate()
        assertFalse(guard.accepts(beforeSave, null))
        val initiallyEmpty = guard.begin(null)
        guard.invalidate() // Saving or discarding also invalidates reads that began with an empty screen.
        assertFalse(guard.accepts(initiallyEmpty, null))
    }

    @Test
    fun `a late project read or generation refresh cannot overwrite a new draft or an author edit`() {
        val guard = PendingChapterDraftRefreshGuard()
        val firstProject = guard.begin(null)
        val secondProject = guard.begin(null)
        assertFalse(guard.accepts(firstProject, null))
        assertTrue(guard.accepts(secondProject, null))
        val beforeEdit = guard.begin(draft)
        assertFalse(guard.accepts(beforeEdit, draft.copy(content = "作者修改")))
        val beforeGeneration = guard.begin(null)
        assertFalse(guard.accepts(beforeGeneration, draft))
    }
}
