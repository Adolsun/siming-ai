from pathlib import Path


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    start_at = text.index(start)
    end_at = text.index(end, start_at)
    return text[:start_at] + replacement.rstrip() + "\n\n" + text[end_at:]


agent_path = Path("mobile/android/app/src/main/java/com/siming/mobile/data/creation/MobileCreationAgent.kt")
agent = agent_path.read_text(encoding="utf-8")
if "import kotlinx.coroutines.CancellationException\n" not in agent:
    agent = agent.replace(
        "import java.util.UUID\n",
        "import java.util.UUID\nimport kotlinx.coroutines.CancellationException\n",
        1,
    )
agent = replace_between(
    agent,
    "    suspend fun interview(\n",
    "    suspend fun generateStage(\n",
    '''    suspend fun interview(
        source: JsonObject,
        answer: String?,
        skip: Boolean,
        config: DirectApiConfig,
    ): JsonObject {
        val draft = source.objectValue("draft")
        val existingInterview = draft.objectValue("interview")
        val history = (existingInterview["history"] as? JsonArray).orEmpty().toMutableList()
        val pending = existingInterview["pending_question"] as? JsonObject
        if (!answer.isNullOrBlank() && pending != null) {
            history += buildJsonObject {
                put("question", pending.string("question"))
                put("answer", answer.trim())
            }
        }
        val historyArray = JsonArray(history)
        if (skip || history.size >= contract.interviewMaxTurns) {
            return withInterview(
                source,
                historyArray,
                status = if (skip) "skipped" else "completed",
                reason = if (skip) "用户要求跳过采访并直接生成方案。" else "动态采访已达到安全轮次上限，使用现有回答进入方案生成。",
                model = config.model,
            )
        }

        val (system, user) = contract.interviewMessages(source, historyArray)
        val interviewExtraBody = if (config.isDeepSeek()) buildJsonObject {
            put("thinking", buildJsonObject { put("type", "disabled") })
        } else null
        var raw = ""
        val decision = try {
            raw = directApi.complete(
                config,
                system,
                user,
                maxOutputTokens = 900,
                temperature = 0.6,
                extraBody = interviewExtraBody,
            )
            try {
                MobileCreationInterviewReliability.parseDecision(raw, historyArray)
            } catch (initialError: MobileInterviewDecisionException) {
                if (!initialError.repairable) throw initialError
                val retryUser = MobileCreationInterviewReliability.retryUserPrompt(
                    user,
                    raw,
                    initialError.message.orEmpty(),
                )
                raw = directApi.complete(
                    config,
                    system,
                    retryUser,
                    maxOutputTokens = 900,
                    temperature = 0.0,
                    extraBody = interviewExtraBody,
                )
                MobileCreationInterviewReliability.parseDecision(raw, historyArray)
            }
        } catch (error: CancellationException) {
            throw error
        } catch (error: Exception) {
            val failure = MobileCreationInterviewReliability.failure(error, raw)
            return withInterview(
                source,
                historyArray,
                status = "failed",
                reason = failure.message,
                model = config.model,
                failure = failure,
            )
        }

        return when (decision.string("action")) {
            "generate" -> withInterview(
                source,
                historyArray,
                status = "completed",
                reason = decision.string("reason").ifBlank { "模型判断信息已足够。" },
                model = config.model,
            )
            "ask_more" -> withInterview(
                source,
                historyArray,
                status = "awaiting_answer",
                reason = decision.string("reason"),
                model = config.model,
                pendingQuestion = decision["question"] as? JsonObject
                    ?: error("动态采访规范化结果缺少问题"),
            )
            else -> error("动态采访规范化结果缺少有效决策")
        }
    }''',
)
agent = replace_between(
    agent,
    "    private fun withInterview(\n",
    "    private fun writeStage(\n",
    '''    private fun withInterview(
        source: JsonObject,
        history: JsonArray,
        status: String,
        reason: String,
        model: String,
        pendingQuestion: JsonObject? = null,
        failure: MobileInterviewFailure? = null,
    ): JsonObject = updateDraft(source) { draft ->
        draft["interview"] = buildJsonObject {
            put("mode", "dynamic_model")
            put("status", status)
            put("history", history)
            put("pending_question", pendingQuestion ?: JsonNull)
            put("model", model)
            put("reason", reason)
            if (failure != null) {
                put("failure_class", failure.failureClass)
                put("next_action", failure.nextAction)
                put("error_message", failure.message)
                if (failure.rawResponsePreview.isNotBlank()) {
                    put("raw_response_preview", failure.rawResponsePreview)
                }
            }
            put("updated_at", Instant.now().toString())
        }
    }''',
)
agent_path.write_text(agent, encoding="utf-8")


