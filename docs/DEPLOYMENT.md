# Deploying VIDHI

> **For the invite-only pilot, follow `docs/hosting-runbook.md`** (HTTPS proxy, encrypted backups, staging first, deploy workflow). This older guide still explains the pieces.

VIDHI is three pieces: a **web** container (nginx serving the React app and proxying `/api`), an **API**
container (FastAPI) and a **MongoDB** with authentication. It talks to three outside services you must have
accounts for: **Google Gemini** and **Anthropic Claude** (AI), **Stripe** (payments) and **Resend** (email). Nothing depends on the
Emergent platform any more.

```
 browser ──HTTPS──► [your TLS proxy / load balancer] ──► web :8080 (nginx) ──/api──► backend :8001 ──► mongo
                                                         └─ serves the app           └─► Gemini · Claude · Stripe · Resend
 scheduler (GitHub Actions or any cron) ──POST /api/cron/*  (bearer secret) ──────────┘
 Stripe / Resend ──signed webhooks──► /api/webhook/stripe · /api/webhooks/resend
```

## 1. Before you start

| You need | Why |
|---|---|
| A domain with HTTPS (a reverse proxy, load balancer or platform that terminates TLS) | Session cookies are `Secure`; emailed links must be https |
| Google AI Studio API key and an Anthropic API key | The AI (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`). One is enough to start; with both, the app switches automatically if a model fails |
| Stripe account + API keys | Pro upgrades |
| Resend account with **your sending domain verified** (SPF + DKIM) | All email. Mail from an unverified domain is rejected or lands in spam |
| A host that runs Docker (or run the two images on any container platform) | Runtime |

## 2. Configure

```bash
cp .env.example .env
```

Fill in **every** value. Generate the random secrets with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

| Variable | Notes |
|---|---|
| `MONGO_ROOT_PASSWORD`, `MONGO_APP_PASSWORD` | Letters and digits only (the app password sits inside a URL). The app connects as `MONGO_APP_USER`, which can only touch its own database |
| `APP_URL`, `CORS_ORIGINS` | The public https address, e.g. `https://app.example.in`. A `*` in `CORS_ORIGINS` is ignored |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Model defaults to `gemini-3.8-flash`. Confirm the name on Google's model list; change it here, not in code |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_SONNET_MODEL`, `ANTHROPIC_HAIKU_MODEL` | Defaults `claude-sonnet-5-5` and `claude-haiku-4-5-20251001`. Confirm exact ids on Anthropic's model list |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_FREE_MODEL` | Groq (OpenAI-compatible): last fall-back for paid users and the free plan's second model. Defaults `openai/gpt-oss-120b` (paid) and `openai/gpt-oss-20b` (free) |
| `OPENROUTER_API_KEY`, `OPENROUTER_SONNET_MODEL`, `OPENROUTER_HAIKU_MODEL` | With no `ANTHROPIC_API_KEY`, Sonnet and Haiku are reached through OpenRouter (defaults `anthropic/claude-sonnet-5.5`, `anthropic/claude-haiku-5.5`). Needs OpenRouter credit: an empty balance gives "402 Payment Required" and the app falls through to the next model |
| `GEMINI_FREE_MODEL`, `AI_ROUTE_FREE`, `FREE_AI_PER_DAY`, `FREE_AI_PLATFORM_PER_DAY` (one daily ceiling for all free accounts together), `PRO_AI_PER_DAY`, `FREE_CONTEXT_CHARS` | The plans. Free: light models only (default `gemini-3.5-flash-lite`, then Groq), 5 AI requests a day per organisation, a small reading budget, and no contract review or whole-matter analysis. Pro: everything, the strongest models |
| `AI_ROUTE`, `AI_ROUTE_<PURPOSE>` | Who answers first, e.g. `AI_ROUTE_RESEARCH=haiku,gemini,sonnet`. The app picks the model by task, invisibly to the user. Defaults: research and evidence extraction and recovery summaries = Haiku 4.5 first; matter synthesis, contract analysis and demand-notice writing = Sonnet 5.5 first; reading images and anything else = Gemini first; any input over 120,000 characters (`AI_LONG_PROMPT_CHARS`) = Gemini first for its longer context. Per task override: `AI_ROUTE_SYNTHESIZE`, `AI_ROUTE_RECOVERY_NOTICE`, etc. If a model errors, times out or returns unusable output, the next one is tried; a model that fails 3 times in a row is skipped for a minute. The log line `ai purpose=… provider=… model=…` shows who answered |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | See step 4 |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_ENV`, `PRO_PRICE_USD` | PayPal for customers outside India (step 4c) |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | UPI, cards and netbanking for customers in India (step 4b). `PAYMENT_PROVIDERS` (optional) sets which are offered and in what order |
| `PRO_PRICE_AMOUNT`, `PRO_PRICE_CURRENCY` | Pro is a **monthly subscription**. The price is server configuration, never client input: `1999` and `inr` means Rs 1,999 a month (you must be able to charge INR on your Stripe account) |
| `RESEND_API_KEY`, `EMAIL_FROM`, `RESEND_WEBHOOK_SECRET` | See step 5. `EMAIL_FROM` must be on the verified domain |
| Google, SendGrid, Twilio, ElevenLabs, image model | Optional integrations: see `docs/INTEGRATIONS.md` (what each does, which keys, which webhooks). Data handling: `docs/DATA_STORAGE.md` |
| `WEBHOOK_CRON_SECRET` | Authorises the scheduled jobs |
| `LINK_SECRET` | Signs consent / unsubscribe links. Changing it breaks links already emailed. It also derives the key that seals two-step sign-in secrets, so changing it makes people set two-step up again |
| `DATA_ENCRYPTION_KEY` | Encrypts every uploaded file at rest (AES-256-GCM). One or more comma-separated keys; the first encrypts, all can read, so you can rotate. **Back it up outside the server: a lost key means encrypted files cannot be opened.** Files saved before it was set stay readable. Generate: `python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |

`AI_STUB`, `PAYMENTS_STUB` and `EMAIL_DRY_RUN` must be **false or unset** in production: they replace the real
services with fakes (the stack never sets them).

## 3. Start

```bash
docker compose up -d --build
docker compose ps          # all three should be "healthy"/"running"
curl http://localhost:8080/api/health     # {"status":"ok"}
```

Point your TLS proxy at `web` (port 8080). The API and database are not published to the host.

The first start creates the database user from `deploy/mongo-init.js`. If you change the Mongo passwords later,
the init script does not re-run: change them inside Mongo too, or start from a fresh volume.

## 4. Stripe

1. Dashboard → Developers → API keys → put the secret key in `STRIPE_SECRET_KEY` (use `sk_test_…` first).
2. Developers → Webhooks → **Add endpoint**: `https://<your-domain>/api/webhook/stripe`, events
   `checkout.session.completed` and `checkout.session.async_payment_succeeded`. Copy the signing secret
   (`whsec_…`) into `STRIPE_WEBHOOK_SECRET`.
3. How payment is trusted: a purchase upgrades the buyer only when **Stripe itself** reports `paid` and the
   amount, currency and buyer match what the server recorded. The browser's success page cannot grant Pro.
4. Test with Stripe's test cards before switching to live keys. Receipts say "Test-mode transaction" while a
   `sk_test_` key is in use.

## 4b. Razorpay (UPI, cards, netbanking; recommended for India)

1. Create a Razorpay account and complete its business activation. Subscriptions (monthly auto-pay) is a separate product that Razorpay
   may need to switch on for your account; ask their support if the Subscriptions menu is missing.
2. Test mode first: Dashboard > Account & Settings > API keys > generate a *test* key. Put `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` in `.env`.
3. Dashboard > Webhooks > add `https://YOUR-DOMAIN/api/webhook/razorpay`, choose a secret (put it in `RAZORPAY_WEBHOOK_SECRET`) and tick the
   `subscription.*` events.
4. Pay with Razorpay's test UPI/card details from their docs. Check: Pro switches on, the receipt arrives, Settings > Cancel works.
5. Switch to live keys only after that. Customers see "Pay with UPI, card or netbanking"; Stripe stays as "Pay by international card" if both are set.

How it behaves: the customer pays on Razorpay's own page (we never see UPI or card details). Razorpay cannot send them back to the app, so Pro
switches on when Razorpay's signed webhook arrives, or when they press "check my payment" in Settings. The price is still set only by the
server (`PRO_PRICE_AMOUNT`, rupees only for Razorpay). Razorpay cannot undo a cancellation, so "Keep my subscription" is Stripe-only; with
Razorpay the person subscribes again after Pro ends.
Please confirm two things in test mode, because they follow Razorpay's documentation and could not be tried against the live service here:
that a scheduled cancellation shows as cancelling in Settings, and that a renewal appears in the billing history.

## 4c. PayPal (customers outside India, billed in US dollars)

1. developer.paypal.com > Apps & Credentials: create an app (Sandbox first), copy the Client ID and Secret into `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`.
2. Decide the monthly dollar price yourself and set `PRO_PRICE_USD` (PayPal is offered only when it is set; the app has no default price for it).
3. Webhooks (same page): add `https://YOUR-DOMAIN/api/webhook/paypal`, tick the `BILLING.SUBSCRIPTION.*` events and `PAYMENT.SALE.COMPLETED`, and copy its Webhook ID into `PAYPAL_WEBHOOK_ID`.
4. Test with a sandbox buyer account from the same dashboard; keep `PAYPAL_ENV=sandbox`. Switch to live credentials and `PAYPAL_ENV=live` only after that works.
How it behaves: PayPal sends the customer back to the app after approval and the app asks PayPal whether the first payment was taken (never trusting the browser);
PayPal's own service verifies each webhook. PayPal cancels at once, so a cancelled customer keeps Pro until the end of the month already paid;
"Keep my subscription" is not possible (they subscribe again). Please confirm in the sandbox that a renewal shows up in billing history and that
a cancellation shows as cancelling: these follow PayPal's documentation and could not be tried against the live service here.

## 5. Resend

1. Add and verify your sending domain (DNS records). Set `EMAIL_FROM`, e.g. `VIDHI <notices@mail.example.in>`.
2. Webhooks → **Add**: `https://<your-domain>/api/webhooks/resend`, events `email.delivered`, `email.bounced`,
   `email.complained`. Copy the signing secret (`whsec_…`) into `RESEND_WEBHOOK_SECRET`.
3. What this gives you: the case page shows real delivery state, a permanent bounce or spam complaint
   blocks future mail to that address, and a temporary bounce is reported without blacklisting.
   Until the webhook is connected a notice only ever shows "accepted for delivery".

## 6. Scheduled jobs (reminders, statements, retention)

The platform cron is replaced by HTTP calls, already wired in `.github/workflows/scheduled-jobs.yml`.
In the GitHub repository settings add secrets `APP_URL` (no trailing slash) and `CRON_SECRET` (same value as
`WEBHOOK_CRON_SECRET`). Schedule: statements 09:00 IST, reminders 09:30 IST, retention sweep 10:00 IST (does nothing unless an organisation chose a retention period). Run one by hand from the Actions tab
to check. Any scheduler works if it sends:

```
POST https://<your-domain>/api/cron/recovery-reminders      Authorization: Bearer <secret>
POST https://<your-domain>/api/cron/scheduled-statements    Authorization: Bearer <secret>
POST https://<your-domain>/api/cron/retention               Authorization: Bearer <secret>
```

Each job takes a database lock, so a delayed or doubled trigger cannot run it twice at once.

## 7. Verified law library

Ships **empty**. Until a lawyer adds entries, legal claims are shown as UNSUPPORTED. See
`backend/data/legal_library/README.md`. Add entries by committing reviewed files and restarting the API; CI fails
if any entry is malformed or unsigned.

## 8. Move off the old Emergent environment

1. **Rotate every secret that lived there** (the old LLM key, email key, the shared Stripe test key, the cron
   secret) - they were copied into backup archives. Revoke them at their source.
2. Data: take a `mongodump` of the old database and `mongorestore` it into the new one:
   ```bash
   mongodump --uri "<old MONGO_URL>" --db vidhi --out dump
   docker compose cp dump mongo:/tmp/dump
   docker compose exec mongo mongorestore -u "$MONGO_ROOT_USER" -p "$MONGO_ROOT_PASSWORD" --authenticationDatabase admin /tmp/dump
   ```
3. Everyone has to sign in again once (session storage changed in an earlier phase). Existing users must verify
   their email before they can email third parties. Any accountant addresses saved before consent existed are
   ignored until each person confirms.

## 9. Backups and monitoring

MongoDB holds client matters and their uploaded files (GridFS), so one database backup covers everything.
`scripts/backup.sh` makes an **encrypted** (GnuPG, AES-256) dump, checks it can be decrypted, and prunes old ones;
`scripts/restore.sh` brings one back. Run it daily from the host's cron and copy the files off the machine. Keep the
passphrase somewhere else. **Practise a restore before launch and every quarter.** The full procedure, monitoring
setup (`/api/health/ready`, request ids, what the logs do and do not contain), data requests and incident steps are
in [`docs/RUNBOOK.md`](RUNBOOK.md).

A managed MongoDB such as Atlas with point-in-time backup is a good alternative: set `MONGO_URL` to its connection
string and drop the `mongo` service from the compose file.

## 10. Go-live checklist

- [ ] `docker compose ps` healthy; `/api/health` ok over HTTPS; `/docs` returns 404
- [ ] Sign up → the verification email arrives from your domain → link works
- [ ] Recovery: create a case, add addresses, draft a notice (needs Gemini), email it to yourself, check the status
- [ ] Add an accountant (your own second address) → consent email → confirm → statement copy has an unsubscribe link
- [ ] Stripe: test purchase upgrades the account; webhook shows as delivered in the Stripe dashboard
- [ ] Resend: a bounce test (send to a bounce-simulator address) shows BOUNCED on the case
- [ ] Scheduled jobs: run all three once from the Actions tab; `/api/health/ready` shows `"status":"ok"`
- [ ] An uptime monitor watches `/api/health/ready`; a backup ran and a restore drill succeeded (docs/RUNBOOK.md)
- [ ] The privacy notice (`/privacy`) was reviewed by a lawyer; then set `REVIEWED_BY_LAWYER = true` in `frontend/src/pages/Privacy.tsx`
- [ ] You decided the retention period (Settings > Data & privacy) - or left it off
- [ ] Response headers on `/` include the Content-Security-Policy; browser console is clean
- [ ] Old secrets revoked; `.env` is not in git; backups run and a restore was tested

## 11. Known gaps

- Gemini, Claude, Stripe and Resend were integrated against their documentation and exercised with recording fakes and
  real signature verification; **the first run with live keys is the real test** - do it with test keys first.
- Razorpay is not integrated. Payments go through `lib/payments_gateway.py`; a second gateway implementing
  `create_checkout` / `retrieve` / webhook verification can be added without touching the routes.
- No log shipping or alert delivery is built in: point an uptime monitor at `/api/health/ready` and read the container logs by request id (docs/RUNBOOK.md).
- The privacy notice describes what the software does; it is a draft until a lawyer reviews it against the operator's actual duties.
- The AI can still be wrong; every claim is checked in code against exact quotes and the verified library, and the
  UI says what could not be verified - lawyers decide.
