Set-Location (Join-Path $PSScriptRoot "..")
$python = if (Test-Path .venv/Scripts/python.exe) { ".venv/Scripts/python.exe" } else { "python" }
& $python -m pytest -q backend/tests
exit $LASTEXITCODE
