# Runs the backend test suite against a THROWAWAY database with dummy provider keys.
# Real keys in backend/.env are overridden (dotenv never overrides existing env vars), so tests can
# never call the real LLM / email / Stripe. Requires: a Python venv, a local mongod.
#
# Usage:  powershell -File scripts/test-backend.ps1 [-Venv C:\vidhi-tools\venv] [-Mongod <path to mongod.exe>]
[CmdletBinding(PositionalBinding = $false)]
param(
  [string]$Venv = "C:\vidhi-tools\venv2",
  [string]$Mongod = "C:\vidhi-tools\mongo\mongodb-win32-x86_64-windows-7.0.14\bin\mongod.exe",
  [string]$DataDir = "C:\vidhi-tools\mongodata",
  [int]$Port = 8001,
  [string]$DbName = "vidhi_test",   # throwaway database name; give each concurrent run its own, because every run drops its database at start (two runs on one name wiped each other's sessions and invitations)
  [switch]$Coverage,   # run the API under coverage; data goes to backend\.coverage
  [switch]$ReuseServer, # allow a server that is ALREADY listening on the port (it keeps its old code and database; results can be wrong); by default the script refuses
  [switch]$Fast,       # 4 workers, each test sent to whichever worker is free (the default pins every file to one worker). Whole suite passed this way: 10,155 tests in about 22 minutes; the 3,000 generated cases alone took half as long
  [Parameter(ValueFromRemainingArguments = $true)] $PytestArgs   # anything else goes to pytest, e.g. tests/test_rbac.py -k invite
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $Venv "Scripts\python.exe"

$env:MONGO_URL = "mongodb://127.0.0.1:27017"
$env:DB_NAME = $DbName
$env:CORS_ORIGINS = "*"
$env:APP_URL = "http://localhost:3000"
$env:GEMINI_API_KEY = "dummy-not-real"        # never used: AI_STUB replaces the model in tests
$env:GROQ_API_KEY = "dummy-not-real"; $env:OPENROUTER_API_KEY = "dummy-not-real"; $env:ELEVENLABS_API_KEY = "dummy-not-real"; $env:ANTHROPIC_API_KEY = "dummy-not-real"; $env:OLLAMA_API_KEY = "dummy-not-real"; $env:NVIDIA_API_KEY = "dummy-not-real"; $env:XAI_API_KEY = "dummy-not-real"; $env:TWILIO_ACCOUNT_SID = "ACdummy0000000000000000000000000"; $env:SENDGRID_API_KEY = ""; $env:MISTRAL_API_KEY = "dummy-not-real"; $env:ZAI_API_KEY = "dummy-not-real"   # real keys in backend/.env must never reach the tests
$env:RESEND_API_KEY = "re_dummy_not_real"       # never used: EMAIL_DRY_RUN captures mail in tests
$env:EMAIL_FROM = "VIDHI Test <test@example.com>"
$env:STRIPE_SECRET_KEY = "sk_test_dummy"        # never used: PAYMENTS_STUB replaces Stripe in tests
$env:STRIPE_WEBHOOK_SECRET = "whsec_stripe_test_secret_not_real"  # secret-scan: ok (fake test value)
$env:RESEND_WEBHOOK_SECRET = "whsec_" + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("resend-test-secret-not-real-0000"))
$env:RAZORPAY_KEY_ID = "rzp_test_dummy"; $env:RAZORPAY_KEY_SECRET = "dummy-not-real"   # never used: the stub replaces Razorpay in tests
$env:RAZORPAY_WEBHOOK_SECRET = "razorpay-test-webhook-secret-not-real"  # secret-scan: ok (fake test value)
$env:GOOGLE_STUB = "true"; $env:GOOGLE_CLIENT_ID = "stub-client"
$env:VOICE_STUB = "true"
$env:SENDGRID_WEBHOOK_PUBLIC_KEY = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEZMxiznS2kKf0XNyPGKhz7///7DvF9XUH9Cp/Y24GpHvVNRc6h1br1cmHMebYtJNtDCZNIkvOFcA48v7hYV4UxA=="   # throwaway test key (its private half is in tests/test_sendgrid.py)
$env:DIRECTORY_ENABLED = "true"; $env:WEBPUSH_STUB = "true"; $env:TWILIO_STUB = "true"; $env:TWILIO_AUTH_TOKEN = "twilio-test-token-not-real"; $env:TWILIO_WEBHOOK_URL = "http://twilio.test/api/webhooks/twilio"
$env:PAYPAL_CLIENT_ID = "paypal-test-client"; $env:PAYPAL_CLIENT_SECRET = "dummy-not-real"; $env:PAYPAL_WEBHOOK_ID = "paypal-test-webhook-id"; $env:PRO_PRICE_USD = "24"; $env:PRO_PRICE_YEARLY_AMOUNT = "19990"; $env:PRO_PRICE_USD_YEARLY = "240"
$env:IMAGE_GEN_ENABLED = "true"; $env:IMAGEGEN_STUB = "true"; $env:IMAGE_MONTHLY_CAP = "3"
$env:GRIEVANCE_OFFICER_EMAIL = "grievance-test@example.com"; $env:SUPPORT_EMAIL = "support-test@example.com"; $env:BUSINESS_LEGAL_NAME = "Test Operator Pvt Ltd (test configuration)"
$env:PLATFORM_ADMIN_EMAILS = "platform-admin-test@example.com"
$env:PLANS_FILE = "$root\backend\tests\fixtures\plans_test.json"   # the shipped plans, except that the firm plan allows only 3 people, so a test can fill it
$env:PAYMENTS_STUB = "true"                     # fake payment gateway; tests mark sessions paid in the database
$env:WEBHOOK_CRON_SECRET = "test-cron-secret-not-real"
$env:COOKIE_SECURE = "false"       # tests talk plain http to localhost
$env:BCRYPT_COST = "4"             # fast hashing in tests only
$env:RATE_LIMIT_SUPPORT = "10000"
$env:RATE_LIMIT_LAWYER_REQUEST_IP = "10000"; $env:RATE_LIMIT_DIRECTORY_LIST = "10000"; $env:RATE_LIMIT_DIRECTORY_ONE = "10000"   # public directory calls all come from one IP in the suite
$env:RATE_LIMIT_SIGNUP = "100000"    # the suite signs up many users from one IP
$env:RATE_LIMIT_LOGIN_IP = "100000"
$env:RECOVERY_ENABLED = "true"   # Legal Recovery is OFF by default (owner, 2026-11-15); the tests keep covering it, tests/test_recovery_off.py covers the default
$env:RECOVERY_FULL_FLOW = "true"   # the tests cover the full Legal Recovery flow; the default (off) is covered by tests/test_recovery_mode.py
$env:EMAIL_DRY_RUN = "true"        # capture mail in the email_outbox collection; nothing leaves the machine
$env:LINK_SECRET = "test-link-secret-not-real"
$env:DATA_ENCRYPTION_KEY = "ChEYHyYtNDtCSVBXXmVsc3qBiI-WnaSrsrnAx87V3OM="   # a throwaway key: uploads are encrypted in tests too
$env:RATE_LIMIT_EMAIL = "100000"
$env:RATE_LIMIT_VERIFY_EMAIL = "10000"   # the suite verifies many throwaway users from one IP
$env:RATE_LIMIT_CONSENT_ACT = "10000"
$env:RATE_LIMIT_CONSENT_VIEW = "10000"
$env:RATE_LIMIT_INVITE_ACCEPT = "10000"
$env:RATE_LIMIT_INVITE_VIEW = "10000"
$env:RATE_LIMIT_RESET_IP = "10000"
$env:RATE_LIMIT_FORGOT_IP = "10000"
$env:FREE_AI_PER_DAY = "5"; $env:PRO_AI_PER_DAY = "500"; $env:KNOWLEDGE_ENABLED = "true"; $env:TRUST_PROXY = "false"   # the same limits whatever backend\.env says
$env:DEFECT_CHECK_ENABLED = "true"; $env:OLD_CODE_CHECK_ENABLED = "true"; $env:DEADLINE_ENGINE_ENABLED = "true"; $env:DATE_LIST_ENABLED = "true"; $env:AUTHORITY_CHECK_ENABLED = "true"   # the Authority Check routes exist in tests; no case source token is set, so every case lookup ends as could-not-check
$env:UPLOAD_MAX_DAYS = "30"   # the upload-expiry tests run against a 30-day ceiling; nothing in the other tests is that old
$env:AUTHORITY_SOURCE_DISABLED = "true"   # tests never call the paid case source, whatever tokens backend/.env holds (an empty variable would be deleted on Windows)
$env:AI_STUB = "true"                # scripted model replies (tests queue them in the ai_stub collection); never in production
$env:AI_DAILY_CAP_INR = "100000"; $env:AI_FREE_DAILY_CAP_INR = "100000"; $env:AI_USER_DAILY_CAP_INR = "100000"; $env:AI_FREE_USER_DAILY_CAP_INR = "100000"; $env:AI_USER_WINDOW_CAP_INR = "100000"; $env:AI_USER_WEEKLY_CAP_INR = "100000"; $env:AI_USER_MONTHLY_CAP_INR = "100000"   # a test run makes thousands of scripted AI calls; the daily caps have their own tests (tests/test_ai_caps.py)
$env:LIBRARY_DIR = "$root\backend\tests\fixtures\legal_library"   # FICTIONAL test provisions, not real law
$env:HC_JUDGMENTS_DIR = "$root\backend\tests\fixtures\hc_judgments"   # FICTIONAL test judgments, not real cases
$env:JUDGMENT_INDEX_DIR = "$root\backend\tests\fixtures\no_judgment_index"   # a folder that does not exist: tests never use your real search index (they use the MongoDB text search over fictional cases)
$env:BACKEND_URL = "http://127.0.0.1:$Port"

