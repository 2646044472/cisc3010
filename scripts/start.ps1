param([switch]$NativeBroker, [int]$Port = 8787)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { python -m venv .venv }
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
if ($NativeBroker) {
    & "$PSScriptRoot\broker.ps1" -Action Start
} else {
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'Kafka startup failed. Check Docker Desktop or use -NativeBroker with Java 17+.' }
}
& '.\.venv\Scripts\python.exe' -m kafka_demo health
if ($LASTEXITCODE -ne 0) { throw 'Kafka is not reachable' }
& '.\.venv\Scripts\python.exe' -m kafka_demo serve --port $Port
