Set-Location (Join-Path $PSScriptRoot "..")
python -m uvicorn backend.app:app --reload --port 8000
