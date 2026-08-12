param(
  [string]$ReleaseDir = "release",
  [string]$AppName = "Siming",
  [Parameter(Mandatory = $true)]
  [string]$CertificatePath,
  [Parameter(Mandatory = $true)]
  [AllowEmptyString()]
  [string]$CertificatePassword,
  [string]$TimestampUrl = "http://timestamp.digicert.com",
  [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"

function Resolve-SignTool {
  if ($env:SIMING_SIGNTOOL_PATH) {
    $ConfiguredPath = [System.IO.Path]::GetFullPath($env:SIMING_SIGNTOOL_PATH)
    if (-not (Test-Path -LiteralPath $ConfiguredPath -PathType Leaf)) {
      throw "SIMING_SIGNTOOL_PATH does not exist: $ConfiguredPath"
    }
    return $ConfiguredPath
  }

  $Command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
  if ($Command) {
    return $Command.Source
  }

  $WindowsKitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
  if (Test-Path -LiteralPath $WindowsKitsRoot -PathType Container) {
    $Candidates = @(
      Get-ChildItem -LiteralPath $WindowsKitsRoot -Filter "signtool.exe" -File -Recurse |
        Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
        Sort-Object FullName -Descending
    )
    if ($Candidates.Count -gt 0) {
      return $Candidates[0].FullName
    }
  }

  throw "Windows SDK signtool.exe is required to sign Siming.exe."
}

$ResolvedReleaseDir = [System.IO.Path]::GetFullPath($ReleaseDir)
$ExePath = Join-Path $ResolvedReleaseDir "$AppName.exe"
$ManifestPath = Join-Path $ResolvedReleaseDir "update.json"
$ShaPath = Join-Path $ResolvedReleaseDir "sha256.txt"
$ResolvedCertificatePath = [System.IO.Path]::GetFullPath($CertificatePath)

foreach ($RequiredPath in @($ExePath, $ManifestPath, $ShaPath, $ResolvedCertificatePath)) {
  if (-not (Test-Path -LiteralPath $RequiredPath -PathType Leaf)) {
    throw "Windows signing input is missing: $RequiredPath"
  }
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if (-not $Manifest.version) {
  throw "update.json must contain a version before signing."
}
if ($ExpectedVersion -and $Manifest.version -ne $ExpectedVersion) {
  throw "update.json version '$($Manifest.version)' does not match expected '$ExpectedVersion'."
}

$SignTool = Resolve-SignTool
$SignArguments = @(
  "sign",
  "/fd", "SHA256",
  "/td", "SHA256",
  "/tr", $TimestampUrl,
  "/f", $ResolvedCertificatePath
)
if ($CertificatePassword) {
  $SignArguments += @("/p", $CertificatePassword)
}
$SignArguments += $ExePath

Write-Host "Signing Windows release executable with a trusted, timestamped Authenticode signature..."
& $SignTool @SignArguments
if ($LASTEXITCODE -ne 0) {
  throw "signtool.exe failed with exit code $LASTEXITCODE."
}

$Signature = Get-AuthenticodeSignature -FilePath $ExePath
if ($Signature.Status -ne "Valid" -or -not $Signature.SignerCertificate) {
  throw "Signed executable is not trusted: status=$($Signature.Status) message=$($Signature.StatusMessage)"
}
if (-not $Signature.TimeStamperCertificate) {
  throw "Signed executable has no trusted timestamp. Publishing is blocked because the signature would expire with the certificate."
}

# Authenticode changes the executable bytes. Refresh both integrity manifests
# only after signing so existing clients verify the exact published artifact.
$Sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLowerInvariant()
$Manifest.sha256 = $Sha256
$ManifestJson = $Manifest | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText(
  $ManifestPath,
  $ManifestJson + [Environment]::NewLine,
  [System.Text.UTF8Encoding]::new($false)
)
[System.IO.File]::WriteAllText(
  $ShaPath,
  "$Sha256  $AppName.exe" + [Environment]::NewLine,
  [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Windows release signed and manifests refreshed." -ForegroundColor Green
Write-Host "Signer: $($Signature.SignerCertificate.Subject)"
Write-Host "Thumbprint: $($Signature.SignerCertificate.Thumbprint)"
Write-Host "SHA256: $Sha256"
