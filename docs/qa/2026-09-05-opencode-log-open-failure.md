# OpenCode 日志打开失败诊断

错误编号：`a29920f471574e8aa3b7015e8707a1b4`。日期：2026-09-05。

## 结论

根因已复现：当前司命及其启动的 CLI 子进程启用了 Windows RedirectionGuard，访问用户迁移后留下的目录联接时被系统拒绝。OpenCode 将底层的 `ERROR_UNTRUSTED_MOUNT_POINT`（WinError 448）显示为 `Unknown: FileSystem.open`。故障发生在模型请求之前，不是操作系统无法创建 OpenCode 进程。

触发条件为安装完成后的自动启动与目录联接同时存在。同版本 Inno Setup 6.7.1 的最小安装器实验，在 `PrivilegesRequired=lowest` 下通过 `runascurrentuser` 和 `runasoriginaluser` 启动的两个诊断进程都继承了限制；独立启动的相同诊断程序没有限制，能打开同一日志文件。仅补一个 `runasoriginaluser` 标志不能解决本机已复现的问题。

本次完成原因诊断，尚未修改安装器或重新打包。临时恢复方式是先保存工作、完全退出司命，再从桌面快捷方式独立打开。不要通过重新安装后自动打开的进程继续重试；不需要修改 API 参数、重装 OpenCode、删除日志、重建用户目录联接或关闭系统防护。用户正常 GUI 重启后的完整立项流程尚未复测。

## 故障记录

- 用户实际运行 `D:/Siming/Siming.exe`，SHA-256 为 `1504cfe92fe9d50b59a6737549cdc4ee2f842331dbbf143bc10a8544e25fc5e1`，与 19:20 新构建的修复包内程序一致。
- 持久化对话记录显示，本轮北京时间 19:28:24 开始，19:28:30 失败。在第一次模型步骤之后即进入错误状态，没有立项工具执行或资料写入回执。
- `launcher.log` 第 882—884 行的底层错误为：`本机 CLI 调用失败: Error: Unexpected error`，随后为 `Unknown: FileSystem.open (C:\Users\糖\.local\share\opencode\log\opencode.log)`。
- 本次失败来自已启动的本机 OpenCode CLI 返回的文件打开错误；日志没有报告此前 DeepSeek 的 `tool_choice` 或 `reasoning_content` 参数错误。不能将其等同于操作系统无法启动 `opencode.exe`：司命对进程创建失败使用“启动本机 CLI 失败”，此次实际记录为收集 CLI 输出后的“本机 CLI 调用失败”。
- 当前配置的 OpenCode 命令为司命托管的 `managed-cli/opencode/bin/opencode.exe`，实测版本 `1.18.4`。
- 司命将该错误保存为 `failure_class=unknown`，界面仅展示“立项助手处理失败”和编号，未说明实际为本机 CLI 调用期间的文件打开错误。这是仍待改善的错误分类与提示问题。
- 19:47 再次出现相同底层错误，编号为 `5e9454da1ffe407dbdfdf16d33a651b9`。

## 根因证据

环境为 Windows 25H2，构建 `26200.9278`。`C:\Users\糖\.local` 是目录联接（Junction），目标为 `D:\HuaweiMoveData\Users\糖\MigratedFromC\Profile\.local`。日志文件本身没有只读属性，普通进程与司命运行用户、完整性级别相同，均为非提升的中完整性进程。

通过 `GetProcessMitigationPolicy(ProcessRedirectionTrustPolicy)` 只读查询，结合 `CreateFileW` 以只读方式打开同一现有日志，得到以下结果。没有调用接口关闭或修改任何进程的缓解策略。

| 运行方式 | RedirectionTrust Flags | 原日志只读打开 | 验证范围 |
| --- | --- | --- | --- |
| 普通诊断进程独立启动 | 0 | 成功 | 原始路径与文件可用 |
| 正在运行的安装版司命，PID 39060 | 1 | 子进程被拒绝 | 实际故障进程 |
| 经安装版非持久化 CLI 连接测试启动的诊断子进程 | 1 | WinError 448 | 真实司命调用链 |
| Inno 6.7.1 最小安装器，`runascurrentuser` | 1 | WinError 448 | 安装器启动方式复现 |
| 同一最小安装器，`runasoriginaluser` | 1 | WinError 448 | 常见单标志修复无效 |
| 同一 `D:/Siming/Siming.exe` 独立启动，隔离数据的 MCP 模式 | 0 | 未在此进程中执行文件探针 | MCP initialize 成功，退出 0 |

