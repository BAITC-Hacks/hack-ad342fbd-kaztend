Set-Location (Join-Path $PSScriptRoot "..")
python -m pytest -q backend\tests
