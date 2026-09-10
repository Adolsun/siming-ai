package com.siming.mobile.ui

import com.siming.mobile.data.MobileAssistantMessage
import com.siming.mobile.data.MobilePendingChapterDraft
import com.siming.mobile.data.parseApiDateTime

internal fun orderedAssistantMessages(messages: List<MobileAssistantMessage>): List<MobileAssistantMessage> = when {
    messages.all { it.sequenceNo != null } -> messages.sortedBy { it.sequenceNo }
    messages.all { parseApiDateTime(it.createdAt) != null } -> messages.sortedBy { parseApiDateTime(it.createdAt) }
    else -> messages // A partially ordered stream keeps its authoritative server/journal order.
}

internal fun MobileUiState.withAssistantHistory(
    conversationId: String,
    messages: List<MobileAssistantMessage>,
    context: MobileAssistantContextState?,
): MobileUiState = copy(
    assistantConversationId = conversationId,
    assistantMessages = orderedAssistantMessages(messages),
    assistantLiveTurnId = null,
    assistantCurrentPrompt = "",
    assistantCurrentStartedAt = "",
    assistantOutput = "",
    assistantReasoning = "",
    assistantToolLog = emptyList(),
    assistantContextState = context,
)

/** Invalidate late reads on saves, edits, project changes and newly generated drafts. */
internal class PendingChapterDraftRefreshGuard {
    private var generation = 0L
    data class Request(val generation: Long, val previous: MobilePendingChapterDraft?)

    fun begin(previous: MobilePendingChapterDraft?): Request = Request(++generation, previous)
    fun invalidate() { generation++ }
    fun accepts(request: Request, current: MobilePendingChapterDraft?): Boolean =
        request.generation == generation && current == request.previous
}
