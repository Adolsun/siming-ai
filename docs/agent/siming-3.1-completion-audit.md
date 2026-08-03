# Siming 3.1 对话式立项完成审计

> 范围：用户给出的 3.1.0、3.1.x，以及原先列入 3.2.0 的全部立项需求。
>
> 版本策略：全部能力在 3.1.x 内完成；`schema_version = 3` 是数据协议版本，不代表另开 3.2 产品版本。
>
> 当前本地测试候选版本：3.1.12。界面验收由产品负责人直接完成；在明确确认上传前，不创建或发布正式 Release。

## 需求到证据矩阵

| 需求 | 当前实现证据 | 自动化验收证据 | 状态 |
|---|---|---|---|
| P0-1 统一任务状态 | `operations/domain/state.py`；`novel_creation_runs.py`；创建任务 SSE | `test_completed_generation_waits_for_author_confirmation`、`test_restart_releases_interrupted_creation_run_for_retry`、`test_waiting_user_operation_survives_restart_as_author_attention` | 已验证 |
| P0-2 助手消息即时持久化 | `assistant/infrastructure/models.py` 的 `run_id`、`operation_id`、`message_type`、`payload_json`、`status`；系统助手运行时 | `test_system_turn_persists_running_placeholder_before_completion`、`test_running_system_message_is_interrupted_after_restart` | 已验证 |
| P0-3 数据库级幂等 | `NovelCreationRunClaim`；迁移 `300a5_creation_claims.py`；创建/重试 API | `test_creation_claim_replays_identical_stage_command`、`test_database_rejects_two_active_claims_for_one_artifact`、`test_duplicate_running_concept_request_reuses_existing_run` | 已验证 |
| P0-4 取消、暂停、恢复 | Operation action API、检查点恢复、重启扫描、写入前取消栅栏 | `test_creation_run_supports_durable_pause_and_checkpoint_resume`、`test_durable_cancellation_after_model_return_never_saves_stage_data`、`test_operation_cancel_stops_producer_and_marks_run_cancelled` | 已验证 |
| P0-5 确认语义拆分 | `confirm`、`confirm-and-generate-recommended`、独立生成 API；明确按钮文案 | `test_repeated_confirmation_is_idempotent_for_the_same_content`、`test_repeated_confirm_and_generate_replays_one_recommended_run`、`NovelCreationWizardPage.test.tsx` | 已验证 |
| P1-1 助手内嵌立项会话 | `GuiAssistantChat` 的会话恢复、立项数据侧栏、完整编辑器入口 | `keeps structured creation data visible beside the conversation and confirms it in place`；对应 Playwright 多视口用例 | 已验证 |
| P1-2 类型化立项工具集 | creation tool registry、`creation/domain/tool_specs.py`、MCP 暴露 | `test_tool_spec_catalog.py`、`test_mcp_novel_creation_tools.py`；所有立项工具拒绝 Legacy 输入 | 已验证 |
| P1-3 依赖提示与 stale | `SOFT_DEPENDENCIES`、`IMPACT_DEPENDENCIES`、artifact 流程投影 | `test_generation_uses_soft_dependency_hints_instead_of_fixed_stage_blockers`、`test_artifact_dependencies_keep_existing_downstream_data_visible` | 已验证 |
| P1-4 自然语言局部修改 | 对话确定性命令、结构化 Patch、锁定校验、revision CAS、影响摘要 | `test_artifact_patch_is_atomic_and_reports_downstream_impact`、`test_artifact_locks_block_parent_and_child_patch_paths`、定向聊天与实体测试 | 已验证 |
| P1-5 长文本/文件导入 | 持久导入任务、原文件、分块、预览、选择应用、来源字段 | `test_novel_creation_imports.py` 覆盖 txt/md/docx/json、3 万字、检查点、幂等、冲突和来源 | 已验证 |
| P1-6 四级结构恢复 | 直接解析、确定性 JSON 修复、同模型结构修复、安全草稿和诊断原文 | `test_truncated_stage_json_is_repaired_without_a_second_model_call`、`test_invalid_json_is_repaired_once_and_refine_failure_keeps_current_concepts`、安全草稿测试 | 已验证 |
| 3.2 原范围：数据对象化 | `NovelCreationEntity`、实体同步、软删除、实体锁 | `test_legacy_artifacts_project_to_independent_entities_with_stable_ids`、`test_entity_delete_is_soft_and_locked_entity_patch_is_rejected` | 已在 3.1.x 实现 |
| 3.2 原范围：地点/势力独立存储 | locations artifact 到 location/faction 实体投影 | `test_dependency_graph_covers_artifacts_entities_and_references`、实体投影测试 | 已在 3.1.x 实现 |
| 3.2 原范围：会话 scope 统一 | 系统会话支持 `system`、`creation`、`project` scope | `test_conversation_scope_can_follow_creation_and_project_contexts`、项目会话前端恢复 E2E | 已在 3.1.x 实现 |
| 3.2 原范围：版本差异与历史恢复 | `NovelCreationArtifactVersion`、不可变历史、diff、restore、expected revision | `test_artifact_history_is_immutable_and_not_limited_to_three_checkpoints`、`test_version_diff_and_restore_keep_the_newer_state_in_history`、前端历史测试/E2E | 已在 3.1.x 实现 |
| 3.2 原范围：实体级生成 | run 的 `entity_id`/`entity_type` 目标及只替换选定实体 | `test_entity_target_generation_runs_end_to_end_without_rewriting_siblings` | 已在 3.1.x 实现 |
| 3.2 原范围：依赖图与一致性 | artifact/entity/reference 通用图、稳定问题代码、只读校验 | `test_novel_creation_consistency.py` | 已在 3.1.x 实现 |

