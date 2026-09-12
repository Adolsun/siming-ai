# 立项开篇细纲正文与卷归属修复

问题发生在生成、保存和正式建书的契约衔接处。模型把内容放在 goal、key_events、chapter_hook 等字段，旧校验仍接受空 summary；正式建书只读取正文摘要字段，导致显示为空。PC 建书通过未要求模型输出的 parent_index 挂卷，缺失时成为根节点；手机端则把缺失值当成第一个卷，结果不一致。整个阶段再次生成时，PC 还会把旧章节集合盖回模型结果。

当前契约由 `backend/app/modules/creation/domain/opening_outline_contract.py` 定义，并随 PC 提示词契约导出给 Android。

- 章节与场景的 summary 必须为非空字符串。planned_summary 缺省时采用 summary，作者明确填写的详细计划正文保留。
- 每章必须有 client_id、chapter_number、title、volume_id。模型从本会话 volume_index 选择真实卷 ID；应用只检查 ID 是否有效及章序号是否处于该卷范围内。
- 场景在顶层 sections 中保存，通过 parent_client_id 关联章节。默认第 1 至 3 章，每章 2 至 6 个连续编号的场景；既有 15 章窗口沿用相同校验。
- 不再补造缺失章节、正文、场景元数据，或接受 parent_index、parent_title、嵌套 sections/scene_outline。模型输出不符合契约时，由同一模型修正一次；仍无效则保留原资料并返回字段路径。
- 保存、确认、撤销检查点、版本恢复和建书均检查结构与当前卷归属。REST 确认失败不会把生成任务标记为已确认。
- 整阶段生成开篇细纲时采用新章节与新场景；首次生成章或场景实体时同时初始化完整阶段。锁定字段不能被整阶段生成覆盖。
- 正式建书使用“立项卷 ID → 正式卷 ID”和“章节 client_id → 正式章节 ID”的映射。卷排序不决定归属。保留章目标、关键事件、章末钩子、建议字数及场景元数据。

手机端在本地生成、校验全部大纲记录后才开始保存正式作品。未建立 PC 会话的本地卷没有服务端 UUID，因此本地实体 ID 使用会话 ID 与规范化卷内容的指纹；调整卷数组顺序不会改变 ID，修改卷内容会改变 ID 并使下游细纲过期。转交 PC 建书时，把本地 ID 作为显式传输 client_id，再根据 PC 返回的 volume_index 转换成 PC 实体 ID，不按卷名或数组顺序匹配。

回归用例使用合成资料，覆盖三章九场景、跨卷章节、卷顺序调整、空正文、对象冒充文本、错误实体类型、外部会话 ID、失效卷 ID、孤立场景、模型修正成功与失败、确认失败保持任务状态，以及 PC/Android 正式建书后的正文和补充字段保留。共享数据在 `contracts/fixtures/creation_opening_outline.json`。

验证结果：338 项后端回归测试通过；55 项 Android 立项测试及 lintDebug 通过；27 项 PC/手机能力一致性检查通过；后端架构、提示词编译与预算、Ruff 规定范围和 4 项导入契约检查通过。

验证命令：

```powershell
# 仓库根目录；测试数据库由 conftest 使用独立临时目录。
$creationTests = @(rg --files backend/tests | Where-Object { $_ -match 'test_.*creation.*\.py$' })
backend\.venv\Scripts\python.exe -m pytest $creationTests backend/tests/test_tool_result_projection.py backend/tests/test_mobile_prompt_contract.py backend/tests/test_mobile_pc_parity_contract.py -q
backend\.venv\Scripts\python.exe scripts/check-mobile-pc-parity.py

# backend 目录
.venv\Scripts\python.exe scripts/run_quality.py

# mobile/android 目录；使用项目配置的 JDK/SDK。
.\gradlew.bat :app:testDebugUnitTest --tests 'com.siming.mobile.data.creation.*' :app:lintDebug --offline --console=plain
```

本次修复不改动本机现有小说或已完成的立项数据，也不自动从人物目标等字段拼造缺失细纲。已有空内容章节不会因为代码升级自动恢复。

2026-09-12 随后按用户要求重新构建 Windows 安装包，版本保持 3.3.16：`release/Siming-Setup.exe`，42,579,612 字节，SHA256 为 `717cf37fa9424a8e30135c07dfea47f421247e68e2611cb0e620c10bf114258e`。安装包校验通过；打包后的 MCP 冒烟检查通过，注册 153 个工具。

另用打包后的 `Siming.exe`、隔离数据库和本地合成模型响应完成实际生成到正式建书的回归：首次返回空正文及缺失卷 ID 时，同一模型修正一次后保存三章九场景；调整两卷顺序后，各章仍挂在原指定卷下；正式建书保留章节、场景正文及章末钩子；两次空正文或外部卷 ID 的写入被拒绝，资料和 revision 均未变化。验证记录位于 `.build/packaged-opening-outline-result.json`，构建日志位于 `.build/windows-installer-build.log`。没有替换正在运行的程序。
