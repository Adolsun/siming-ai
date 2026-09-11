# 本地 API 交互可视化

使用源码可用的 [Phoenix](https://arize.com/docs/phoenix/self-hosting/deployment-options/terminal)
和 [OpenTelemetry](https://opentelemetry.io/docs/languages/python/instrumentation/)。
Phoenix 展示模型请求、提供商响应、工具参数和结果；司命仍调用同一个业务执行器和原来的 API 地址。
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

## 采集新请求

给现有的后端开发/测试 Python 环境安装轻量 SDK（不要把 Phoenix 服务的依赖装入后端环境）：

```powershell
<后端Python> -m pip install -r scripts/observability/requirements-sdk.txt
<后端Python> scripts/observability/run_backend.py `
  --database '<测试数据库或明确选定的测试副本>' --port 8011
```

这是普通后端的诊断启动入口。它要求显式指定数据库，使用 `app.main:app` 的相同业务实现，
项目名为 `siming-api-live`。需要让测试前端连接此后端，再使用正常的模型配置发起测试。
已经运行的安装版和独立 Android 进程不会被自动附加采集。

采集在 HTTPX 异步发送边界执行，位于提供商参数适配之后：记录实际 JSON 请求体，
并旁路观察返回字节；不会更换 API 域名/路径，不使用代理，不额外调用模型。
OpenAI 兼容接口的 messages、tools、thinking，以及 JSON/SSE 响应字段可查看。
API 的原始返回与业务执行器返回分别保留，不把生成前的参数失败误记为提供商失败。
提供商未返回的隐藏内容无法采集。

HTTP 头和 URL 查询串不采集；显式凭据字段会替换为 `[REDACTED]`。
每次请求/响应采集上限 16 MiB，超限标记 `*_capture_truncated`，不截断实际 API 数据。
流式 gzip/deflate 会解码；其他压缩类型标记 `response_decoding`，不可视为完整可读响应。
关闭/取消的流标记真实状态，不把部分响应当成完整响应。
CLI 外部进程和 Android 独立请求不经过此 Python 入口，需要各自接入同一 OTLP 协议，不能冒充已覆盖。

## 验证

```powershell
<后端Python> -m pytest scripts/observability -q
```

测试使用 HTTPX MockTransport，不发送真实提供商请求、不消耗模型 token。覆盖：
DeepSeek 适配器的请求地址/请求体、思考字段、工具调用、gzip 分块响应、400 响应、取消、
本地 collector 限制，以及历史导入不改数据库、不伪造请求/耗时/token。
额外后端服务的启动验证被自动审批拦截，改用进程内 ASGI 请求验证：调用真实工具执行器，
核对父子 trace、引用错误和数据库 revision 均正确。不能把模拟验证表述为已经附加到正在运行的安装版。

后续比较压缩策略时，优先统计真实请求的消息/工具组成、输入与缓存用量、失败和重试次数，
再比较相同任务的完成率、状态和写入结果。当前变更不新增上下文压缩策略。
