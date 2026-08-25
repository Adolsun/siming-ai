param(
  [string]$ReleaseDir = "release",
  [string]$AppName = "Siming",
  [string]$ExpectedVersion = "",
  [switch]$RequireTrustedSignature,
  [switch]$AllowUnsignedManualRelease
)

$ErrorActionPreference = "Stop"

$ExePath = Join-Path $ReleaseDir "$AppName.exe"
$ManifestPath = Join-Path $ReleaseDir "update.json"
$ShaPath = Join-Path $ReleaseDir "sha256.txt"

foreach ($AssetPath in @($ExePath, $ManifestPath, $ShaPath)) {
  if (-not (Test-Path -LiteralPath $AssetPath)) {
    throw "Release asset is missing: $AssetPath"
  }
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$ActualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLowerInvariant()
$ShaTokens = ((Get-Content -LiteralPath $ShaPath -TotalCount 1).Trim() -split '\s+')

if ($ShaTokens.Count -lt 2 -or $ShaTokens[1] -ne "$AppName.exe") {
  throw "sha256.txt must contain the $AppName.exe file name."
}
if ($Manifest.sha256 -ne $ActualSha) {
  throw "update.json SHA256 does not match $AppName.exe."
}
if ($ShaTokens[0].ToLowerInvariant() -ne $ActualSha) {
  throw "sha256.txt SHA256 does not match $AppName.exe."
}
if ($ExpectedVersion -and $Manifest.version -ne $ExpectedVersion) {
  throw "update.json version '$($Manifest.version)' does not match expected '$ExpectedVersion'."
}
if (-not $Manifest.version -or -not $Manifest.download_url) {
  throw "update.json must contain version and download_url."
}
$IsPrerelease = $Manifest.version.Contains("-")
$ExpectedChannel = if ($IsPrerelease) { "preview" } else { "stable" }
if ($Manifest.channel -ne $ExpectedChannel) {
  throw "update.json channel '$($Manifest.channel)' does not match expected '$ExpectedChannel'."
}
if ($IsPrerelease) {
  $ExpectedTagPath = "/releases/download/v$($Manifest.version)/$AppName.exe"
  if (-not $Manifest.download_url.EndsWith($ExpectedTagPath)) {
    throw "Prerelease download_url must target its exact tag: $ExpectedTagPath"
  }
} elseif (-not $Manifest.download_url.EndsWith("/releases/latest/download/$AppName.exe")) {
  throw "Stable download_url must target releases/latest."
}

if ($RequireTrustedSignature -and $AllowUnsignedManualRelease) {
  throw "Choose either -RequireTrustedSignature or -AllowUnsignedManualRelease, not both."
}

if ($RequireTrustedSignature -or $AllowUnsignedManualRelease) {
  $Signature = Get-AuthenticodeSignature -FilePath $ExePath
  if ($Signature.Status -eq "Valid" -and $Signature.SignerCertificate) {
    if (-not $Signature.TimeStamperCertificate) {
      throw "Windows Authenticode signature has no trusted timestamp."
    }
    Write-Host "Trusted Windows signer: $($Signature.SignerCertificate.Subject) thumbprint=$($Signature.SignerCertificate.Thumbprint)" -ForegroundColor Green
  } elseif ($AllowUnsignedManualRelease -and $Signature.Status -eq "NotSigned") {
    Write-Warning "Siming.exe is unsigned and may only be distributed for explicit manual download. The in-app updater will reject it."
  } else {
    throw "Windows Authenticode signature is not trusted: status=$($Signature.Status) message=$($Signature.StatusMessage)"
  }
}

Write-Host "Release assets verified: $AppName.exe version=$($Manifest.version) sha256=$ActualSha" -ForegroundColor Green
