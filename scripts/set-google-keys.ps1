# Saves the Google sign-in keys into backend\.env (git-ignored), restarts the dev backend and checks that Google sign-in is on. Nothing secret is ever printed.
# Where the keys come from, in this order:
#   1. -FromJson <path>, or the newest client_secret*.json in your Downloads folder (Google Cloud Console > the OAuth client > "Download JSON"). The file is deleted once the keys are saved.
#   2. otherwise the Client secret from the clipboard when it has the form of a Google secret, with the public Client ID given by -ClientId,
#   3. otherwise you are asked to paste the secret (hidden as you type).
param([string]$ClientId = "", [string]$FromJson = "")
$repo = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo "backend\.env"
if (-not (Test-Path $envFile)) { Write-Host "backend\.env not found at $envFile" -ForegroundColor Red; exit 1 }

$id = $ClientId; $secret = $null; $jsonUsed = $null
if (-not $FromJson) {
  $newest = Get-ChildItem (Join-Path $env:USERPROFILE "Downloads") -Filter "client_secret*.json" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($newest) { $FromJson = $newest.FullName }
}
if ($FromJson -and (Test-Path $FromJson)) {
  try {
    $web = (Get-Content $FromJson -Raw | ConvertFrom-Json).web
    if ($web.client_id -and $web.client_secret) { $id = $web.client_id; $secret = $web.client_secret; $jsonUsed = $FromJson; Write-Host "Read the keys from the downloaded file (values not shown)." }
  } catch { Write-Host "That file is not a Google credentials file." -ForegroundColor Yellow }
}
if (-not $secret) {
  if (-not $id) { Write-Host "Give the Client ID with -ClientId, or download the JSON file from Google Cloud Console." -ForegroundColor Yellow; exit 1 }
  $clip = (Get-Clipboard -Raw -ErrorAction SilentlyContinue)
  if ($clip -and $clip.Trim() -match "^GOCSPX-[A-Za-z0-9_-]{20,}$") { $secret = $clip.Trim(); Write-Host "Using the Client secret from your clipboard (value not shown)." }
  else {
    $s = Read-Host -Prompt "Paste the Google Client secret and press Enter" -AsSecureString
    $secret = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)).Trim().Trim('"').Trim("'")
  }
}
if (-not $secret) { Write-Host "No secret. Nothing was changed." -ForegroundColor Yellow; exit 1 }
if ($id -notmatch "\.apps\.googleusercontent\.com$") { Write-Host "That does not look like a Google Client ID (it should end with .apps.googleusercontent.com). Nothing was changed." -ForegroundColor Yellow; exit 1 }

$lines = [System.Collections.Generic.List[string]](Get-Content $envFile)
function SetKey($name, $value) {
  $i = $lines.FindIndex({ param($l) $l -match "^$name=" })
  if ($i -ge 0) { $lines[$i] = "$name=$value" } else { $lines.Add("$name=$value") }
}
SetKey "GOOGLE_CLIENT_ID" $id
SetKey "GOOGLE_CLIENT_SECRET" $secret
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))
Write-Host "Saved both keys to backend\.env (values not shown)." -ForegroundColor Green
if ($jsonUsed) { Remove-Item $jsonUsed -Force; Write-Host "Deleted the downloaded credentials file." }

Get-NetTCPConnection -State Listen -LocalPort 8001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-Sleep 3
Start-Process powershell -ArgumentList '-ExecutionPolicy', 'Bypass', '-File', "`"$repo\scripts\dev-backend.ps1`"" -WindowStyle Hidden -RedirectStandardOutput "$env:TEMP\dev-be.out" -RedirectStandardError "$env:TEMP\dev-be.err"
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep 3
  try {
    $o = Invoke-RestMethod http://localhost:8001/api/auth/options -TimeoutSec 3
    Write-Host ("Backend is up. Google sign-in on: " + $o.google) -ForegroundColor Green
    if ($o.google) { Write-Host "Open http://localhost:3000/login and press Continue with Google." } else { Write-Host "Google is still off: check that both values were copied whole." -ForegroundColor Yellow }
    exit 0
  } catch {}
}
Write-Host "The backend did not come up in two minutes." -ForegroundColor Red
