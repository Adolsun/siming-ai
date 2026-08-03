param(
    [string]$ReleaseDir = "release",
    [string]$GradleCommand = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
$androidRoot = Join-Path $root "mobile\android"
$releaseRoot = [System.IO.Path]::GetFullPath((Join-Path $root $ReleaseDir))
New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null

$required = @(
    "SIMING_ANDROID_KEYSTORE_FILE",
    "SIMING_ANDROID_KEYSTORE_PASSWORD",
    "SIMING_ANDROID_KEY_ALIAS",
    "SIMING_ANDROID_KEY_PASSWORD"
)
foreach ($name in $required) {
    if (-not [Environment]::GetEnvironmentVariable($name)) {
        throw "$name is required to build the signed Android release."
    }
}
$keystore = [System.IO.Path]::GetFullPath($env:SIMING_ANDROID_KEYSTORE_FILE)
if (-not (Test-Path -LiteralPath $keystore)) {
    throw "Android signing keystore does not exist: $keystore"
}
if (-not $env:ANDROID_SDK_ROOT -or -not (Test-Path -LiteralPath $env:ANDROID_SDK_ROOT)) {
    throw "ANDROID_SDK_ROOT must point to an installed Android SDK."
}

$gradle = $GradleCommand
if (-not $gradle) { $gradle = $env:SIMING_GRADLE_COMMAND }
if (-not $gradle) { $gradle = Join-Path $androidRoot "gradlew.bat" }

Push-Location $androidRoot
try {
    & $gradle assembleRelease --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "Android release build failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}

$unsignedApk = Join-Path $androidRoot "app\build\outputs\apk\release\app-release-unsigned.apk"
if (-not (Test-Path -LiteralPath $unsignedApk)) {
    throw "Unsigned Android release APK was not produced: $unsignedApk"
}

$buildTools = Get-ChildItem -LiteralPath (Join-Path $env:ANDROID_SDK_ROOT "build-tools") -Directory |
    Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
    Select-Object -First 1
if (-not $buildTools) { throw "Android build-tools are not installed." }
$zipalign = Join-Path $buildTools.FullName "zipalign.exe"
$apksigner = Join-Path $buildTools.FullName "apksigner.bat"

$alignedApk = Join-Path $releaseRoot "Siming-aligned.apk"
$signedApk = Join-Path $releaseRoot "Siming.apk"
$shaPath = Join-Path $releaseRoot "Siming-apk-sha256.txt"
foreach ($path in @($alignedApk, $signedApk, $shaPath)) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}

& $zipalign -p -f 4 $unsignedApk $alignedApk
if ($LASTEXITCODE -ne 0) { throw "zipalign failed with exit code $LASTEXITCODE." }
& $apksigner sign `
    --ks $keystore `
    --ks-key-alias $env:SIMING_ANDROID_KEY_ALIAS `
    --ks-pass env:SIMING_ANDROID_KEYSTORE_PASSWORD `
    --key-pass env:SIMING_ANDROID_KEY_PASSWORD `
    --out $signedApk `
    $alignedApk
if ($LASTEXITCODE -ne 0) { throw "APK signing failed with exit code $LASTEXITCODE." }
Remove-Item -LiteralPath $alignedApk -Force

$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $signedApk).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText(
    $shaPath,
    "$sha  Siming.apk`n",
    [System.Text.UTF8Encoding]::new($false)
)

$versionLine = Select-String -Path (Join-Path $root "backend\app\version.py") -Pattern 'APP_VERSION\s*=\s*["'']([^"'']+)' | Select-Object -First 1
if (-not $versionLine) { throw "Unable to read the application version." }
$version = $versionLine.Matches.Groups[1].Value
& (Join-Path $scriptDir "verify-android-release.ps1") -ReleaseDir $releaseRoot -ExpectedVersion $version
if ($LASTEXITCODE -ne 0) { throw "Android release verification failed." }
