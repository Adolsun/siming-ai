# 本机 CLI 建档候选空转控制

> 历史排查记录：文中的旧建档阶段和工具仅说明当时行为；现行流程见[统一建档计划](../agent/external-no-api-cataloging.md)。

## 问题与改动

建档 CLI 原先主要依据输出、CPU 和工具事件判断活跃，连续提交不合法或重复候选也能维持运行。候选阶段现在增加一个跨工具类别切换共享的业务进度探针：

- 读取真实候选内容、状态与目标 ID，不以时间戳、模型输出、读取工具或类别切换刷新保存进度。
- 检测到连续三次无效候选提交时，终止本轮 CLI 进程树；合法保存重置提交失败计数。
- 连续 600 秒没有候选保存变化时停止，即使模型仍在输出。该时限仅用于候选阶段，不限制长篇事实提取。
- 最近校验错误或缺失覆盖项进入原有失败持久化路径，任务进入 paused_on_failure，保留事实、候选，不自动重开同一失败回合。
- 已完成检查点、作者暂停优先；自动应用中间状态不作为完成终止条件。审计晚于数据库提交到达时不会误算失败。

没有替模型推断实体、合并别名、拆分自然语言字段或放宽工具参数校验。模型仍可能返回不合规参数；本次修复约束由此产生的空转，并保留诊断信息。

## 验证

全部离线，无真实模型调用：

- test_cataloging_cli_progress.py、test_local_cli_cataloging_agent.py、test_cataloging_static_audit.py：45 passed。
- test_external_cataloging_tools.py、test_external_cataloging_apply.py、test_cataloging_retry_feedback.py：33 passed。
- 覆盖持续 stdout 输出的子进程被业务探针终止、重复提交、类别切换、保存进展恢复预算、提交后审计延迟、检查点与候选保留。
- check-mobile-pc-parity.py：27 项能力契约检查通过。本次仅修改 PC 本机 CLI 进程监管；共享建档 API 和工具参数契约不变。手机端独立完整建档仍是现有能力缺口，此检查不代表该流程已实现。
- git diff --check 通过。

当前工作区代码已修复；本次未安装或启动新版本，也未恢复作者暂停的任务。
