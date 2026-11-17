# One command that does what GitHub's automatic tests (CI) would do, on THIS computer, for the commit you are on.
#
#   powershell -ExecutionPolicy Bypass -File scripts\check-all.ps1            the whole thing (about 40 minutes): frontend checks, the full backend suite, the full browser suite
#   powershell -ExecutionPolicy Bypass -File scripts\check-all.ps1 -Quick     frontend checks and a short backend sample (a few minutes): to try the script, not a release check
#
# When every step passes it writes a stamp for this exact commit: C:\vidhi-tools\logs\check-all-<commit>.ok. scripts\deploy-from-pc.ps1 accepts that stamp instead of a green GitHub run
# (GitHub's own tests cannot start while the account has no payment method: docs/OWNER_TODO.md). A -Quick run never writes the stamp.
# Logs go to C:\vidhi-tools\logs\check-all-<time>-*.txt. Nothing is sent anywhere and nothing is changed in the repository.
param([switch]$Quick, [int]$Port = 8561, [string]$DbName = "", [string]$Logs = "C:\vidhi-tools\logs")
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$node = "C:\vidhi-tools\node\node-v22.11.0-win-x64"
$python = if (Test-Path "C:\vidhi-tools\venv2\Scripts\python.exe") { "C:\vidhi-tools\venv2\Scripts\python.exe" } else { "python" }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $DbName) { $DbName = "check_$stamp".Replace("-", "_") }
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$sha = (git rev-parse --short HEAD).Trim()
$dirty = @(git status --porcelain --untracked-files=no -- . ':(exclude)artifacts').Count -gt 0  # the screenshots under artifacts/ change on every browser run and are not code
if ($dirty) { Write-Host "WARNING: there are uncommitted changes. The stamp (if any) names commit $sha, so it is only written for a clean tree." -ForegroundColor Yellow }
$results = [ordered]@{}
function Step($name, [scriptblock]$run, $log) {
  Write-Host "== $name ..." -NoNewline
  $started = Get-Date
  & $run *> $log
  $code = $LASTEXITCODE
  $mins = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
  $script:results[$name] = @{ ok = ($code -eq 0); minutes = $mins; log = $log }
  Write-Host (" {0} ({1} min)" -f $(if ($code -eq 0) { "PASS" } else { "FAIL, see $log" }), $mins)
}

$env:PATH = "$node;" + $env:PATH
Set-Location "$repo\frontend"
Step "frontend typecheck" { yarn -s typecheck } "$Logs\check-all-$stamp-typecheck.txt"
Step "frontend lint (errors only)" { $o = yarn -s lint 2>&1; $o; if ($o -match " error ") { $global:LASTEXITCODE = 1 } else { $global:LASTEXITCODE = 0 } } "$Logs\check-all-$stamp-lint.txt"
Step "frontend unit tests" { yarn -s vitest run } "$Logs\check-all-$stamp-vitest.txt"
Set-Location $repo

$quickFiles = @("tests/test_claim_attacks.py", "tests/test_pilot_kit.py", "tests/test_recovery_guide.py", "tests/test_erase_user.py", "tests/test_log_leaks.py")
if (-not (Get-NetTCPConnection -LocalPort 27017 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath "C:\vidhi-tools\mongo\mongodb-win32-x86_64-windows-7.0.14\bin\mongod.exe" -ArgumentList '--dbpath "C:\vidhi-tools\mongodata" --bind_ip 127.0.0.1' -WindowStyle Hidden
  Start-Sleep 8
}
if ($Quick) {
  Step "backend sample" { powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-backend.ps1 -Fast -Port $Port -DbName $DbName @quickFiles } "$Logs\check-all-$stamp-backend.txt"
} else {
  Step "backend full suite" { powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test-backend.ps1 -Fast -Port $Port -DbName $DbName } "$Logs\check-all-$stamp-backend.txt"
  Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  Start-Sleep 3
  Set-Location "$repo\frontend"
  $env:PW_CHANNEL = "msedge"
  $env:E2E_BACKEND_CMD = "$python -m uvicorn server:app --host 127.0.0.1 --port 8001"
  $env:AUTHORITY_CHECK_ENABLED = "true"; $env:DATE_LIST_ENABLED = "true"; $env:DEFECT_CHECK_ENABLED = "true"; $env:OLD_CODE_CHECK_ENABLED = "true"; $env:DEADLINE_ENGINE_ENABLED = "true"
  Step "browser full suite" { yarn e2e --output=C:/vidhi-tools/pw-results } "$Logs\check-all-$stamp-browser.txt"
  Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  Set-Location $repo
}

$failed = @($results.GetEnumerator() | Where-Object { -not $_.Value.ok })
Write-Host ""
foreach ($r in $results.GetEnumerator()) { Write-Host ("  {0,-30} {1}" -f $r.Key, $(if ($r.Value.ok) { "pass" } else { "FAIL" })) }
if ($failed.Count -eq 0 -and -not $Quick -and -not $dirty) {
  Set-Content -Path "$Logs\check-all-$sha.ok" -Value "commit $sha passed every step on $(Get-Date -Format s)" -Encoding ASCII
  Write-Host "All steps passed. Stamp written: $Logs\check-all-$sha.ok" -ForegroundColor Green
  exit 0
}
if ($failed.Count -eq 0) { Write-Host "All steps passed, but no stamp was written ($(if ($Quick) { 'quick run' } else { 'uncommitted changes' }))." -ForegroundColor Yellow; exit 0 }
Write-Host "Some steps FAILED: no stamp." -ForegroundColor Red
exit 1
