param([int]$Port = 6006)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$runtime = Join-Path $root '.build/phoenix-venv/Scripts/phoenix.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    throw 'Install scripts/observability/requirements.txt into .build/phoenix-venv first.'
}
& (Join-Path $root '.build/phoenix-venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'prepare_phoenix.py')
if ($LASTEXITCODE -ne 0) { throw 'Phoenix runtime preparation failed.' }
$data = Join-Path $root '.build/phoenix-data'
New-Item -ItemType Directory -Path $data -Force | Out-Null
$env:PHOENIX_HOST = '127.0.0.1'
$env:PHOENIX_PORT = "$Port"
$env:PHOENIX_WORKING_DIR = $data
$env:PHOENIX_TELEMETRY_ENABLED = 'false'
$env:PHOENIX_ALLOW_EXTERNAL_RESOURCES = 'false'
$env:PHOENIX_DISABLE_AGENT_ASSISTANT = 'true'
$env:PHOENIX_ENABLE_MCP_SERVER = 'false'
$env:PHOENIX_DISCOVER_CONFIG = 'false'
$env:PYTHONUTF8 = '1'
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "Port $Port is already in use; inspect the running server instead of starting a duplicate."
}
$process = Start-Process -FilePath $runtime -ArgumentList @('serve', '--no-internet') -WindowStyle Hidden -PassThru `
    -WorkingDirectory $root -RedirectStandardOutput (Join-Path $data 'server.stdout.log') `
    -RedirectStandardError (Join-Path $data 'server.stderr.log')
$process.Id | Set-Content -LiteralPath (Join-Path $data 'server.pid')
Write-Output "Phoenix PID $($process.Id), UI http://127.0.0.1:$Port"