$startedMongo = $null; $startedApi = $null
try {
  if (-not (Get-NetTCPConnection -LocalPort 27017 -State Listen -ErrorAction SilentlyContinue)) {
    New-Item -ItemType Directory -Force $DataDir | Out-Null
    $startedMongo = Start-Process $Mongod -ArgumentList "--dbpath", $DataDir, "--bind_ip", "127.0.0.1" -WindowStyle Hidden -PassThru
    Start-Sleep 5
  }
  if ((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and -not $ReuseServer) {
    throw "Something is already listening on port $Port. It runs old code and an old database, so test results would be wrong (a leftover server once made 323 tests fail, and another time 3). Stop it, use -Port for another port, or pass -ReuseServer if you really mean to test that server."
  }
  if (-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    # A fresh API gets a fresh database (it builds its own indexes at start-up); stale rate-limit buckets from earlier runs caused false 429s.
    & $py -c "import pymongo; pymongo.MongoClient('mongodb://127.0.0.1:27017').drop_database('$DbName')"
    if ($Coverage) {
      $env:COV_STOP_FILE = Join-Path $env:TEMP "vidhi-cov-stop"; Remove-Item $env:COV_STOP_FILE -ErrorAction SilentlyContinue
      $env:COV_DATA_FILE = "$root\backend\.coverage"
      $startedApi = Start-Process $py -ArgumentList "`"$root\scripts\cov_server.py`"", $Port -WorkingDirectory "$root\backend" -WindowStyle Hidden -PassThru
    } else {
      # The server's own output is kept (it holds the real error behind a "Something went wrong" 500); it only ever sees invented test data.
      $serverLog = Join-Path $env:TEMP "vidhi-test-server-$Port"
      $env:VIDHI_SERVER_LOG = "$serverLog.err.txt"   # tests/test_log_canary.py reads the server's own log from here
      $startedApi = Start-Process $py -ArgumentList "-m", "uvicorn", "server:app", "--port", $Port -WorkingDirectory "$root\backend" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$serverLog.out.txt" -RedirectStandardError "$serverLog.err.txt"
    }
    $ready = $false
    for ($i = 0; $i -lt 60 -and -not $ready; $i++) {   # wait until the server really answers, instead of guessing 10 seconds
      Start-Sleep 1
      try { $ready = (Invoke-WebRequest "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { }
    }
    if (-not $ready) { throw "The test server did not answer on port $Port within 60 seconds, so no test was run." }
  }
  Push-Location "$root\backend"
  $speed = if ($Fast) { @("-n", "4", "--dist", "load") } else { @() }   # a command-line -n / --dist overrides backend\pytest.ini, which stays as it is
  & $py -m pytest -q -p no:cacheprovider @speed @PytestArgs
  $code = $LASTEXITCODE
  Pop-Location
} finally {
  if ($startedApi -and $Coverage) {
    New-Item -ItemType File -Force $env:COV_STOP_FILE | Out-Null          # ask the server to stop itself so coverage can save its data
    $startedApi.WaitForExit(60000) | Out-Null
  }
  if ($startedApi) { Stop-Process -Id $startedApi.Id -Force -ErrorAction SilentlyContinue }
  if ($startedMongo) { Stop-Process -Id $startedMongo.Id -Force -ErrorAction SilentlyContinue }
}
exit $code
