# Ежечасный чекпоинт (Windows / PowerShell). Использование:
#   .\checkpoint.ps1 h1 "core agent loop works end-to-end"
param(
  [Parameter(Mandatory=$true)][string]$Tag,
  [string]$Message = "checkpoint"
)
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
  Write-Host "Нет изменений — создаю пустой коммит-чекпоинт"
  git commit --allow-empty -m "checkpoint $Tag @ $stamp`: $Message"
} else {
  git commit -m "checkpoint $Tag @ $stamp`: $Message"
}
git tag -f $Tag -m $Message
git push origin HEAD
git push -f origin $Tag
Write-Host "OK: $Tag @ $stamp запушен. Проверь на GitHub!"