## 作者优先与异常恢复不变量

- 旧 revision 任务不得覆盖作者的新修改；冲突候选保存在 run 结果中，artifact 投影为 `conflict`。
- “按原输入重试”和“按最新内容重试”冻结不同 revision/snapshot，并保留明确 `retry_mode`。
- 取消后的模型返回不能进入最终写入；重启后的无执行器任务转为 `interrupted` 并释放 active claim。
- 非法模型输出不能覆盖已确认原稿；修复方式、警告和原始回复进入诊断数据。
- `waiting_user` 停止 SSE 等待，隐藏暂停/取消，保留审阅和调整入口。

对应证据：`test_long_stage_save_uses_revision_cas_and_preserves_manual_edit`、`test_retry_uses_the_selected_original_or_latest_input_snapshot`、`test_durable_cancellation_after_model_return_never_saves_stage_data`、`test_repaired_model_reply_is_kept_in_full_diagnostics_only`，以及前端冲突/双重试测试。

## 3.1.10 额外回归项

- DeepSeek V4 Flash/Pro：开放式聊天保留思考并读取 `reasoning_content`；只有思考没有最终正文时，同模型无思考补偿重试一次；短 JSON 判断默认无思考。
- 任务中心：红点代表未读提醒，可一键清零；历史待处理任务不删除；最近活动显示本地绝对时间。
- Gateway：前端构建固定运行于 `$BUILDPLATFORM`，最终 Python 镜像仍按 `$TARGETPLATFORM` 生成，避免 arm64 QEMU 执行 npm。

## 3.1.11 额外回归项

- 创意方向只生成一套，并允许作者通过聊天持续调整；旧蓝图入口同步为单方案。
- AI 助手单条消息上限提高到 1,000,000 字符，超过 20,000 字符的立项文本进入持久化分块导入。
- 已保存 API 密钥可用于模型发现与连接测试；OpenCode 模型由司命运行 `opencode models` 获取。
- 模型标识上限从 100 提高到 512 字符；任务时间携带 UTC 偏移并按用户本地时区显示绝对时间。

## Release Gate（尚未完成前不得发布）

- [x] 后端全量测试（1597 项）及 87 项模型配置边界回归。
- [x] 前端全量单元测试、lint、质量检查、API schema 检查和生产构建。
- [x] Playwright 全量 E2E（34 项）；1920×1080 与 800×600 实际界面复审及截图。
- [x] 本机运行 `opencode models` 并获取 7 个实际可用模型。
- [x] Windows `Siming.exe` 重新打包、启动烟测、版本/update.json/SHA-256 一致。
- [x] Android 单测、lint、Debug/Release 构建和模拟器安装复审通过；签名 APK 由标签 Release Gate 使用仓库密钥生成。
- [ ] Gateway amd64/arm64 镜像构建和非 root、可写数据烟测。
- [ ] 提交并推送；GitHub Release 上传经验证资产；发布匹配的多架构 Gateway 镜像。
