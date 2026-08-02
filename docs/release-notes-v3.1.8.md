# Siming 3.1.8

Siming 3.1.8 是对话式立项优化计划的收口版本。它把作品助手也接入统一持久会话入口，并补齐计划中约定的类型化立项工具，使聊天、结构化数据和持久任务具备一致、可查询的控制契约。

## 主要变化

- 系统、立项和作品对话统一使用带 `scope_type`、`scope_id` 的持久会话列表与消息生命周期；作品助手每轮消息会即时保存，完成、失败或取消状态均可刷新恢复。
- 修复启动时项目列表尚未加载便清除已保存作品选择的竞态，刷新后可稳定恢复原作品与对应会话。
- 新增 `get_creation_session`、`get_creation_snapshot`、`get_creation_operation` 和 `patch_creation_session`。
- 新增 `confirm_creation_artifact`，确认当前内容不会隐式生成当前或下一对象。
- 新增 `generate_creation_artifact`、`refine_creation_artifact`、`regenerate_creation_artifact`，支持 artifact 或实体级定向运行，并复用 revision、锁定字段和持久 Run 保护。
- 新增 `cancel_creation_operation`、`pause_creation_operation`、`resume_creation_operation`、`retry_creation_operation`，直接连接统一 Operation 控制面。
- 新增 `validate_creation_session` 与 `finalize_creation_session`；正式创建项目前执行依赖、stale 与引用一致性校验，创建操作保持幂等。
- 工作区工具注册表扩展到 193 项，并补充 MCP 暴露、revision 冲突和统一作品会话测试。

## 升级说明

- 新增 `300a9_canonical_conversation_bridge` 非破坏性迁移，为作品助手内部执行线程增加规范会话映射；升级后同一作品会话会稳定复用后台执行上下文。
- Android 版本为 `3.1.8`，`versionCode` 为 `30108`，与桌面版本一致。
