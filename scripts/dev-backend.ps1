# Runs the backend on this PC for MANUAL testing (web app or phone on the same Wi-Fi). Local only: every outside service is faked.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\dev-backend.ps1 [-Port 8001]
# Data goes to a separate database (vidhi_dev) so it never mixes with the automatic tests (vidhi_test).
param(
  [string]$Venv = "C:\vidhi-tools\venv2",
  [string]$Mongod = "C:\vidhi-tools\mongo\mongodb-win32-x86_64-windows-7.0.14\bin\mongod.exe",
  [string]$DataDir = "C:\vidhi-tools\mongodata",
  [int]$Port = 8001,
  [switch]$RealPayments,   # use the real Stripe TEST key from backend.env instead of the fake payment gateway (still test mode; no real money)
  [string]$DbName = "vidhi_dev",
  [switch]$Lan   # also listen on the Wi-Fi address. Not needed for the phone app: it talks to the front end (yarn dev --host), which forwards /api to this server on this PC
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $Venv "Scripts\python.exe"

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is already in use. Stop that program or pass -Port." }
if (-not (Get-NetTCPConnection -LocalPort 27017 -State Listen -ErrorAction SilentlyContinue)) {
  Start-Process -FilePath $Mongod -ArgumentList "--dbpath `"$DataDir`" --bind_ip 127.0.0.1" -WindowStyle Hidden
  Start-Sleep -Seconds 4
}

# Your own keys live in backend\.env (git-ignored); load them first. The stubs below still stop real emails and charges.
$envFile = Join-Path $root "backend\.env"
if (Test-Path $envFile) { Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$($k.Trim())" (($v -replace '\s+#.*$', '').Trim().Trim('"').Trim("'")) } }  # no surrounding quotes or trailing comments in the values
$env:MONGO_URL = "mongodb://127.0.0.1:27017"; $env:DB_NAME = $DbName
$env:CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,https://localhost"; $env:APP_URL = "http://localhost:3000"; $env:COOKIE_SECURE = "false"
# Faked outside services: payments and e-mail never leave this PC. AI is REAL (keys come from backend\.env) and costs a little; AI_STUB stays off.
if (-not $RealPayments) { $env:PAYMENTS_STUB = "true" } else { Remove-Item env:PAYMENTS_STUB -ErrorAction SilentlyContinue; if (-not $env:PRO_PRICE_AMOUNT) { $env:PRO_PRICE_AMOUNT = "1999"; $env:PRO_PRICE_CURRENCY = "inr" } }
$env:EMAIL_DRY_RUN = "true";
$env:VOICE_STUB = "true"; $env:WEBPUSH_STUB = "true"; $env:TWILIO_STUB = "true"; $env:IMAGEGEN_STUB = "true"
if (-not $env:GEMINI_API_KEY) { $env:GEMINI_API_KEY = "dummy-not-real" }
if (-not $env:RESEND_API_KEY) { $env:RESEND_API_KEY = "re_dummy_not_real" }; $env:EMAIL_FROM = "VIDHI Dev <dev@example.com>"
if (-not $env:STRIPE_SECRET_KEY) { $env:STRIPE_SECRET_KEY = "sk_test_dummy" }; $env:STRIPE_WEBHOOK_SECRET = "whsec_dev_only"; $env:RESEND_WEBHOOK_SECRET = "whsec_dev_only"
$env:RAZORPAY_KEY_ID = "rzp_test_dummy"; $env:RAZORPAY_KEY_SECRET = "dev_only"; $env:RAZORPAY_WEBHOOK_SECRET = "dev_only"
$env:PAYPAL_CLIENT_ID = "paypal-dev"; $env:PAYPAL_CLIENT_SECRET = "dev_only"
$env:WEBHOOK_CRON_SECRET = "dev-only-cron-secret"; $env:LINK_SECRET = "dev-only-link-secret-not-for-production"  # secret-scan: ok (fake test value)
$env:DATA_ENCRYPTION_KEY = "ChEYHyYtNDtCSVBXXmVsc3qBiI-WnaSrsrnAx87V3OM="   # throwaway, same as the tests
$env:ENABLE_DOCS = "true"; $env:PLATFORM_ADMIN_EMAILS = "admin@example.com"
# The five Toolkit tools are switched on for manual testing (they are off by default everywhere else).
$env:AUTHORITY_CHECK_ENABLED = "true"; $env:DATE_LIST_ENABLED = "true"; $env:DEFECT_CHECK_ENABLED = "true"; $env:OLD_CODE_CHECK_ENABLED = "true"; $env:DEADLINE_ENGINE_ENABLED = "true"
$env:GRIEVANCE_OFFICER_EMAIL = "grievance-dev@example.com"; $env:SUPPORT_EMAIL = "support-dev@example.com"; $env:BUSINESS_LEGAL_NAME = "Dev Operator (local test)"

Set-Location (Join-Path $root "backend")
& $py -m uvicorn server:app --host $(if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }) --port $Port
