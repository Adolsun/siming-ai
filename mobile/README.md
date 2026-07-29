# Siming Android

Android 客户端位于 `mobile/android`，最低 Android 8.0（API 26），目标 API 35。它保存可写离线副本并连接用户自有 Gateway，不包含本地模型、OpenCode、CLI、MCP 或训练运行时。

## 开发构建

```powershell
$env:JAVA_HOME = "C:\path\to\jdk-17"
$env:ANDROID_SDK_ROOT = "C:\path\to\android-sdk"
cd mobile\android
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

Debug APK 位于 `app/build/outputs/apk/debug/app-debug.apk`。

## 正式签名

正式 APK 必须始终使用同一发布密钥。密钥文件、口令、生成的 APK、截图、模拟器数据和 `local.properties` 均被 `.gitignore` 排除；不要通过 Issue、日志或 Release 上传密钥。

```powershell
$env:SIMING_ANDROID_KEYSTORE_FILE = "C:\secure\siming-release.jks"
$env:SIMING_ANDROID_KEYSTORE_PASSWORD = "..."
$env:SIMING_ANDROID_KEY_ALIAS = "siming"
$env:SIMING_ANDROID_KEY_PASSWORD = "..."
.\scripts\build-android-release.ps1
```

脚本执行 R8 release 构建、zipalign、APK Signature Scheme 签名、签名/包名/版本验证，并输出 `release/Siming.apk` 与 `release/Siming-apk-sha256.txt`。GitHub Release 的 APK 版本必须与 `backend/app/version.py` 和 `frontend/package.json` 一致。

## 发布前检查

- 单元测试、lint、Debug 与 Release 构建通过。
- 在实际模拟器或手机检查连接、扫码、作品库、新建/导入、编辑、离线、同步、冲突、AI 禁用/运行和关于页面。
- 检查紧凑手机视口与当前参考视口，覆盖加载、空、错误、禁用和完成状态并保存截图。
- 用全新安装和上一正式版升级各验证一次；确认 Room schema、令牌迁移和 WorkManager 不丢任务。
- 通过 Gateway 创建作品、编辑同一实体制造冲突、解决后再次同步；断开设备后旧令牌必须失效。
