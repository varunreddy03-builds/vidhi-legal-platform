<!-- Verbatim copy of the former CLAUDE.md (architecture, conventions, status). CLAUDE.md now holds only the owner rules and commands. -->

# VIDHI — project brief for Claude

**Start every session by reading `docs/PROJECT_MEMORY.md` (history, decisions, status, how to run) and end it by updating that file.** The owner's own words are in `docs/history/OWNER_REQUESTS_LOG.md`.

VIDHI is an AI legal platform for India with two modules sharing auth, DB and AI:

- **Legal Intelligence** (lawyers; Free plan with limits, or Pro at Rs 1,999 a month): matters, documents + media evidence, facts, timeline, evidence items,
  people, source-checked research, drafting, graph, audit log.
- **Legal Recovery** (non-lawyers; free): proof, case summary, demand notice, interest + time-limit help, payments,
  reminders/statements, accountant copies, lawyer handoff (creates a Matter in Intelligence).

Tagline: AI assists. Sources support. Graphs connect. Logic verifies. Lawyers decide.

## Rules for the whole project (from the owner — do not relax)

1. **Never invent law, sections or case citations.** A legal claim is `VERIFIED` only if the exact source text is in
   our verified library AND it has been checked against ALL documents in the matter. Otherwise show
   `PARTIALLY_VERIFIED` or `UNSUPPORTED`. A model's own opinion never counts as verification.
2. **The app flags inconsistencies; it never says someone "lied".** Neutral wording only. Lawyers decide.
3. **Do not change the existing UI style, names or core flows.** The owner has allowed only the BUTTON look (`btn-orbit`, `btn-plate`, `btn-lamp`, `btn-ember` in `index.css`, used through `components/ui/button.tsx`) to be restyled, plus light/dark themes and languages. Keep product names (VIDHI, Legal Intelligence, Legal Recovery) untranslated and keep the look neutral and commercial (it must work for users in any country).
4. **Never put secrets in code or the frontend. Never print or commit `.env`.** Refer to key names only, never values.
5. **Work in small steps. Run tests after each step. Tell the owner what changed.**

## How the rules are enforced in code (keep it that way)

- `lib/verify.py` decides claim status; the model only proposes. Quotes are normalised-exact-matched against the
  source (`find_quote`). "There is no X" claims need an exhaustive scan of every document.
- `lib/matter_context.py`: the model sees every document (index) and all text if it fits, else every document gets
  its best passage and the answer reports exactly what was not read. VERIFIED needs complete coverage.
- `lib/library.py` + `backend/data/legal_library/`: the ONLY source that can verify law. Ships empty; entries are
  reviewed JSON with exact text, source, version, SHA-256 and a named verifier. Never add law from memory or from AI.
- `lib/neutral.py` strips honesty judgements from AI text. `lib/limitation.py` has no periods of its own
  (verified rules only). `lib/interest.py` is arithmetic on a user-entered rate. `lib/notice_checks.py` blocks
  notices with blanks or legal references.
- Outbound email goes through `lib/outbound.py::send_logged` only: sender must be email-verified, notices need
  preview + confirmation, accountants need consent, bounces/complaints suppress addresses, every send is logged.
- Payments (`lib/payments_gateway.py`, `routers/payments.py`): the server owns the price (env); an upgrade needs
  Stripe to report `paid` AND amount/currency/buyer to match. Webhooks are signature-verified (Stripe, Resend/Svix).
- Failed/unparseable model replies raise (`lib/ai.py`); they are never shown as "I am unsure".

## Stack

- Frontend: React 19 + Vite + TypeScript (strict) + Tailwind v4 + shadcn/base-ui, TanStack Query. Calls relative `/api/*`.
- Backend: FastAPI (Python 3.11) + Motor/MongoDB (uploads in GridFS). Cookie sessions, token stored hashed.
- AI: Gemini (`google-genai`) + Claude Sonnet/Haiku (`anthropic`), routed per purpose with automatic fall-through in `lib/ai.py`
  (`AI_ROUTE*` env; research = Haiku first). The model only drafts; `lib/verify.py` still decides every claim status.
