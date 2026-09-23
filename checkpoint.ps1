param([Parameter(Mandatory=$true)][string]$Tag, [string]$Message = "checkpoint")
$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
git add -A
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { git commit --allow-empty -m "checkpoint $Tag @ $stamp`: $Message" }
else { git commit -m "checkpoint $Tag @ $stamp`: $Message" }
git tag -f $Tag -m $Message
git push origin HEAD
git push -f origin $Tag
Write-Host "OK: $Tag @ $stamp pushed. Check GitHub!"
