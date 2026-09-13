package com.siming.mobile.data.agent

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal const val MAX_NATIVE_TOOL_NAME_REJECTIONS = 3

internal data class MobileNativeToolNameRejection(
    val results: List<JsonObject>,
    val recoveryFits: Boolean,
    val failure: MobileConversationContextException,
)

/** Only called after category/terminal batch validation. No business call is admitted here. */
internal fun rejectMobileUnopenedToolBatch(
    assistantPayload: JsonObject,
    orderedToolNames: List<String>,
    offeredToolNames: Set<String>,
    requestBudget: MobileRequestBudgetEnvelope,
    rejectionCount: Int,
): MobileNativeToolNameRejection? {
    val unavailable = orderedToolNames.filterNot(offeredToolNames::contains).distinct()
    if (unavailable.isEmpty()) return null
    val rawCalls = validateMobileNativeAssistantCalls(assistantPayload, orderedToolNames)

    fun results(retryable: Boolean) = orderedToolNames.map { tool -> buildJsonObject {
        put("tool", tool)
        put("status", "error")
        put("detail", "本批次含有当前未开放的工具，所有调用均未执行。请根据本步骤实际提供的工具名称与" +
            "参数 Schema 重新选择调用；需要其他能力时单独调用 set_tool_categories。" +
            "不要猜测工具别名，也不要把同批其他调用当作已成功。")
        put("data", buildJsonObject {
            put("reason", "native_tool_not_open")
            put("unavailable_tools", JsonArray(unavailable.map(::JsonPrimitive)))
            put("available_tools", JsonArray(offeredToolNames.sorted().map(::JsonPrimitive)))
            put("batch_call_count", orderedToolNames.size)
            put("executed", false)
            put("retryable", retryable)
        })
    } }
    val provisional = results(true)
    val messages = buildJsonArray {
        add(assistantPayload)
        rawCalls.zip(provisional).forEach { (call, result) -> add(buildJsonObject {
            put("role", "tool")
            put("tool_call_id", (call.getValue("id") as JsonPrimitive).content)
            put("content", mobileCanonicalJson(result))
        }) }
    }
    val canContinue = rejectionCount < MAX_NATIVE_TOOL_NAME_REJECTIONS &&
        mobileCanonicalJson(messages).toByteArray(Charsets.UTF_8).size <= requestBudget.toolTransactionBudgetTokens
    return MobileNativeToolNameRejection(
        results = if (canContinue) provisional else results(false),
        recoveryFits = canContinue,
        failure = MobileConversationContextException(
            MobileConversationContextErrorCode.PROTOCOL_INVALID,
            "模型调用了当前未开放的工具 ${unavailable.first()}，本批次未执行。" +
                if (rejectionCount >= MAX_NATIVE_TOOL_NAME_REJECTIONS) "已用完本轮两次自动修正机会。" else "",
        ),
    )
}