- Plans (`lib/plans.py`, `lib/auth.entitlement_for`): Legal Intelligence is FREE (light models only, a few AI requests a day, a small
  reading budget, no contract review or whole-matter synthesis) or PRO (a monthly Stripe subscription; Pro lasts to the paid-until
  date + 2 days' grace). Legal Recovery is free for everyone and never gated. Every AI call in Intelligence goes through
  `gate_ai` and passes its tier to `ask_json`; the free tier can never reach a Claude model.
- Payments: Stripe (official SDK), Razorpay (`lib/razorpay_gateway.py`, UPI/cards/netbanking) and PayPal (`lib/paypal_gateway.py`, US dollars via `PRO_PRICE_USD`; each checkout records its `provider`, webhooks `/webhook/stripe` and `/webhook/razorpay` are both signature-verified and re-ask the provider), subscription mode; webhooks re-ask Stripe for the subscription instead of trusting the event. Email: Resend (HTTP API) + Svix-signed delivery webhook.
- Jobs: `.github/workflows/scheduled-jobs.yml` POSTs `/api/cron/*` (bearer secret; DB lock per job).
- Deploy: `docker-compose.yml` (web nginx with CSP + API + authenticated MongoDB). See `docs/DEPLOYMENT.md`.
- No Emergent code or dependency remains (a test enforces it).

## Layout

```
backend/   server.py · lib/ · routers/ · models/schemas.py · data/legal_library/ · scripts/library_add.py · tests/
frontend/  src/pages · src/components (recovery/, matter/, ui/) · src/lib (api, format, types, interaction)
deploy/    nginx.conf, security-headers.conf (CSP), mongo-init.js     docs/DEPLOYMENT.md  docs/RUNBOOK.md     AUDIT.md
scripts/   test-backend.{sh,ps1}, backup.sh, restore.sh
```

Tenancy: every user belongs to one `organization_id`; every query must filter by it; cross-org tests exist for
every ID route (`tests/test_tenancy.py`, plus per-feature files).

## Commands

```
backend:   pip install -r backend/requirements-dev.txt -c backend/requirements.lock
           bash scripts/test-backend.sh        # or: powershell -File scripts/test-backend.ps1  (Windows)
           (uses a throwaway DB + AI_STUB / PAYMENTS_STUB / EMAIL_DRY_RUN; needs a local MongoDB)
frontend:  cd frontend && yarn typecheck && yarn lint && yarn test && yarn build
```

Local toolchain on the owner's Windows machine (portable, no admin): `C:\vidhi-tools\` (Python venvs, Node + yarn,
MongoDB). Git is in `C:\Program Files\Git\cmd`. Run tests from a SHORT path if you see "file not found" on long
paths (the session folder is deeper than Windows' 260-character limit; CI paths are short).

## Conventions

- New routes: add to the `/api` router; call the org-scoped getter (`get_matter`, `_get_case`, or an explicit
  `organization_id` filter) and add a cross-organization negative test.
- AI features: structured JSON, statuses computed server-side, quotes validated, `human_review_required` unless fully
  verified; test with the scripted model (`AI_STUB`, helpers in `tests/conftest.py`).
- Dates shown to users go through `frontend/src/lib/format.ts` (e.g. `10 Jun 2026`). Money in PDFs uses "Rs" (the PDF
  base fonts have no rupee glyph); web and email use ₹.
- No test/demo text in user-facing UI.

- Roles (`lib/rbac.py`): OWNER / ADMIN / LAWYER / MEMBER, one `POLICY` table keyed on route templates, enforced for every
  `/api` route by the router-level `enforce_policy`. A new route needs NO extra code to be protected (default by method)
  but sensitive ones (AI, email, billing, org admin) must be listed in `POLICY`; `tests/test_rbac.py` fails on an
  unlisted public route and checks the role matrix. The UI hides buttons from `capabilities`; the server decides.
- Deleting (`lib/purge.py`): matter, case and organisation deletes all go through it - never write a new `delete_many` chain.
  Retention (`lib/retention.py`) is OFF unless an org sets it, notifies owners first (30 days), skips legal hold.
- Recovery money and law: lib/balance.py does all case arithmetic (owner's amount only; charges need a written basis);
  lib/route_checks.py raises warnings and never states law; routers/recovery_intake.py drafts notices where the AI writes
  wording and code inserts the statement of account and enclosures. lib/notice_checks.py blocks blanks, legal references and threats.
- Notice versions and approval (lib/notice_workflow.py, routers/recovery_notice.py): every text change is a new immutable version;
  approval is bound to one version's hash and cleared on any edit; email sending is refused unless the current text is approved.
  An advocate review is only ever the reviewer's own recorded declaration - never write a name, signature or registration into a notice.
- Delivery (lib/delivery.py, routers/recovery_delivery.py): state only what the records show. Never write that a notice was
  received, read or legally served; a tracking update counts as receipt only if it says delivered; scheduled jobs must never email the customer.
- Translations (lib/translation.py, routers/recovery_translation.py): figures and names are protected by code, never trusted to the model;
  the English notice stays authoritative; a translation is bound to one English version and needs its own approval before it is emailed.
- Logs: one access line per request by route TEMPLATE (never raw paths/queries); no personal data in logs.

- Languages and themes: English plus all 22 Eighth-Schedule languages (`frontend/src/lib/languages.ts`, catalogs in `src/lib/i18n/locales`, English keys in `en.ts`, `useT()`). "full" catalogs must translate every key (a test enforces it); "core" ones (sa, mai, kok, doi, brx, ks, sd, mni, sat) cover menus/sign-in/home and are shown as Beta until native speakers review them; anything missing falls back to English. Urdu, Kashmiri and Sindhi are right-to-left. Theme is dark/light/system (`lib/theme.tsx`, `public/theme-init.js` avoids a flash). Choices are saved on the account (`PATCH /auth/preferences`). `/research` takes `language` so answers come back in it, with quotes and ids unchanged. Notice translations offer all 22 languages and still need a fluent reader's approval.
- Security additions: two-step sign-in with an authenticator app (`lib/totp.py`, `lib/twofactor.py`, `routers/twofactor.py`; login returns 428 until the code is given; codes work once; recovery codes are hashed) and encryption of uploaded files at rest (`lib/crypto.py`, `lib/filestore.py` - every upload read/write goes through `filestore`, never GridFS directly). nginx gzips text.

- Sign-in and integrations (see `docs/INTEGRATIONS.md`, `docs/DATA_STORAGE.md`): Google OIDC (`lib/google_auth.py`, PKCE + state + nonce, links by verified email, never skips the app's own two-step), 30-day sessions renewed in `/auth/me`; SendGrid beside Resend (`lib/email.py provider()`, signed `/webhooks/sendgrid`); Twilio opt-in alerts to the OWNER's verified phone only (`lib/twilio_sms.py`, `lib/phone_alerts.py` - never to a customer, no names/amounts in texts); voice (`lib/voice.py`: ElevenLabs/Gemini speech-to-text, ElevenLabs text-to-speech, browser fallback, audio never stored); rare Pro-only illustrations (`lib/imagegen.py`, off by default, capped, refuses real people/documents/evidence); instant rules engine (`lib/decide.py`: scoring/filtering/categorising with reasons; no AI).

- Newer modules (see `docs/FINAL_REPORT.md` for the full list and what is still open):
  * Roles: staff `OWNER/ADMIN/LAWYER/MEMBER` plus `CLIENT` (portal only: holds just `account` and `portal`; `routers/portal.py`; a test walks every route with a client session). Every signed-in-user route is `account`, not `read`.
  * Templates (`lib/templates.py`, `data/templates/pending|IN`, `scripts/template_review.py`): filled by code, no statute names (a test scans), unreviewed until a lawyer approves; edits after review revert them.
  * Dates and reminders (`lib/deadlines.py`, `lib/reminders.py`, `lib/webpush.py`, cron `/api/cron/deadline-reminders`): user-entered dates only; text/push messages are generic; `public/sw.js` caches nothing.
  * Conflict check (`lib/conflicts.py`), lawyer directory (`lib/directory.py`, OFF unless `DIRECTORY_ENABLED=true`, needs a lawyer's advice first), e-sign extension point (`lib/esign.py`, nothing signs), sample case (`routers/demo.py`).
  * Payments: yearly plan only when its price env is set; refunds are RECORDED by the operator after refunding at the provider (`/admin/payments`); NO GST, NO coupons (decisions pending: `docs/PAYMENTS.md`). Price structure by country: `lib/pricing.py`.
  * Help centre and tour: `src/lib/help/*.ts` (English reference + hi, te, ta, bn, mr, gu, all unreviewed translations, a test enforces identical structure).
  * Browser tests: `frontend/e2e/*.e2e.ts` (Playwright + axe; `PW_CHANNEL=msedge yarn e2e` with the servers running; CI job `browser`).
  * New env settings are listed in `.env.example`; `tests/test_deploy_config.py` fails if the code reads a setting that is not documented.
- External sources (`lib/external_sources.py`, `docs/VIDHI_RATING_AND_COMPLIANCE.md`): an honest registry of every outside service asked about (none live-tested); `ingest_allowed` refuses depositions, witness statements, transcripts, sealed or protected records and raw case files; the Indian Kanoon client is OFF until `INDIANKANOON_API_TOKEN` is set and returns unreviewed leads only. Never add a hidden layer of "loopholes": anything shown must be visible, sourced and lawyer-reviewable.
- Legal links (phase 16, all EMPTY until real text is loaded and reviewed): ``lib/legal_history.py`` (versions by recorded date, "as on" states), ``lib/legal_graph.py`` (cross-reference edges found by code on ingest), ``lib/forums.py`` (courts, remedies, appeal chains; edits undo review), ``lib/case_law.py`` (treatments need a passage that is in the loaded text; never says "good law"), routes in ``routers/legal_links.py``. Notices also block on stray figures (``amount_mismatches``).
- Arena skill (`.claude/skills/arena/`, third-party, MIT, installed unchanged from github.com/Jakeschincariol/arena-skill commit df07b8e of 2026-09-26, reviewed before install; compare against that commit before trusting any later change): on this Windows machine `python3` is a Microsoft Store stub that fails, so run every `bracket.py` command with `C:\vidhi-tools\venv2\Scripts\python.exe` instead of `python3`. It spends model calls (16 agents = 91 sub-agent calls, 32 = 187, 100 = 595): always show the `plan` numbers and get a yes first; default `--quick`. Never put keys, user data or real client documents in an Arena task. Its output is advice: never apply a winner without the owner's approval, and it proves nothing about legal accuracy. Run files go to `.arena/` (git-ignored).

## Status

Phases 0-6 of the audit plan are complete (see `AUDIT.md`), followed by the Recovery improvement stages 1-4 (intake, balance,
evidence, route warnings, notice versions and approval, delivery tracking, courtesy translations) and the Free / Pro plans with a
monthly Stripe subscription. Backend suite: 10,173 tests, all passing on 2026-10-21 (about 22 minutes with `scripts/test-backend.ps1 -Fast`; mostly generated cases, see docs/VIDHI_TEST_QUALITY_AUDIT.md); frontend: 120; browser (Playwright + axe): 14. The test script refuses to run if something already listens on port 8001 (a leftover server makes results wrong). Open items for the owner: rotate the API keys that were pasted into a chat;
add OpenRouter credit (Sonnet 5.5 needs it); a domain, then the Stripe and Resend webhooks (`docs/GO_LIVE.md`); a lawyer to review the
notice wording, warnings, MSME text, privacy page, translations and the verified law library; decide the retention period; do a restore
drill (`docs/RUNBOOK.md`); a first live card payment in Stripe test mode.
