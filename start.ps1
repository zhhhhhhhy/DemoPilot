$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $projectRoot "backend"
$frontendRoot = Join-Path $projectRoot "frontend"

Write-Host "Starting DemoPilot API on http://127.0.0.1:8091" -ForegroundColor Cyan
Start-Process -FilePath "uv" -ArgumentList @("run", "uvicorn", "--env-file", "..\.env", "--app-dir", "src", "demopilot.main:app", "--host", "127.0.0.1", "--port", "8091") -WorkingDirectory $backendRoot -WindowStyle Hidden

Write-Host "Starting DemoPilot web app on http://127.0.0.1:5173" -ForegroundColor Cyan
Set-Location -LiteralPath $frontendRoot
npm.cmd run dev
