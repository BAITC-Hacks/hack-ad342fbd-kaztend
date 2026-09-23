Set-Location (Join-Path $PSScriptRoot "..")
$python = if (Test-Path .venv/Scripts/python.exe) { ".venv/Scripts/python.exe" } else { "python" }
$port = if ($env:APP_PORT) { $env:APP_PORT } else { "8000" }
& $python -m uvicorn backend.app:app --reload --port $port
