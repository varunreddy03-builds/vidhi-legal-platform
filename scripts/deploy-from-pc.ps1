# Deploys one release to ONE server from this computer, over SSH. The same steps as .github/workflows/deploy.yml, for when GitHub Environments are not available
# (on GitHub Free a PRIVATE repository cannot use environment secrets or required reviewers; docs/STAGING_PLAN.md).
#
#   powershell -ExecutionPolicy Bypass -File scripts\deploy-from-pc.ps1 -Domain staging.example.in -HostName 203.0.113.10
#   powershell -ExecutionPolicy Bypass -File scripts\deploy-from-pc.ps1 -Domain staging.example.in -HostName 203.0.113.10 -WhatIf     (checks everything, connects to nothing)
#
# Needs: the secrets made by scripts\make-secrets.py (C:\vidhi-tools\secrets\<environment>\secrets.env and deploy_key), a server prepared with deploy\server-setup.sh, and an optional
# C:\vidhi-tools\secrets\<environment>\extra.env with the keys you add (GEMINI_API_KEY, RESEND_API_KEY, EMAIL_FROM, PLATFORM_ADMIN_EMAILS, ...: NAME=value lines). Nothing is printed.
# The first time, log in once by hand so the server's host key is remembered:   ssh -i C:\vidhi-tools\secrets\staging\deploy_key deploy@<host>     (answer yes after checking the fingerprint)
#
# STATUS: written 2026-11-05 and never run against a server. Run it for staging first, with a person watching, as the runbook says.
param(
  [ValidateSet("staging", "production")][string]$Environment = "staging",
  [Parameter(Mandatory = $true)][string]$Domain,
  [Parameter(Mandatory = $true)][string]$HostName,
  [string]$User = "deploy",
  [string]$DeployPath = "",
  [string]$SecretsDir = "",
  [switch]$SkipCiCheck,
  [switch]$WhatIf
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
if (-not $SecretsDir) { $SecretsDir = "C:\vidhi-tools\secrets\$Environment" }
if (-not $DeployPath) { $DeployPath = "/srv/vidhi-$Environment" }
$python = if (Test-Path "C:\vidhi-tools\venv2\Scripts\python.exe") { "C:\vidhi-tools\venv2\Scripts\python.exe" } else { "python" }
$key = Join-Path $SecretsDir "deploy_key"
foreach ($f in @((Join-Path $SecretsDir "secrets.env"), $key)) { if (-not (Test-Path $f)) { throw "Missing $f. Run: python scripts\make-secrets.py --out $SecretsDir" } }
foreach ($tool in @("ssh", "scp", "git")) { if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool was not found on this computer." } }
if ($Domain -match "^https?://" -or $Domain -match "/") { throw "Give the domain only, for example staging.example.in (no https:// and no path)." }

Set-Location $repo
if ((git status --porcelain --untracked-files=no) -and -not $WhatIf) { throw "There are uncommitted changes. Commit them first: the server gets the last commit (HEAD), not your working folder." }
if (-not $SkipCiCheck -and -not $WhatIf) {
  $conclusion = (gh run list --branch main --limit 1 --json conclusion --jq ".[0].conclusion" 2>$null)
  if ($conclusion -ne "success") {
    # GitHub's own tests cannot start without a payment method on the account (docs/OWNER_TODO.md), so a pass stamp from scripts\check-all.ps1 for THIS commit is accepted instead
    $sha = (git rev-parse --short HEAD).Trim()
    $stampFile = "C:\vidhi-tools\logs\check-all-$sha.ok"
    if (Test-Path $stampFile) { Write-Host "GitHub CI is '$conclusion', but this commit passed every local check: $(Get-Content $stampFile)" }
    else { throw "The latest CI run on main is '$conclusion', and there is no local pass stamp for commit $sha. Run scripts\check-all.ps1 (about 40 minutes) and try again, or pass -SkipCiCheck if you have already looked." }
  }
}

# 1. the server's .env, built in memory from the secret files and the profile; nothing is printed
function Import-Env($path) {
  foreach ($line in Get-Content $path -Encoding UTF8) {
    if ($line -match '^\s*([A-Z][A-Z0-9_]*)=(.*)$') { Set-Item -Path "env:$($Matches[1])" -Value $Matches[2].Trim() }
  }
}
Import-Env (Join-Path $SecretsDir "secrets.env")
$extra = Join-Path $SecretsDir "extra.env"
if (Test-Path $extra) { Import-Env $extra }
$env:DOMAIN = $Domain
$env:APP_URL = "https://$Domain"
$env:CORS_ORIGINS = "https://$Domain"
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("vidhi-env-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmp | Out-Null
$serverEnv = Join-Path $tmp "server.env"
try {
  & $python (Join-Path $repo "deploy\render_env.py") --profile $Environment --out $serverEnv $(if ($WhatIf) { "--check-only" })
  if ($LASTEXITCODE -ne 0) { throw "render_env.py refused (it names the problem above, never a value)." }
  if ($WhatIf) {
    Write-Host "WhatIf: the settings are complete. Would deploy commit $(git rev-parse --short HEAD) to ${User}@${HostName}:$DeployPath and check https://$Domain. Nothing was sent."
    return
  }
  $ssh = @("-i", $key, "-o", "StrictHostKeyChecking=yes", "-o", "BatchMode=yes")
  $target = "${User}@${HostName}"
  # 2. this release (the last commit) and the .env
  $release = Join-Path $tmp "release.tar.gz"
  git archive --format=tar.gz HEAD -o $release
  & ssh @ssh $target "mkdir -p '$DeployPath' && cd '$DeployPath' && mkdir -p backups secrets"
  if ($LASTEXITCODE -ne 0) { throw "Could not log in to the server. Did you log in once by hand to accept its host key (see the top of this script)?" }
  & scp @ssh $release "${target}:$DeployPath/release.tar.gz"
  & ssh @ssh $target "cd '$DeployPath' && tar -xzf release.tar.gz && rm -f release.tar.gz"
  & scp @ssh $serverEnv "${target}:$DeployPath/.env"
  & ssh @ssh $target "chmod 600 '$DeployPath/.env'"
  # 3. start it
  & ssh @ssh $target "cd '$DeployPath' && test -s secrets/backup_passphrase && docker compose --profile https up -d --build --remove-orphans"
  if ($LASTEXITCODE -ne 0) { throw "Starting the containers failed (is secrets/backup_passphrase on the server? Did deploy/server-setup.sh run?). Look at: docker compose logs --tail=200" }
} finally {
  Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
# 4. look at the live site from outside
$bash = "C:\Program Files\Git\bin\bash.exe"
if (Test-Path $bash) { & $bash "deploy/smoke.sh" "https://$Domain" } else { Write-Host "Open https://$Domain/api/health/ready yourself: it should say status ok." }