安装器实验的父子进程记录显示：安装器加载进程 Flags 为 0，实际执行安装的 `.tmp` 进程为 1，它直接启动的 Python 及其下一层子进程均为 1。正在运行的司命启动于 19:25:30，原父进程 PID 38976 已退出，未获得它的历史映像名称；安装后自动启动这一触发路径由当前进程策略与同版本安装器对照实验共同定位。

通过安装版既有的 `POST /api/v1/config/models/test`，故意使用不存在的诊断模型，6.672 秒后稳定返回与用户完全相同的 `Unknown: FileSystem.open`。该接口不保存模型配置。再使用其自定义 CLI 测试能力启动只读探针，Windows API 返回 448，Python 将其映射为 `OSError(22)`；这一结果也排除了“只有 Bun/OpenCode 才会发生”的假设。

自定义探针故意返回诊断文字而不是连接测试约定的成功文字，因此接口返回“unexpected test reply”的 502 是预期结果。它只证明探针运行和文件访问结果，不能被记录为模型连接成功或第二个业务故障。

## 排除项与测试缺口

- 独立进程中的版本查询、启动诊断、中文目录下的初始化都成功；打包 DLL 搜索目录、隐藏窗口、有无标准输入、并发运行等隔离实验没有复现此故障。这些检查缺少实际安装器父进程环境，因此之前不能据此判断安装版可用。
- 独立进程使用不存在的模型时，成功越过日志初始化后按预期返回 `ProviderModelNotFoundError`。这只验证模型请求之前的初始化，没有调用真实模型。
- 只读属性也能让 OpenCode 显示类似的通用 `Unknown` 错误，但用户实际文件没有该属性。不能仅凭 OpenCode 的错误文本断定文件只读、被占用或用户名编码错误。
- 后续回归必须覆盖安装完成后的自动启动与独立启动，以及用户目录经迁移成为 Junction 的场景；只跑源码测试、版本查询、独立启动的打包 MCP 冒烟测试不足以覆盖此次故障。
- 正式修复应保持安装器自身的安全防护，将安装完成后的应用启动与安装器的进程限制分离，并改善 CLI 文件访问错误提示。不得全局关闭 RedirectionGuard，也不应擅自修改用户的目录联接、权限或持久模型配置。

## 上游资料与实测差异

[Inno Setup RedirectionGuard 文档](https://jrsoftware.org/ishelp/topic_setup_redirectionguard.htm)说明了目录联接防护及错误 448，但同时声称子进程不继承。该说法与此机器上 Inno 6.7.1 的两种启动方式实测不一致，因此本报告采用记录的进程策略与系统错误作为依据。上游 [WiX 问题 9334](https://github.com/wixtoolset/issues/issues/9334) 也报告过安装后启动应用继承此限制；它仅作为同类现象参考，不替代本项目复现。

## 范围与证据

本次未修改用户模型配置、密钥、作品、权限或目录联接，未重试立项写入，未发送真实模型生成请求，未重启正在运行的司命，未修改业务源码或重新打包正式安装器。最小诊断安装器不复制应用、不注册卸载项、不创建应用目录，只运行只读探针并在工作区保存报告；没有安装或覆盖 `D:/Siming`。

原始日志 SHA-256 在诊断前后均为 `4850c07bdc7d4a6deec39e4d17aaa19fef9dbffd09889ff331dc12c0b1ae519c`。所有启动的独立诊断进程已退出，用户原司命进程保持运行。

关键原始证据保存在 `.build/opencode-log-a29920f4/`：

- `installed-connection-probe.json`：实际安装版稳定复现原始错误。
- `installed-child-result.json`：Python/Bun/Win32 文件打开对照，Win32 返回 448。
- `probe-redirection-policy.json`、`installed-siming-child-policy.json`：当前司命与子进程的策略。
- `probe-inno-child.py/.iss`、`standalone-control.json`、`inno-current-user.json`、`inno-original-user.json`、`inno-diagnostic.log`：最小安装器复现与对照。
- `probe-siming-policy.json`：相同已安装二进制独立启动、隔离数据的 MCP initialize 与策略查询。
- `probe-startup.py/.json`、`probe-run.py/.json` 等：前期隔离排查，须按其实际验证范围理解。
