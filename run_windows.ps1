param([switch]$Token, [int]$Port = 8088)
$ErrorActionPreference = 'Stop'
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be 1..65535' }
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Prepare the project private virtual environment first.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'backend'
if ($Token) { & $python -m uav_app.cli token }
else { & $python -m uav_app.cli serve --host 127.0.0.1 --port $Port }
if ($LASTEXITCODE -ne 0) { throw "UAV application exited: $LASTEXITCODE" }
