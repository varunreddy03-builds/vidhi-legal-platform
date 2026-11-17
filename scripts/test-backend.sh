#!/usr/bin/env bash
# Linux/macOS/CI equivalent of scripts/test-backend.ps1: starts the API against a THROWAWAY database with dummy
# provider keys and scripted AI / payments / email, then runs the backend suite.
# Needs: Python deps installed (backend/requirements-dev.txt) and a MongoDB reachable at $MONGO_HOST (default 127.0.0.1:27017).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8001}"
PYTHON="${PYTHON:-python}"

export MONGO_URL="mongodb://${MONGO_HOST:-127.0.0.1:27017}"
export DB_NAME="vidhi_test"
export CORS_ORIGINS="*"                       # ignored by the app (a wildcard is never allowed with credentials)
export APP_URL="http://localhost:3000"
export GEMINI_API_KEY="dummy-not-real"        # never used: AI_STUB replaces the model
export RESEND_API_KEY="re_dummy_not_real"     # never used: EMAIL_DRY_RUN captures mail
export EMAIL_FROM="VIDHI Test <test@example.com>"
export STRIPE_SECRET_KEY="sk_test_dummy"      # never used: PAYMENTS_STUB replaces Stripe
export STRIPE_WEBHOOK_SECRET="whsec_stripe_test_secret_not_real"  # secret-scan: ok (fake test value)
export RESEND_WEBHOOK_SECRET="whsec_$(printf 'resend-test-secret-not-real-0000' | base64)"
export WEBHOOK_CRON_SECRET="test-cron-secret-not-real"
export LINK_SECRET="test-link-secret-not-real"
export DATA_ENCRYPTION_KEY="ChEYHyYtNDtCSVBXXmVsc3qBiI-WnaSrsrnAx87V3OM="   # a throwaway key: uploads are encrypted in tests too
export COOKIE_SECURE="false"                  # tests talk plain http to localhost
export BCRYPT_COST="4"                        # fast hashing in tests only
export RATE_LIMIT_SIGNUP="100000" RATE_LIMIT_LOGIN_IP="100000" RATE_LIMIT_EMAIL="100000"
export RATE_LIMIT_VERIFY_EMAIL="10000" RATE_LIMIT_CONSENT_ACT="10000" RATE_LIMIT_CONSENT_VIEW="10000"
export RAZORPAY_KEY_ID="rzp_test_dummy" RAZORPAY_KEY_SECRET="dummy-not-real" RAZORPAY_WEBHOOK_SECRET="razorpay-test-webhook-secret-not-real"  # secret-scan: ok (fake test value)
export GOOGLE_STUB="true" GOOGLE_CLIENT_ID="stub-client"
export VOICE_STUB="true"
export SENDGRID_WEBHOOK_PUBLIC_KEY="MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEZMxiznS2kKf0XNyPGKhz7///7DvF9XUH9Cp/Y24GpHvVNRc6h1br1cmHMebYtJNtDCZNIkvOFcA48v7hYV4UxA=="
export DIRECTORY_ENABLED="true" WEBPUSH_STUB="true" TWILIO_STUB="true" TWILIO_AUTH_TOKEN="twilio-test-token-not-real" TWILIO_WEBHOOK_URL="http://twilio.test/api/webhooks/twilio"
export PAYPAL_CLIENT_ID="paypal-test-client" PAYPAL_CLIENT_SECRET="dummy-not-real" PAYPAL_WEBHOOK_ID="paypal-test-webhook-id" PRO_PRICE_USD="24" PRO_PRICE_YEARLY_AMOUNT="19990" PRO_PRICE_USD_YEARLY="240"
export IMAGE_GEN_ENABLED="true" IMAGEGEN_STUB="true" IMAGE_MONTHLY_CAP="3"
export GRIEVANCE_OFFICER_EMAIL="grievance-test@example.com" SUPPORT_EMAIL="support-test@example.com" BUSINESS_LEGAL_NAME="Test Operator Pvt Ltd (test configuration)"
export PLATFORM_ADMIN_EMAILS="platform-admin-test@example.com"
export RATE_LIMIT_SUPPORT="10000" RATE_LIMIT_LAWYER_REQUEST_IP="10000" RATE_LIMIT_DIRECTORY_LIST="10000" RATE_LIMIT_DIRECTORY_ONE="10000"
export AI_DAILY_CAP_INR="100000" AI_FREE_DAILY_CAP_INR="100000" AI_USER_DAILY_CAP_INR="100000" AI_FREE_USER_DAILY_CAP_INR="100000" AI_USER_WINDOW_CAP_INR="100000" AI_USER_WEEKLY_CAP_INR="100000" AI_USER_MONTHLY_CAP_INR="100000"   # a test run makes thousands of scripted AI calls; the daily caps have their own tests (tests/test_ai_caps.py)
export AI_STUB="true" PAYMENTS_STUB="true" EMAIL_DRY_RUN="true"
export LIBRARY_DIR="$ROOT/backend/tests/fixtures/legal_library"   # FICTIONAL test provisions, not real law
export HC_JUDGMENTS_DIR="$ROOT/backend/tests/fixtures/hc_judgments"   # FICTIONAL test judgments, not real cases
export GROQ_API_KEY="dummy-not-real" OPENROUTER_API_KEY="dummy-not-real" ELEVENLABS_API_KEY="dummy-not-real" ANTHROPIC_API_KEY="dummy-not-real" OLLAMA_API_KEY="dummy-not-real" NVIDIA_API_KEY="dummy-not-real" XAI_API_KEY="dummy-not-real" MISTRAL_API_KEY="dummy-not-real" ZAI_API_KEY="dummy-not-real"
export TWILIO_ACCOUNT_SID="ACdummy0000000000000000000000000" SENDGRID_API_KEY=""   # real keys in backend/.env must never reach the tests
export RATE_LIMIT_INVITE_ACCEPT="10000" RATE_LIMIT_INVITE_VIEW="10000" RATE_LIMIT_RESET_IP="10000" RATE_LIMIT_FORGOT_IP="10000"
export FREE_AI_PER_DAY="5" PRO_AI_PER_DAY="500" KNOWLEDGE_ENABLED="true" TRUST_PROXY="false"   # the same limits whatever backend/.env says
export DEFECT_CHECK_ENABLED="true"
export OLD_CODE_CHECK_ENABLED="true"
export DEADLINE_ENGINE_ENABLED="true"
export DATE_LIST_ENABLED="true"
export PLANS_FILE="$ROOT/backend/tests/fixtures/plans_test.json"   # the shipped plans, except that the firm plan allows only 3 people, so a test can fill it (same as scripts/test-backend.ps1)
export JUDGMENT_INDEX_DIR="${TMPDIR:-/tmp}/vidhi-no-judgment-index"   # an empty place: the tests never use a real judgment search index (same as scripts/test-backend.ps1)
export RECOVERY_ENABLED="true" RECOVERY_FULL_FLOW="true"   # Legal Recovery is OFF by default; the tests keep covering it (tests/test_recovery_off.py covers the default). Same as scripts/test-backend.ps1
export AUTHORITY_CHECK_ENABLED="true"       # the Authority Check routes exist in tests
export AUTHORITY_SOURCE_DISABLED="true"     # tests never call the paid case source, whatever tokens backend/.env holds
export UPLOAD_MAX_DAYS="30"                 # the upload-expiry tests run against a 30-day ceiling
export BACKEND_URL="http://127.0.0.1:$PORT"

export VIDHI_SERVER_LOG="${TMPDIR:-/tmp}/vidhi-api.log"   # tests/test_log_canary.py reads the server's own log from here
cd "$ROOT/backend"
"$PYTHON" -m uvicorn server:app --port "$PORT" >"$VIDHI_SERVER_LOG" 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS "$BACKEND_URL/api/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "$BACKEND_URL/api/health" >/dev/null || { echo "API did not start:"; tail -n 40 "${TMPDIR:-/tmp}/vidhi-api.log"; exit 1; }

"$PYTHON" -m pytest -q -p no:cacheprovider "$@"
