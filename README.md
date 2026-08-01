# 司命 / Siming

**长篇小说的命运织机。**

Siming is a free and open-source, local-first AI workspace for planning, writing, archiving, and maintaining continuity in long-form fiction.

[![Latest Release](https://img.shields.io/github/v/release/teangtang1122/siming-ai?display_name=tag&sort=semver)](https://github.com/teangtang1122/siming-ai/releases/latest)
![Windows x64](https://img.shields.io/badge/Windows-x64-2979ff?logo=windows11&logoColor=white)
![Android 8+](https://img.shields.io/badge/Android-8%2B-3c7a57?logo=android&logoColor=white)
![Gateway](https://img.shields.io/badge/Gateway-amd64%20%7C%20arm64-963a36?logo=docker&logoColor=white)
[![Backend CI](https://github.com/teangtang1122/siming-ai/actions/workflows/backend-ci.yml/badge.svg?branch=main)](https://github.com/teangtang1122/siming-ai/actions/workflows/backend-ci.yml)
[![Frontend CI](https://github.com/teangtang1122/siming-ai/actions/workflows/frontend-ci.yml/badge.svg?branch=main)](https://github.com/teangtang1122/siming-ai/actions/workflows/frontend-ci.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-3c7a57.svg)](LICENSE)

[下载 Windows 版](https://github.com/teangtang1122/siming-ai/releases/latest/download/Siming.exe) · [下载 Android 版](https://github.com/teangtang1122/siming-ai/releases/latest/download/Siming.apk) · [跨设备指南](docs/gateway-mobile.md) · [反馈问题](https://github.com/teangtang1122/siming-ai/issues/new/choose) · [版本记录](https://github.com/teangtang1122/siming-ai/releases)

> 💬 **用户交流 QQ 群：814283606**  
> 欢迎交流使用体验、小说创作方法与功能建议。为确保安全，请仅从本仓库的官方 Releases 下载 `Siming.exe`。

[![司命新书立项工作台，展示《雾海拾光》的三套轻量创意方向](docs/images/readme/novel-creation.png)](docs/images/readme/novel-creation.png)

*新书立项工作台：先比较三套故事发动机，再逐步生成角色、世界观、卷纲和前 15 章细纲。图中内容均为虚构演示数据。*

> **3.1.2** 增加对话式立项的结构化事实面：AI 助手内可查看、确认和定向调整各项立项数据；新增 revision 防护的原子补丁、字段锁定、依赖与影响摘要工具。历史变更请查看 [GitHub Releases](https://github.com/teangtang1122/siming-ai/releases)。

## 它解决什么问题

用通用大模型直接写长篇，真正难的往往不是生成一段文字，而是让几百章的事实持续一致：

- 角色的年龄、外貌、位置、伤势、目标和关系会随时间变化。
- 大纲、正文、世界观、伏笔和时间线容易分散，写后还需要反复手工同步。
- 几十万字无法一次塞进模型，只靠聊天记忆很快就会丢失前文。
- API、Claude Code、Codex、OpenCode 等入口的能力和错误提示不一致，长任务也很难判断是在计算还是真的卡住。

司命把正文、大纲、角色状态、世界观、叙事账本和 AI 工作流放在同一个本地项目中。数据库是权威写入源，Markdown/JSON 文件作为可阅读镜像；修改通过司命工具落库，让前端、索引、版本历史和文件保持一致。

项目采用 Apache 2.0 许可证，软件本身永久免费、源码公开。你可以从一句创意建立新小说，也可以导入已有 TXT 小说完成建档后续写或二创。写作时会按章节选取角色当前状态、世界规则、时间线、伏笔和未解决动作，并在写后更新叙事账本，尽量减少人物失真和 OOC；模型生成仍建议由作者最终审阅。

## 3 分钟开始

### 1. 下载并启动

从 [官方 GitHub Release](https://github.com/teangtang1122/siming-ai/releases/latest) 下载 `Siming.exe`，双击即可启动。普通使用者不需要安装 Python、Node.js，也不需要打开 CMD 或 PowerShell。

首次启动会让你选择小说数据目录；不修改时使用 `%LOCALAPPDATA%\Siming`。旧版 `%LOCALAPPDATA%\Moshu` 和 `%LOCALAPPDATA%\NovelWritingAgent` 数据会兼容读取，不会被主动删除。

### 2. 点击“准备 AI 并开始构思”

没有任何模型配置时，司命会为 Windows 自动下载、校验并测试 OpenCode，整个过程都在图形界面里完成。测试通过后才会把模型标记为可用。

免费方案当前使用 OpenCode 提供的免费开源模型 DeepSeek V4 Flash，运行时会显示完整模型 ID：

```text
opencode_cli:opencode/deepseek-v4-flash-free
```

免费模型、额度与数据政策由对应服务提供方决定，可能随时调整。若实际模型发生切换，司命会在运行记录中明确显示；更多高质量模型仍需前往相应模型官网自行订阅。

### 3. 说一句故事想法

输入一句梗概，司命会先给出三套轻量创意。选定方向后，可以使用完整向导逐步确认角色、世界观、卷纲和前 15 章细纲，也可以快速生成后再统一审阅。正式作品只会在最终确认时创建。

## 界面预览

| 首次准备 AI | 作品写作工作台 |
| --- | --- |
| [![司命首次使用页，展示准备 AI 并开始构思按钮](docs/images/readme/quick-start.png)](docs/images/readme/quick-start.png) | [![司命作品写作工作台，展示《雾海拾光》章节列表、摘要和正文编辑器](docs/images/readme/project-workspace.png)](docs/images/readme/project-workspace.png) |
| 不需要开发工具或命令行，下载、校验和模型测试都有明确步骤。 | 章节、大纲节点、摘要、正文与版本历史在同一工作台内管理。 |

[![司命全局任务中心，展示《雾海拾光》正在处理第 138/600 章的作品建档任务](docs/images/readme/task-center.png)](docs/images/readme/task-center.png)

*全局任务中心：跨页面查看当前阶段、处理对象、模型、已用时间和运行健康度。建档和拆书不设总时限，只会在输出、工具、进程和业务检查点都长时间没有变化时判定卡住。*

> 四张截图均由 `npm run screenshots:readme` 使用真实前端与稳定的虚构数据生成，不读取本机作品、路径、凭据或模型账户。

## 核心能力

| 能力 | 作者能得到什么 |
| --- | --- |
| 新书立项 | 三套轻量创意、可编辑的分阶段向导、全书卷纲与前 15 章细纲；每章包含 2–6 个场景节点。 |
| 作品建档 | 逐章提取摘要、大纲、角色状态、关系、世界观、时间线、伏笔与故事线，可从检查点继续。 |
| 写作与上下文 | 按任务预算选择大纲、场景、近期摘要、角色当前状态、有效线索和未解决动作，避免整本书硬塞给模型。 |
| 叙事账本 | 跟踪已完成节拍、已揭露线索、读者承诺和故事线状态，写后归档并为下一章注入关键事实。 |
| 版本与回退 | 每次写章前后保留快照；对新章不满意时，可查看差异并恢复旧版，同步回退相关档案和文件镜像。 |
| 长任务运行 | 展示阶段、最近活动、模型和健康度；支持暂停、继续、取消和重试当前单元，已完成章节不会因后续失败而丢失。 |
| 跨设备创作 | Android 保留可写离线副本；Gateway 按有序修订同步并在分岔时保留双方版本，不静默覆盖。 |

## Android 与自己的 Gateway

司命没有官方小说数据服务器。Android 客户端连接的是你在桌面端启用或用 Docker 部署的 Gateway：

- 桌面内置 Gateway：适合电脑开机时同步，仍可使用桌面本地模型、OpenCode、CLI 和 MCP。
- Docker Gateway：适合 NAS、家中常开主机或云主机，提供同步和云端 API 写作；镜像不启用本地模型、OpenCode、CLI、MCP 或训练能力。
- 手机端：可新建或导入 TXT，编辑章节、大纲、角色、世界观、伏笔与治理资料；离线照常写，联网后先上传再拉取。

局域网可以直接连接；跨网络推荐 [Tailscale](https://tailscale.com/) 或自己配置 HTTPS。只有已显式加入同步的作品才会进入 Gateway，首次建档前会自动备份并核对数量与摘要哈希。完整部署、配对、备份和恢复步骤见 [Android 与 Gateway 指南](docs/gateway-mobile.md)，安全边界见 [Gateway 威胁模型](docs/security/gateway-threat-model.md)。

最小 Docker 启动示例：

```powershell
$env:SIMING_GATEWAY_BOOTSTRAP_KEY = "请换成至少12位的随机管理口令"
docker compose -f compose.gateway.yml up -d
```

管理页默认位于 `http://你的设备地址:8000`。口令只用于换取当前浏览器的 HttpOnly 管理会话，不写入浏览器存储。

## 模型与隐私

司命可以使用 OpenAI、Anthropic Claude、DeepSeek、Google Gemini、通义千问、OpenAI 兼容中转站，也可以调用 Claude Code、Codex、OpenCode 等本机 CLI。仅“检测到命令”不等于可用；只有完成真实对话测试的模型才会进入新书、助手和写作流程。

- 作品数据库、文件镜像、快照和任务记录保存在你选择的本机目录。
- 司命不会自主把整个作品库上传到项目服务器。
- 使用云端 API 或需联网的 CLI 时，当前任务选中的提示词、正文片段和上下文会发送给对应提供方处理。
- API Key 由本机配置使用；OpenCode 的一次性登录凭据仅传递给当前登录进程，不保存、不回显、不写日志。

请根据内容敏感程度阅读所选模型提供方的数据政策，不要向免费云端模型提交隐私或机密内容。

## 下载与信任

当前 `Siming.exe` **尚未完成代码签名**。PyInstaller 打包的单文件 EXE 会在运行时解压内嵌 Python 组件、启动本地 Web 服务，并在用户授权时启动本机 CLI，因此部分杀毒软件可能产生误报。

为减少供应链风险：

1. 只从 [`teangtang1122/siming-ai` 官方 Releases](https://github.com/teangtang1122/siming-ai/releases) 下载。
2. 下载同一版本的 `sha256.txt`，用 `certutil -hashfile Siming.exe SHA256` 计算文件哈希并与其对照。
3. 不要使用网盘、聊天群或第三方网站二次分发的 EXE。

发行页会同时提供 `Siming.exe`、`update.json`、`sha256.txt`、签名的 `Siming.apk` 和 `Siming-apk-sha256.txt`。桌面三件套会校验版本、下载地址和 SHA256；APK 还会校验签名、对齐、包名和版本号。

## 外部 Agent 与提示词投稿

司命支持让 Claude Code、Codex、OpenCode 等外部 Agent 通过 MCP 读取项目上下文。镜像文件可以直接读取；章节、角色、大纲和世界观的新建或修改必须通过司命工具入库，不把“直接写出一个 Markdown 文件”当作完成。

提示词贡献不要求作者掌握 Git。在作品的“提示词投稿”页面中，可以直接修改快速模式或质量模式提示词，补充改动说明、预期效果和测试记录，然后生成投稿包和预填好的 GitHub Issue。

专业文档：

- [外部 Agent 无 API 写作](docs/agent/external-no-api-writing.md)
- [外部 Agent 无 API 建档](docs/agent/external-no-api-cataloging.md)
- [MCP 权限包与工具](docs/mcp/permission-packs-and-tools.md)
- [MCP 安全边界](docs/mcp/security.md)

## 开发与贡献

普通使用者只需要 `Siming.exe`。以下环境仅面向源码贡献者。

```powershell
# 后端
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# 前端（新终端）
cd frontend
npm install
npm run dev
```

提交前的常用检查：

```powershell
backend\.venv\Scripts\python.exe -m pytest backend/tests -q
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend run screenshots:readme
cd mobile\android
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

本地桌面打包使用 `.\build-exe.bat`；签名 APK 使用 `.\scripts\build-android-release.ps1`（签名凭据只通过环境变量提供）。提交代码、文档、可复现问题或者通过 GUI 生成的提示词投稿都很欢迎。

## 路线图与许可证

- [项目路线图](docs/roadmap.md)
- [项目管理与发布约定](docs/project-management.md)
- [全部版本发布记录](https://github.com/teangtang1122/siming-ai/releases)
- [功能建议与问题反馈](https://github.com/teangtang1122/siming-ai/issues)

本项目采用 [Apache License 2.0](LICENSE)。
