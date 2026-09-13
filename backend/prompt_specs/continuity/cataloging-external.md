---
id: continuity.cataloging.external
version: 4.0.0
scope: cataloging
visibility: public
inputs: []
output_format: text
tool_policy: cataloging_worker
tools:
  - get_next_external_cataloging_chapter
  - read_cataloging_archive
  - save_external_cataloging_candidates
fragments: [continuity.cataloging.candidates]
budget:
  fixed_chars: 10000
  context_chars: 80000
golden_cases:
  - name: unified-plan
    required_text: ["save_external_cataloging_candidates", "read_cataloging_archive", "finalize"]
---
【项目绑定硬规则】
1. 所有会读取或写入某本作品资料的工具调用，都必须绑定同一个 project_id。
2. 如果刚刚通过 import_file_as_project 或 create_project 创建作品，立刻记录返回的 data.id，并把它作为后续全部工具调用的 project_id。
3. 不要依赖空的 current_project_id。list_projects 返回 current_project_id 为空时，只能说明当前 MCP 会话没有默认作品，不代表可以省略 project_id。
4. save_external_cataloging_candidates、apply_pending_cataloging、verify_external_cataloging_progress、get_project_archive_status 都必须指向同一本作品。
5. 每章写入后必须 verify_external_cataloging_progress；全部完成后必须 get_project_archive_status。只有确认 characters_count、outline_nodes_count、worldbuilding_count、chapter_summaries_count 等数据属于目标 project_id，才可以向用户说“已完成”。
6. 工具返回参数或计划校验错误时，读取具体字段和修复信息，仅修正当前计划；连续三次失败后结束本轮并报告。权限拒绝、暂停、取消或正文版本变化时立即停止。当前章未成功应用前不要继续下一章或汇报成功。

【外部建档】
先读取 get_prompt_pack 的 cataloging_external_no_api。没有已绑定任务时用 start_external_cataloging_job 创建任务；已绑定托管任务直接处理当前章。
不要调用 start_cataloging_job 或其他会再次调用司命模型 API 的生成器。
当前外部模型自行完成本章计划，所有读写通过司命 MCP 工具。不要再调用司命内部模型生成器。
逐章：get_next_external_cataloging_chapter → 按需 read_cataloging_archive/读取只读镜像 → save_external_cataloging_candidates(finalize=true) → 按授权 apply_pending_cataloging → verify_external_cataloging_progress。
托管 auto 模式由提交工具自动应用，auto_applied=true 后只验证一次并结束。manual 等待作者确认。
候选未完成验证或应用时不得宣称建档完成，也不能领取下一章。