repo_path = Path("mobile/android/app/src/main/java/com/siming/mobile/data/SimingRepository.kt")
repo = repo_path.read_text(encoding="utf-8")
repo = replace_between(
    repo,
    "    suspend fun advanceCreationInterview(\n",
    "    suspend fun generateCreationStage(\n",
    '''    suspend fun advanceCreationInterview(
        sessionId: String,
        answer: String? = null,
        skip: Boolean = false,
    ): JsonObject {
        val current = loadCreationSession(sessionId)
        val route = creationRoute(current)
        val gatewayExecution = creationHost(current) == CREATION_HOST_GATEWAY
        val updated = when {
            route == CreationExecutionRoute.Pc || gatewayExecution -> {
                val connection = requireConnection()
                val history = interviewHistoryWithAnswer(current, answer)
                val mobileProvider = if (route == CreationExecutionRoute.MobileKey) {
                    mobileProviderPayload(connection, sessionId)
                } else {
                    null
                }
                api.advanceNovelCreationInterview(
                    connection,
                    sessionId,
                    buildJsonObject {
                        put("user_brief", current.string("user_brief"))
                        put("qa_history", history)
                        put("skip_questions", skip)
                        put("model_route", if (mobileProvider == null) "pc" else "mobile")
                        mobileProvider?.let { put("mobile_provider", it) }
                    },
                )
                tagCreationRoute(
                    api.getNovelCreationSession(connection, sessionId),
                    route,
                    CREATION_HOST_GATEWAY,
                )
            }
            else -> tagCreationRoute(
                mobileCreationAgent.interview(
                    current,
                    answer,
                    skip,
                    resolvedDirectConfig(),
                ),
                route,
                CREATION_HOST_DEVICE,
            )
        }
        saveCreationSession(updated)
        val interview = updated.draft().objectValue("interview")
        if (interview.string("status") == "failed") {
            error(
                interview.string("error_message").ifBlank {
                    "动态采访失败；回答已保留，请发送“继续”重试。"
                },
            )
        }
        return updated
    }''',
)
repo_path.write_text(repo, encoding="utf-8")


screen_path = Path("mobile/android/app/src/main/java/com/siming/mobile/ui/CreationScreen.kt")
screen = screen_path.read_text(encoding="utf-8")
screen = screen.replace('                        answer = ""\n', "", 1)
screen = replace_between(
    screen,
    "@Composable\nprivate fun InterviewCard(\n",
    "@Composable\nprivate fun StageCard(\n",
    '''@Composable
private fun InterviewCard(
    interview: JsonObject,
    answer: String,
    onAnswerChange: (String) -> Unit,
    running: Boolean,
    onSubmit: () -> Unit,
    onSkip: () -> Unit,
    onStart: () -> Unit,
) {
    val pending = interview["pending_question"] as? JsonObject
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFFFBF2)),
        border = BorderStroke(1.dp, Color(0xFFE8D7C4)),
        shape = RoundedCornerShape(22.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(color = SimingCinnabar, shape = CircleShape) {
                    Icon(Icons.Outlined.AutoAwesome, null, tint = Color.White, modifier = Modifier.padding(9.dp).size(18.dp))
                }
                Spacer(Modifier.width(10.dp))
                Column {
                    Text("AI 策划编辑", fontWeight = FontWeight.Bold)
                    Text("一次只问真正会改变故事的问题", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (interview.string("status") == "failed") {
                Text("刚才的回答已经保存", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                Text(
                    interview.string("error_message").ifBlank { "模型没有完成本轮判断。" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    interview.string("next_action").ifBlank { "请发送“继续”重试。" },
                    style = MaterialTheme.typography.bodySmall,
                    color = SimingCinnabar,
                )
                Button(onClick = onStart, enabled = !running, modifier = Modifier.fillMaxWidth()) {
                    Text("继续判断")
                }
            } else if (pending == null) {
                Text("我会先读你的完整构想，再决定是追问一个关键分岔，还是直接开始生成。", lineHeight = 23.sp)
                Button(onClick = onStart, enabled = !running, modifier = Modifier.fillMaxWidth()) {
                    Text("开始 AI 采访")
                }
            } else {
                Text(pending.string("question"), fontSize = 19.sp, fontWeight = FontWeight.SemiBold, lineHeight = 27.sp)
                if (pending.string("purpose").isNotBlank()) {
                    Text("为什么问：${pending.string("purpose")}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                OutlinedTextField(
                    value = answer,
                    onValueChange = onAnswerChange,
                    label = { Text("像聊天一样回答") },
                    placeholder = { Text("不需要术语，把你真正想要的感觉说出来即可") },
                    minLines = 3,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(16.dp),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                    OutlinedButton(onClick = onSkip, enabled = !running, modifier = Modifier.weight(1f)) {
                        Text("信息够了，生成")
                    }
                    Button(onClick = onSubmit, enabled = answer.isNotBlank() && !running, modifier = Modifier.weight(1f)) {
                        Text("回答并继续")
                    }
                }
            }
        }
    }
}''',
)
screen_path.write_text(screen, encoding="utf-8")
