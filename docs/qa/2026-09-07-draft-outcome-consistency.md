# 章节草稿成功后误报资料提交失败

## 真实问题与结论

用户运行 `779c5158-b200-4b23-a3f5-9670bbcb3614` 已生成第42章《把钟摆回原处》，却收到“工具执行失败，相关数据可能未保存：submit_context_evidence 等待确认”。

只读检查原数据库得到以下顺序：

| 模型步骤 | 工具 | 结果 |
| --- | --- | --- |
| 11 | `submit_context_evidence` | `needs_confirmation`；一个 `source_id` 被填入 `item_id`，未能匹配已验证检索结果 |
| 12 | `submit_context_evidence` | `ok`；正确引用检索结果，6条资料通过，同一个上下文清单 |
| 13—18 | `prepare_task_context` | 分页交付已选上下文 |
| 19 | `chapter_writer` | `ok`；草稿已持久暂存，回合结束 |

草稿ID为 `309e289a-d0cf-4e72-9814-580b7d43569a`，状态 `pending`，`saved_chapter_id` 为空。正文共3471个字符（含标点等，不等同于汉字数），仍等待作者保存。原数据库的消息不包含用户粘贴中的反斜杠和 `&#x20;`。

根因在最终汇总：草稿识别名单只含 CLI 的两个 `save_external_*_draft`，遗漏 API 的 `chapter_writer`、`outline_writer`。因此 API 已完成的上下文前置步骤仍被计为未解决问题。另外，汇总将 `needs_confirmation` 与 `error` 混为一类，产生矛盾提示及错误的 `partial_success` 状态。这不是本次正文生成或正式章节写入失败。

## 本轮修改

- 从现有权威工具注册表读取终止工具与草稿产物契约，移除另一份按入口维护的工具名单。API、CLI 的章节及大纲草稿使用同一汇总逻辑。
- 只有完成状态、非空草稿ID及 `pending` 状态同时存在，才承认成功暂存；只有上下文清单回执存在，才认定此前的上下文前置检查已由草稿生成流程解决。
- 尚未解决的 `needs_confirmation` 显示“需要确认或调整”，结果为 `waiting_user`，不再声称工具失败或数据丢失。
- 真正的 `error`、`failed`、`interrupted` 仍产生失败或部分完成结果。成功生成草稿不会掩盖无关操作的错误。
- 最终提示不再重复打印两次工具名。过程日志仍保留首次退回和随后成功的事实，不删除历史记录。

未修改生成提示词、资料来源校验、字数约束、保存／建档权限、模型容量、用户草稿或正式项目数据。

## 验证

后端运行：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_workspace_assistant_outcome.py backend/tests/test_assistant_public_projection.py backend/tests/test_tool_execution_status.py backend/tests/test_ai_writer.py backend/tests/test_direct_mcp_run_steps.py backend/tests/test_outline_draft_generation.py backend/tests/test_agent_context_checkpoint_native_e2e.py backend/tests/test_assistant_run_contract.py backend/tests/test_task_context_delivery.py -q
```

193项通过。覆盖四种草稿工具、失败状态别名、资料提交退回后成功、仅有成功文案却没有草稿回执、就绪／阻塞状态、未解决的确认与真正失败同时存在，以及公开结果不泄露诊断信息。

此外，将原数据库以 SQLite `mode=ro` 和 `query_only` 打开，备份至独立目录，再调用真实 `finalize_workspace_assistant_turn` 重放本次完成阶段：

- 原结果 `partial_success` 改为 `completed_with_reply`；消息正文、消息载荷与运行记录中的最终回复一致。
- 已解决的前置校验显示“后续流程已纠正”，不再提示资料可能未保存。
- 对章节／大纲草稿、正式章节、大纲、角色、世界观、上下文清单和步骤审计表逐行计算摘要，重放前后完全一致。编辑器正文和过程日志也完整保留。
- 未调用模型；未对原数据库执行写入。隔离重放不等同于重新运行生成流程，也不是10万字小说的完整验收。

## 手机端检查

手机访问服务端时复用修复后的同一最终汇总。手机独立 API 路径在收到草稿事件后结束回合，并由本地会话存储记录未保存草稿结果；没有本次按 CLI 工具名单汇总错误的实现，因此不新增另一条手机业务路径。

本轮手机完整JVM测试282项通过，包含会话持久化、当前回合上下文、章节目标、独立大纲分页、请求契约和草稿保存状态；PC／手机27项能力契约检查通过。首次直接从中文路径启动Gradle时，测试工作进程无法加载测试类，尚未执行断言；改用已有构建脚本的临时ASCII路径映射后全量通过，没有修改或跳过测试。最终安装包证据见同名 `evidence` 文件。

## 测试提示

本修复作用于后续回合的最终汇总；用户已完成的历史消息保持原样，不批量改写审计记录。本次第42章草稿无需因该警告重新生成，是否修改、保存和建档仍由作者决定。

## 本地安装包

路径：`release/local-draft-outcome-fix-20260907/Siming-Setup.exe`。

版本3.3.13，本地未签名测试包，手动安装；未发布、未自动安装、未合并分支。

SHA-256：`020a4a79be4291bd7f107d919f783a6ca892ceb4c55f57fce8c8947b619ab0cc`；大小 42521987 字节。

已核对冻结后的 624 个后端模块与当前源码编译结果一致，包含本次最终汇总修复；前端及提示词文件也与构建输入一致。标准安装包MCP验收通过，额外冻结程序分页与长正文查询验证通过。验证均使用隔离数据，未访问或改动作者原项目。

上一份 `release/local-active-turn-fix-20260907/Siming-Setup.exe` 保留且SHA-256未改变。
