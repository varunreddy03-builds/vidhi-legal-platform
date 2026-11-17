# One script for a fresh Windows PC: installs what the test copy needs, checks it, starts it, and prints a public link that works on any network.
# Usage (from the repo folder):  powershell -ExecutionPolicy Bypass -File scripts\setup-and-share.ps1
# Add -CheckOnly to only install and check. Test data only: payments and e-mail are faked, and the AI keys are not set.
param([switch]$CheckOnly)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$tools = "C:\vidhi-tools"
New-Item -ItemType Directory -Force $tools, "$tools\mongodata", "$tools\cf" | Out-Null

function Have($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
function Refresh-Path { $env:PATH = [Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH", "User") }

# 1. Python and Node (winget ships with Windows 11)
if (-not (Have "winget")) { throw "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again." }
$py0 = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py0 -or $py0.Source -like "*WindowsApps*") { winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements; Refresh-Path }
if (-not (Have "node")) { winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements; Refresh-Path }

# 2. Backend packages in C:\vidhi-tools\venv2
if (-not (Test-Path "$tools\venv2\Scripts\python.exe")) { py -3.12 -m venv "$tools\venv2" }
& "$tools\venv2\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$tools\venv2\Scripts\python.exe" -m pip install --quiet -r "$root\backend\requirements.lock"

# 3. MongoDB (portable)
$mongod = "$tools\mongo\mongodb-win32-x86_64-windows-7.0.14\bin\mongod.exe"
if (-not (Test-Path $mongod)) {
  Invoke-WebRequest "https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.14.zip" -OutFile "$tools\mongo.zip" -UseBasicParsing
  Expand-Archive "$tools\mongo.zip" "$tools\mongo" -Force
  Remove-Item "$tools\mongo.zip"
}

# 4. Front end packages
Push-Location "$root\frontend"
if (-not (Have "yarn")) { npm install -g yarn; Refresh-Path }
yarn install --ignore-engines
Pop-Location

# 5. Tunnel program
if (-not (Test-Path "$tools\cf\cloudflared.exe")) { Invoke-WebRequest "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile "$tools\cf\cloudflared.exe" -UseBasicParsing }

# 6. Check
Write-Host "`n== Checks ==" -ForegroundColor Cyan
& "$tools\venv2\Scripts\python.exe" -c "import fastapi, motor, uvicorn; print('backend packages: OK')"
Write-Host ("mongod: " + (Test-Path $mongod)); Write-Host ("node: " + (node --version)); Write-Host ("yarn: " + (yarn --version)); Write-Host ("cloudflared: " + (& "$tools\cf\cloudflared.exe" --version))
if ($CheckOnly) { return }

# 7. Start everything
foreach ($p in 3000, 8001) { if (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) { throw "Port $p is already in use. Close that program first." } }
$env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = ".trycloudflare.com"
Start-Process powershell -ArgumentList '-ExecutionPolicy', 'Bypass', '-File', "`"$root\scripts\dev-backend.ps1`"" -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\dev-be.out" -RedirectStandardError "$env:TEMP\dev-be.err"
Start-Process powershell -ArgumentList '-NoProfile', '-Command', "Set-Location `"$root\frontend`"; yarn dev --host" -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\dev-web.out" -RedirectStandardError "$env:TEMP\dev-web.err"
$ok = $false
for ($i = 0; $i -lt 45 -and -not $ok; $i++) {
  Start-Sleep 2
  try { if ((Invoke-WebRequest http://localhost:8001/api/health -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 -and (Get-NetTCPConnection -State Listen -LocalPort 3000 -ErrorAction SilentlyContinue)) { $ok = $true } } catch {}
}
if (-not $ok) { throw "The servers did not start. Look at $env:TEMP\dev-be.err and $env:TEMP\dev-web.err" }
Remove-Item "$env:TEMP\cf.err" -ErrorAction SilentlyContinue
Start-Process "$tools\cf\cloudflared.exe" -ArgumentList 'tunnel', '--url', 'http://localhost:3000', '--no-autoupdate' -WindowStyle Hidden -RedirectStandardError "$env:TEMP\cf.err" -RedirectStandardOutput "$env:TEMP\cf.out"
$url = $null
for ($i = 0; $i -lt 30 -and -not $url; $i++) {
  Start-Sleep 2
  if (Test-Path "$env:TEMP\cf.err") { $m = Select-String -Path "$env:TEMP\cf.err" -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if ($m) { $url = $m.Matches.Value } }
}
Write-Host "`nPublic link (any network, while this PC stays on):" -ForegroundColor Green
Write-Host $url -ForegroundColor Yellow
Write-Host "To stop: close the hidden programs with  Get-Process cloudflared,node,python,mongod | Stop-Process"
