package com.siming.mobile.data.agent

/**
 * Persists a rejected native batch before applying its terminal admission policy.
 *
 * A rejected assistant transaction has not been shown back to the provider,
 * so it must stay DELIVERED across the thrown turn error.  The next successful
 * provider step is the only place that may mark it consumed and create receipts.
 */
internal suspend fun persistRejectedMobileNativeToolBatch(
    conversationStore: MobileAssistantConversationStore,
    projectId: String,
    turnContext: MobileAssistantTurnContext,
    transaction: MobileToolTransaction,
    recoveryFits: Boolean,
    terminalError: MobileConversationContextException,
    afterPersist: suspend (MobileTurnToolRuntimeState) -> Unit,
): MobileTurnToolRuntimeState {
    val runtime = conversationStore.recordDeliveredToolTransaction(
        projectId = projectId,
        turnContext = turnContext,
        transaction = transaction,
    )
    afterPersist(runtime)
    if (!recoveryFits) {
        throw terminalError
    }
    return runtime
}
