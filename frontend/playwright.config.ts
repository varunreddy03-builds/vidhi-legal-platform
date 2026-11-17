import { defineConfig } from "@playwright/test";

/**
 * Browser tests (real browser, real backend with its outside services replaced by captures: no AI, email, payment or SMS provider is called).
 *   CI:     `npx playwright install --with-deps chromium`, then `yarn e2e` (starts the backend and the front end itself).
 *   Local:  start the backend on :8001 and `yarn dev` on :3000 yourself, then `PW_CHANNEL=msedge yarn e2e` (uses the Edge or Chrome already installed;
 *           PW_CHANNEL=chrome for Chrome) so no browser has to be downloaded.
 * The tests create their own throwaway accounts in a throwaway database (DB_NAME below), never in a real one.
 */
const backendEnv = {
  MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017",
  DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e",
  CORS_ORIGINS: "http://localhost:3000",
  APP_URL: "http://localhost:3000",
  COOKIE_SECURE: "false", // plain http on localhost
  PLATFORM_ADMIN_EMAILS: "platform-admin-test@example.com", // the e2e operator account (e2e/legal-review.e2e.ts seeds it straight in the database)
  AUTHORITY_SOURCE_DISABLED: "true", // e2e never calls the paid case source, whatever tokens backend/.env holds
  AI_DAILY_CAP_INR: "100000", AI_FREE_DAILY_CAP_INR: "100000", AI_USER_DAILY_CAP_INR: "100000", AI_FREE_USER_DAILY_CAP_INR: "100000", AI_USER_WINDOW_CAP_INR: "100000", AI_USER_WEEKLY_CAP_INR: "100000", AI_USER_MONTHLY_CAP_INR: "100000", // browser tests make many scripted AI calls on one persistent database
  AI_STUB: "true", PAYMENTS_STUB: "true", EMAIL_DRY_RUN: "true", VOICE_STUB: "true", TWILIO_STUB: "true", WEBPUSH_STUB: "true", GOOGLE_STUB: "true", IMAGEGEN_STUB: "true",
  DATA_ENCRYPTION_KEY: "ChEYHyYtNDtCSVBXXmVsc3qBiI-WnaSrsrnAx87V3OM=", // a throwaway key, the same as the backend tests: uploads and their extracted text are encrypted in browser tests too
  GEMINI_API_KEY: "dummy-not-real", RESEND_API_KEY: "re_dummy_not_real", EMAIL_FROM: "VIDHI Test <test@example.com>",
  RECOVERY_ENABLED: "true", // Legal Recovery is off by default; the older tests still cover it, legal-recovery-off.e2e.ts covers the default
  RECOVERY_FULL_FLOW: "true", // the full Legal Recovery flow is on here; recovery-small.e2e.ts covers the default (off) by answering /api/recovery/options itself
  BCRYPT_COST: "4", RATE_LIMIT_SIGNUP: "1000", RATE_LIMIT_LOGIN_IP: "1000", RATE_LIMIT_SUPPORT: "10000", WEBHOOK_CRON_SECRET: "e2e-cron-secret-not-real",
};

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts", // not *.spec.ts: the unit-test runner would pick those up
  outputDir: process.env.E2E_OUTPUT_DIR ?? "test-results", // a cloud-synced folder can refuse to let the runner clear this one: point it somewhere local
  timeout: 60_000,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: process.env.PW_CHANNEL || undefined,
    trace: "retain-on-failure",
  },
  webServer: process.env.E2E_NO_SERVERS
    ? undefined
    : [
        {
          command: process.env.E2E_BACKEND_CMD ?? "python -m uvicorn server:app --host 127.0.0.1 --port 8001",
          cwd: "../backend",
          url: "http://127.0.0.1:8001/api/health",
          env: { ...(process.env as Record<string, string>), ...backendEnv },
          reuseExistingServer: true,
          timeout: 120_000,
        },
        { command: "yarn dev", url: "http://localhost:3000", reuseExistingServer: true, timeout: 120_000 },
      ],
});