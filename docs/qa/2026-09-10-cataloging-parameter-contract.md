# 建档参数契约与同模型纠错

## 修复内容

此前候选工具仅导出任意对象数组，枚举、嵌套关联和数组字段主要依赖长提示词说明；部分提示词示例不完整。工具结果投影又遗漏 candidate_errors、coverage_repairs、scene_repair，使模型无法获得原值确认等具体修复数据。API JSONL 入口还存在按字段猜候选类型、按关系描述改候选类型、将世界观 category 映射到 dimension 的旧逻辑。

本次将候选字段结构集中到 continuity/domain/candidate_contract.py：

- MCP 和 API 工具导出同源 Schema，包含候选 type、角色 role_type、世界观 dimension、聚合 chapter_link、覆盖清单等字段结构。托管 CLI 的 maxItems=3 随进程作用域导出，和当前执行限制一致；未托管 API 的批量大小契约不变。
- API JSONL 在参数规范化前使用同一字段校验，拒绝字符串化数组、非法枚举和不合法嵌套结构，避免字段被默认为其他值或丢弃。
- 删除候选类型、关系类型和世界观维度的旧猜测分支及相应过时测试。无 type、非标准 type、把候选类别写进 node_type 的输出明确报错，由模型修正。保留合法 JSON/JSONL 的确定性传输解析。
- API 与 CLI 共用候选恢复上下文。API JSONL 下一请求携带完整已保存候选；MCP 先交付身份、覆盖清单及关联，再提供完整候选分页读取参数，避免每次重复整份档案正文。
- 修复信息进入模型可见结果；显式类型的联合 Schema 错误报告实际字段位置。提示词说明工具返回校验错误时也进入增量纠错，不再仅以新的用户消息触发。
- 删除矛盾的旧格式示例，改为可由实际工具 Schema 验证的原生 JSON 示例。
- 修复 API 整段响应恢复时校验异常跳出重试循环的问题；错误保留为 candidate_validation，合法候选保留，再交给同一模型修正。

既有事务、实体归属、真实 ID、来源证据、人工确认和自动应用边界继续生效。没有增设语义修复器或使用另一模型改写参数。

## 验证

均为离线测试，没有调用真实模型或修改作者作品数据：

- `pytest backend/tests -k cataloging`：414 passed。
- 工具 Schema、工具结果投影、架构、手机端契约专项：82 passed。
- 最后提示词调整后重新编译、导出手机契约并运行提示词及移动资产测试：32 passed。
- `check-mobile-pc-parity.py`：27 项能力契约通过；`git diff --check` 通过。

新增用例覆盖 MCP、API 工具、API JSONL 三个入口：非法角色枚举和字符串化数组均不写入，正确参数可保存；工具会交付 appearance_before 的真实修复原值；API Gateway 模拟首次非法、下一轮只提交修正候选，最终进入 awaiting_confirmation 且已保存候选 ID 不变。另覆盖 CLI 的真实批量限制导出、嵌套错误路径、禁止推断类型和维度。

手机端完整独立建档仍是原有能力缺口，本次没有将契约检查结果当作该功能已实现。当前已修复代码并打包，尚未安装；模型仍可能产生非法参数，系统提供明确契约和有界同模型纠错，无法承诺每次首次输出都合法。

## 测试安装包

- 路径：`release/local-cataloging-contract-20260910/Siming-Setup.exe`。
- 版本：3.3.13；大小：42,585,687 字节。
- SHA256：`ca7fa102467a69028cc3658bb77b488ad1650caa7847b8e36b761ba45ba83bc5`。
- 构建日志：`.build/cataloging-contract-installer-20260910.log`。
- 前端、PyInstaller 与 Inno Setup 构建成功；发布资源校验、打包后 MCP 冒烟测试（153 个工具）和 `verify-windows-installer.ps1` 校验通过。
- 包含本次参数契约与 API 纠错，以及前次 CLI 无持久化进展保护修复。未安装到用户机器，未恢复暂停的建档任务。
