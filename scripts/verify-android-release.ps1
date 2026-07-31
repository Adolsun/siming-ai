param(
    [string]$ReleaseDir = "release",
    [string]$ExpectedVersion = "",
    [string]$ExpectedCertificateSha256 = "7977f60224fbfd336c5670103a415664e82d1b90750225fbd511b9949100c60a"
)

$ErrorActionPreference = "Stop"

$apkPath = Join-Path $ReleaseDir "Siming.apk"
$shaPath = Join-Path $ReleaseDir "Siming-apk-sha256.txt"
foreach ($path in @($apkPath, $shaPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Android release asset is missing: $path"
    }
}

$actualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $apkPath).Hash.ToLowerInvariant()
$shaTokens = ((Get-Content -LiteralPath $shaPath -TotalCount 1).Trim() -split '\s+')
if ($shaTokens.Count -lt 2 -or $shaTokens[1] -ne "Siming.apk") {
    throw "Siming-apk-sha256.txt must contain the Siming.apk file name."
}
if ($shaTokens[0].ToLowerInvariant() -ne $actualSha) {
    throw "Siming-apk-sha256.txt does not match Siming.apk."
}

$sdkRoot = $env:ANDROID_SDK_ROOT
if (-not $sdkRoot) { $sdkRoot = $env:ANDROID_HOME }
if (-not $sdkRoot -or -not (Test-Path -LiteralPath $sdkRoot)) {
    throw "ANDROID_SDK_ROOT is required to verify the APK signature and manifest."
}
$buildTools = Get-ChildItem -LiteralPath (Join-Path $sdkRoot "build-tools") -Directory |
    Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
    Select-Object -First 1
if (-not $buildTools) { throw "Android build-tools are not installed." }

$apksigner = Join-Path $buildTools.FullName "apksigner.bat"
$aapt = Join-Path $buildTools.FullName "aapt.exe"
$zipalign = Join-Path $buildTools.FullName "zipalign.exe"
foreach ($tool in @($apksigner, $aapt, $zipalign)) {
    if (-not (Test-Path -LiteralPath $tool)) { throw "Android verification tool is missing: $tool" }
}

& $zipalign -c -p 4 $apkPath
if ($LASTEXITCODE -ne 0) { throw "Siming.apk is not zip-aligned." }
$signatureOutput = (& $apksigner verify --verbose --print-certs $apkPath 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Siming.apk signature verification failed.`n$signatureOutput" }
$certificateMatch = [regex]::Match(
    $signatureOutput,
    "(?im)^Signer #1 certificate SHA-256 digest:\s*([0-9a-f:]+)\s*$"
)
if (-not $certificateMatch.Success) {
    throw "Unable to read the APK signing certificate SHA-256 fingerprint."
}
$actualCertificateSha256 = $certificateMatch.Groups[1].Value.Replace(":", "").ToLowerInvariant()
if ($ExpectedCertificateSha256 -and $actualCertificateSha256 -ne $ExpectedCertificateSha256.ToLowerInvariant()) {
    throw "APK certificate '$actualCertificateSha256' does not match the trusted Siming release certificate."
}

$badging = (& $aapt dump badging $apkPath) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "Unable to read Siming.apk manifest." }
$packageMatch = [regex]::Match(
    $badging,
    "(?m)^package:\s+name='com\.siming\.mobile'[^\r\n]*$"
)
$versionMatch = [regex]::Match(
    $packageMatch.Value,
    "(?:^|\s)versionName='([^']+)'"
)
$versionCodeMatch = [regex]::Match(
    $packageMatch.Value,
    "(?:^|\s)versionCode='([^']+)'"
)
if (-not $packageMatch.Success -or -not $versionMatch.Success -or -not $versionCodeMatch.Success) {
    throw "Siming.apk does not contain the expected application id and version."
}
$actualVersion = $versionMatch.Groups[1].Value
$actualVersionCode = $versionCodeMatch.Groups[1].Value
if ($ExpectedVersion -and $actualVersion -ne $ExpectedVersion) {
    throw "APK version '$actualVersion' does not match expected '$ExpectedVersion'."
}
if ($ExpectedVersion -and $ExpectedVersion -match '^(\d+)\.(\d+)\.(\d+)') {
    $expectedVersionCode = ([int]$Matches[1] * 10000) + ([int]$Matches[2] * 100) + [int]$Matches[3]
    if ($actualVersionCode -ne [string]$expectedVersionCode) {
        throw "APK versionCode '$actualVersionCode' does not match expected '$expectedVersionCode'."
    }
}

Write-Host "Android release verified: Siming.apk version=$actualVersion code=$actualVersionCode cert=$actualCertificateSha256 sha256=$actualSha" -ForegroundColor Green
