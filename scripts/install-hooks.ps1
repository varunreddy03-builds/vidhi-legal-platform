# Points git at the versioned hooks in scripts/hooks (secret scan before every commit).
Set-Location (Split-Path $PSScriptRoot -Parent)
git config core.hooksPath scripts/hooks
Write-Host "Hooks installed: $(git config core.hooksPath). Test it: stage a file containing a fake key and run git commit."
