# Windows 可执行程序打包

## 生成 exe

在项目根目录运行：

```bat
build-exe.bat
```

生成结果：

```text
release\Siming.exe
release\update.json
release\sha256.txt
```

`Siming.exe` 是面向 Windows 10 x64 或更高版本的正式分发文件。Windows 7、Windows 8/8.1 和 32 位 Windows 不在支持范围内，不应将当前构建标记或分发为兼容这些系统。Android 使用独立的长期签名密钥构建；3.2.1 同时发布 APK。旧品牌数据目录仍然兼容，但旧 exe 名不再生成、不再上传。

## 给普通用户运行

**系统要求：Windows 10 x64 或更高版本。**

新用户发送 `release\Siming.exe` 即可。用户双击后会：

1. 自动启动本地后端服务。
2. 自动打开浏览器页面。
3. 使用本机数据目录保存数据库、密钥、模型和运行时配置。

默认数据目录：

```text
%LOCALAPPDATA%\Siming
```

如果用户已经用旧版产生过数据，新版启动时会自动检测：

```text
%LOCALAPPDATA%\Moshu
%LOCALAPPDATA%\NovelWritingAgent
```

旧目录存在且新目录没有有效数据库时，司命会继续使用旧目录，避免用户丢数据。

## 重新指定数据目录

优先使用：

```bat
set SIMING_HOME=D:\SimingData
release\Siming.exe
```

旧变量 `MOSHU_HOME`、`NOVEL_AGENT_HOME` 仍然兼容。

## 打包机要求

只有负责打包的电脑需要安装 Python、Node.js 和 npm。普通用户运行 `Siming.exe` 不需要安装这些工具。

## 自动更新

桌面更新只接受同时满足以下条件的 `Siming.exe`：

1. SHA-256 与 `update.json`、`sha256.txt` 完全一致。
2. Windows Authenticode 签名可信。
3. 签名包含可信时间戳。

本地开发包可以不签名。正式自动更新包必须签名；没有证书时，只能显式使用 `-ManualDownloadOnly` 发布供用户主动下载并核对 SHA256 的手动安装包。签名必须在计算发布 SHA-256 **之前**完成，因为 Authenticode 会改变 exe 字节。

默认更新仓库：

```text
teangtang1122/siming-ai
```

发布新版本时，在 GitHub Release 上传：

```text
Siming.exe
sha256.txt
update.json
```

`sha256.txt` 只包含：

```text
<sha256>  Siming.exe
```

更新器只下载 `Siming.exe`。Release 中不要上传旧 exe 名资产。

### Windows 正式签名

GitHub Actions 需要配置以下加密 Secrets：

```text
SIMING_WINDOWS_CODESIGN_PFX_BASE64
SIMING_WINDOWS_CODESIGN_PASSWORD
```

前者是受信任代码签名证书 PFX 的 Base64 内容，后者是 PFX 口令。证书、私钥和口令不得提交到仓库、构建日志或 Release 资产。

本地发布机可在构建后运行：

```powershell
.\scripts\sign-windows-release.ps1 `
  -ReleaseDir release `
  -CertificatePath C:\secure\siming-codesign.pfx `
  -CertificatePassword $env:SIMING_CODESIGN_PASSWORD `
  -ExpectedVersion 3.2.1

.\scripts\verify-release-assets.ps1 `
  -ReleaseDir release `
  -ExpectedVersion 3.2.1 `
  -RequireTrustedSignature
```

签名脚本会在可信时间戳校验通过后重新生成 `update.json` 与 `sha256.txt`。如果线上版本已经发布为未签名包，旧客户端会显示 `no_signature` 并停止安装；必须用签名后的同版本 exe 及重新计算的两个完整性文件一并替换，或者发布更高的签名版本。

没有 Windows 代码签名证书时，可发布仅供手动安装的 Windows 资产：

```powershell
.\scripts\publish-github.ps1 -Tag v3.2.1 -SkipBuild -ManualDownloadOnly
```

该模式不会降低应用内更新器的签名要求，也不会包含 Android APK。

## Android APK

3.2.1 恢复 Android 发布，并继续使用同一把长期保存的发布密钥。手动运行发布脚本时，必须显式使用 `-IncludeAndroid`，确保 APK 与校验文件一同上传。

Android Release 必须使用同一把长期保存的发布密钥签名；丢失密钥后，已安装用户无法原位升级。密钥和口令不得写入仓库、构建日志或 Release 资产。

本地构建机通过以下环境变量提供签名信息：

```text
SIMING_ANDROID_KEYSTORE_FILE
SIMING_ANDROID_KEYSTORE_PASSWORD
SIMING_ANDROID_KEY_ALIAS
SIMING_ANDROID_KEY_PASSWORD
ANDROID_SDK_ROOT
JAVA_HOME
```

GitHub Actions 使用 `SIMING_ANDROID_KEYSTORE_BASE64` 保存同一密钥的 Base64 内容，并使用上述三个密码/别名 Secret；工作流只在临时目录还原密钥，构建结束后不保留该文件。

然后运行：

```powershell
.\scripts\build-android-release.ps1
.\scripts\verify-android-release.ps1 -ExpectedVersion 3.1.11
```

验证脚本会检查 APK SHA-256、zip 对齐、签名证书、包名 `com.siming.mobile` 与版本号。GitHub Actions 使用同一发布密钥的加密 Secrets，不为每次构建临时生成新密钥。

## Gateway 容器

正式版本同时发布：

```text
ghcr.io/teangtang1122/siming-ai-gateway:<version>
ghcr.io/teangtang1122/siming-ai-gateway:<major.minor>
ghcr.io/teangtang1122/siming-ai-gateway:latest
```

镜像必须包含 `linux/amd64` 与 `linux/arm64`，以 UID 10001 非 root 运行；`/data` 可写而 `/app` 不可写。发布前运行容器健康检查并验证 Docker Gateway 不暴露本地模型、CLI、MCP 与训练能力。

可用环境变量覆盖更新源：

```bat
set SIMING_UPDATE_REPO=owner/repo
set SIMING_UPDATE_MANIFEST_URL=https://example.com/update.json
set SIMING_DISABLE_UPDATE=1
```

旧变量 `MOSHU_UPDATE_REPO`、`MOSHU_UPDATE_MANIFEST_URL`、`MOSHU_DISABLE_UPDATE`、`NOVEL_AGENT_*` 仍然兼容。

## MCP Server

打包后的 exe 包含 MCP Server 入口。推荐让程序自动检测和配置本机 Agent；手动排障时可以运行：

```powershell
powershell -NoProfile -File .\scripts\setup-external-agent-mcp.ps1
```

配置示例：

```json
{
  "mcpServers": {
    "siming": {
      "command": "C:\\path\\to\\Siming.exe",
      "args": ["--mcp-server", "--permission-pack", "project_management"],
      "env": {}
    }
  }
}
```

如果从源码运行：

```bat
python scripts\moshu-mcp-server.py --permission-pack project_management
```

入口脚本文件名暂时保留 `moshu-mcp-server.py`，用于兼容旧文档和旧配置；客户端里的服务器条目应使用 `siming`。

## Smoke Test

打包后运行：

```powershell
.\scripts\smoke-test-release.ps1
```

测试会验证 `Siming.exe`、MCP 配置脚本、服务启动和核心 API。
