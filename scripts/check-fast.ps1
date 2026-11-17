# A 2-3 minute gate to run after every small change, BEFORE the 17-minute full suite.
# It runs the tests most likely to break when the answer pipeline, the guards, the knowledge layer, permissions or language handling change, plus the front-end checks.
# The complete output is saved to a log file, so a failure always has its reason on disk. Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\check-fast.ps1 [-Port 8301] [-SkipFrontend]
param([int]$Port = 8301, [switch]$SkipFrontend)
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$log = "C:\vidhi-tools\logs"; New-Item -ItemType Directory -Force $log | Out-Null
$file = Join-Path $log ("check-fast-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
$tests = "tests/test_rbac.py", "tests/test_research_honesty.py", "tests/test_analysis_guard.py", "tests/test_analysis.py", "tests/test_knowledge.py", "tests/test_films.py",
         "tests/test_evidence_and_philosophy.py", "tests/test_legal_reasoning.py", "tests/test_truth_engine.py", "tests/test_phase5.py", "tests/test_deploy_config.py"
"== backend (fast set) ==" | Tee-Object -FilePath $file
& powershell -ExecutionPolicy Bypass -File (Join-Path $root "scripts\test-backend.ps1") -Port $Port @tests 2>&1 | Tee-Object -FilePath $file -Append | Select-Object -Last 4
$backend = Select-String -Path $file -Pattern "(\d+) passed|(\d+) failed" | Select-Object -Last 1
if (-not $SkipFrontend) {
  $env:Path = "C:\vidhi-tools\node\node-v22.11.0-win-x64;" + $env:Path
  Push-Location (Join-Path $root "frontend")
  "== front end ==" | Tee-Object -FilePath $file -Append
  foreach ($step in "typecheck", "test") { & yarn -s $step 2>&1 | Tee-Object -FilePath $file -Append | Select-Object -Last 3; "yarn $step exit $LASTEXITCODE" | Tee-Object -FilePath $file -Append }
  Pop-Location
}
"Log with the full output: $file"
