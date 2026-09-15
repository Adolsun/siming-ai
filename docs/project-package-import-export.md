# 司命项目包协议与导入导出

司命项目包是作者数据的显式、版本化交换格式，不是数据库快照，也不是通用小说文档。普通 TXT、Markdown、DOCX 走“导入外部小说”；只有 `.siming-project` 可以进入项目包导入路径。

## 权威接口

```text
POST /api/v1/projects/{project_id}/project-package/export?profile=full|structure
POST /api/v1/projects/project-package/import
```

导入使用 multipart：

- `file`：必填，文件名必须以 `.siming-project` 结尾。
- `new_title`：可选，最多 200 字符。
- `Idempotency-Key`：必填请求头，必须是 UUID。

导入始终创建新作品，不覆盖、不合并现有作品。同一请求键与相同包/标题重试会返回原结果；同一请求键换包或换标题返回 `409`。

项目包扩展名为 `.siming-project`，MIME 为 `application/vnd.siming.project+zip`。内部使用 ZIP 仅作为容器，普通 `.zip` 不是受支持的入口格式。

## v1 manifest

`manifest.json` 必须且只能包含：

```json
{
  "format": "siming-project-package",
  "format_version": 1,
  "package_id": "UUID",
  "profile": "full",
  "producer": { "name": "siming", "app_version": "3.x" },
  "exported_at": "ISO-8601",
  "source_project": { "id": "source-id", "title": "作品名" },
  "entries": [
    {
      "path": "data/project.jsonl",
      "media_type": "application/x-ndjson",
      "size": 123,
      "sha256": "64 位小写十六进制",
      "records": 1
    }
  ]
}
```

v1 拒绝未知 manifest 字段、未知集合、未知记录字段和不支持的协议版本。作者数据集合使用 JSONL；原始立项素材位于 `assets/materials/`，并由 manifest 的大小与 SHA-256 约束。

## 数据档位

`full` 包含：

- 作品写作设置、作者确认的立项数据及版本；
- 当前大纲、角色、别名、关系、时间线和作者可见的角色语言风格；
- 世界观及关系；
- 正式章节、章节快照与摘要；
- 未保存章节草稿（恢复后仍是独立草稿，不会伪装或覆盖正式章节）；
- 作者已应用的叙事治理项和检查点；
- 原始立项素材文件。

`structure` 只包含作品写作设置、当前立项简报、大纲、角色及关系、世界观及关系。它严格排除章节正文、草稿、快照、摘要、素材、历史版本和带正文证据的治理数据。

两个档位都排除自动任务、助手对话/运行/记忆、RAG、建档和 Operation 运行态、缓存、质量指标、立项运行日志/事件/幂等声明、Skill、Prompt Pack、MCP、外部 Agent 权限以及模型/训练配置。角色语气和口头禅属于作者内容；`model_override`、`custom_system_prompt` 等执行配置不属于项目包。

## 安全与恢复语义

导入在任何数据库写入前完成 ZIP 路径、条目、版本、Schema、记录数、大小、SHA-256 和引用关系校验。禁止加密 ZIP、符号链接、重复路径、绝对路径、目录穿越和未声明条目。

`narrative_checkpoints` 的 `chapter_id` 与 `chapter_snapshot_id` 对“指向已删除章节/快照”的陈旧引用做容错：完整档位导出时，超出包内章节与快照集合的引用会先被清洗为 `null`；对旧备份包内已携带的陈旧引用，导入校验放行，恢复时同样置为 `null`（检查点保留，仅断开失效的章节/快照关联）。

默认限制：

- 压缩包 512 MiB；
- 解压总量 2 GiB；
- 最多 10,000 个 ZIP 条目；
- 单个 JSON/JSONL 128 MiB；
- 单个素材 25 MiB；
- 压缩比不超过 100:1。

实体 ID 使用 UUIDv5，由 `Idempotency-Key + 集合类型 + 源 ID` 确定。同一包换请求键可以有意创建另一份副本。素材恢复到新的项目内路径，素材分块和检索索引由确定性流程重建；导入不会启动 Agent、建档或自动任务。

v1 不传输 `cataloging_required` 运行态字段。PC 与 Android 导入时按同一确定性规则重建续写门槛：空正文无需建档；非空正文必须同时存在同章、同版本、内容完全一致的快照，以及不早于该快照的非空建档摘要，才恢复为无需补建档。摘要时间使用 `updated_at`，为空时使用 `created_at`；无时区时间按 UTC 处理。正文的 `updated_at` 也可能由标题或其他元数据更新，因此不单独用它判定摘要过期。旧版本快照、不同正文、较早摘要或缺失证据均恢复为待建档，不能仅凭摘要存在或数据库默认值放行。

Android 数据库从版本 3 升级到版本 4 时，对已经登记为项目包导入的作品执行一次缺失状态修复，使用本机保存的快照和摘要，不要求连接 PC。迁移仅补齐缺失状态，保留明确的待建档/已建档状态、正文修改、同步修订、冲突标记和 outbox；日常读写不再执行兼容分支。若早于 3.4.1 的导入没有恢复快照和摘要，需要用完整原包重新导入这些资料。

Android 使用同一 manifest、集合字段、引用校验（含 `narrative_checkpoints` 陈旧引用容错）、限制和 UUIDv5 算法。文件先通过 `ContentResolver` 流式写入本机副本，不进入外部小说的 20 MiB `ByteArray` 解析器。离线导入保存完整原包和请求键；离线重导会保留原包中手机暂不展示的合法集合与素材，再叠加当前本地作者数据。联网同步时先上传项目包，再回放该作品的普通 outbox 修改。

尚未上传的手机项目包副本使用 `revision=0`、`dirty=false`，由整包上传队列管理，不能把 `dirty=false` 当作已同步证明。作品列表与删除工具共用服务器修订、整包上传状态及创建请求的发送记录：未上传作品允许本机删除，并在事务中清理全部副本、冲突及待同步记录，移除保留的原包；已同步或上传结果未确认的作品通过 Gateway 核验并调用 PC 删除 API。导入、同步与删除共用互斥边界，删除时重新读取状态；无需修改旧导入包或制造逐实体 outbox 才能恢复正确显示。

## 可读稿件与项目包的区别

导出界面把两类结果分开：

- TXT、DOCX、PDF：面向阅读、投稿或交付，只生成可读稿件。
- `.siming-project`：面向司命之间的迁移与备份，可选择 `full` 或 `structure`。

TXT、Markdown、DOCX 导入只创建作品与正式章节，不推断角色、世界观、任务或其他结构化司命数据。
