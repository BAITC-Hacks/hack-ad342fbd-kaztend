Set-Location (Join-Path $PSScriptRoot "..")
node --test tests/frontend-state.test.cjs
exit $LASTEXITCODE
