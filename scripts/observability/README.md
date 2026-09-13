# 本地 API 交互可视化

使用源码可用的 [Phoenix](https://arize.com/docs/phoenix/self-hosting/deployment-options/terminal)
和 [OpenTelemetry](https://opentelemetry.io/docs/languages/python/instrumentation/)。
Phoenix 可展示明确导入的历史记录。产品中的新请求由司命原生调用查看器采集，不需要启动 Phoenix。
本目录只用于诊断，不进入安装包，不修改正式依赖锁和模型配置。

Phoenix 20.9.0 主体采用 [Elastic License 2.0](https://github.com/Arize-ai/phoenix/blob/main/LICENSE)，
OpenTelemetry 采集 SDK 采用 [Apache-2.0](https://github.com/open-telemetry/opentelemetry-python/blob/main/LICENSE)。
Phoenix 的本地使用、修改及分发须遵守 ELv2；分发时附带协议、保留声明并明确标注修改。
ELv2 限制向第三方提供开放其大量功能的托管服务。Phoenix 及其修改版不能统一标为司命的 Apache-2.0。

## 启动界面

在仓库根目录执行，推荐 Python 3.12：

```powershell
python -m venv .build/phoenix-venv
.build/phoenix-venv/Scripts/python.exe -m pip install -r scripts/observability/requirements.txt
pwsh -NoProfile -File scripts/observability/start_phoenix.ps1
```

界面：<http://127.0.0.1:6006>。打开项目、点击一条 trace，再展开左侧调用树：

- `LLM`：Input 是输入，Output 是模型输出；`Attributes` 可看 token、请求体大小和消息组成。
- `TOOL`：Input 是工具参数，Output 是工具执行器返回的结果。失败节点标红。
- 历史模型节点的 `output.value` 保留已保存的 `reasoning_content`，这是提供商返回的字段。
- 可以下载 span，或使用 Phoenix REST API 导出，用于后续上下文压缩效果比较。

数据与服务日志保存在 `.build/phoenix-data`（Git 忽略）。HTTP 6006 与 gRPC 4317
仅监听 `127.0.0.1`；不配置云端 collector，关闭遥测、联网资源和内置 AI 助手。
不要把这整个目录提交到仓库或上传到云服务。

Phoenix 20.9.0 有两个本地运行限制，由 `prepare_phoenix.py` 对隔离环境做可重复的安装修正：
Python 3.11 下三个 dataclass 默认值改用等价 factory；gRPC 固定监听回环地址。
脚本严格检查版本与源代码，版本不符会明确失败。它不修改司命代码或全局 Python。

## 导入已保存的立项记录

```powershell
.build/phoenix-venv/Scripts/python.exe scripts/observability/import_creation_history.py `
  --database '<司命数据库的绝对路径>' --message-id '<失败回合的 assistant message ID>'
```

导入器通过 SQLite `mode=ro` 读取，写入的是本地 Phoenix；项目名为
`siming-creation-history`。同一个消息使用确定性 trace/span ID，避免重复导入。

历史记录不是完整 API 请求：它包含本轮工具调用、工具返回、模型已保存的输出、部分 token
统计，但不包含当时完整系统提示词、之前回合的全部上下文和实际发送的工具 Schema。
页面的 Input 明确列出缺失项，不能把本轮记录的拼接结果当作原始请求。
根节点时间来自消息创建和更新时间；子节点时间仅用于排列调用顺序。
历史节点的 `0 ms` 表示耗时未知；费用未采集，Phoenix 显示的 `$0` 不能解释为免费。
报告的输入 token 包括可能命中缓存的输入，不等于实际计费金额；缺少的输出 token 不补零。

## 查看新请求

使用司命内置的“查看本轮调用”，从项目助手消息、立项会话、上下文治理或任务列表进入。
默认保存调用摘要；选择“完整记录 60 分钟”或“持续完整记录”后，再发起需要诊断的任务。
PC/Gateway 的记录保存在独立诊断 SQLite 库，Android 直连记录保存在手机独立 Room 库。
两端可以分页查看、清理和导出诊断 ZIP，不需要本目录的 Python 环境或外部服务。

原有 `live_capture.py` 与 `run_backend.py` 已随内置采集移除，避免维护第二条 HTTP monkeypatch 路径。
导出包目前用于离线检查；尚未提供原生 ZIP 到 Phoenix 的导入器或 OTLP 自动上传。
历史导入器继续只处理已保存的旧立项记录，缺失的原请求不会补造。

实现、采集边界及验收见 [内置查看器说明](../../docs/context-inspector-plan.md)。
CLI 只记录司命提供给进程的输入和进程实际暴露的输出；外部进程内的 API 交互不可见。
`reasoning_content` 只展示提供商实际返回的字段。

## 验证

```powershell
<后端Python> -m pytest backend/tests/test_context_trace_capture.py backend/tests/test_context_trace_contract.py -q
```

测试使用合成记录、临时数据库与 HTTP mock，不发送真实模型请求。
外部 Phoenix 的历史导入测试仍位于本目录，不影响安装版的原生采集实现。
