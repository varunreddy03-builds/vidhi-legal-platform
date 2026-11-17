# Integrations: what to set up, and what each one does

Every integration is optional. If its keys are not set, its button or section simply does not appear. Never paste keys into chat or commit them: they go in
the server's `.env` (names are listed in `.env.example`). Use test or sandbox keys first.

| Service | What it does in VIDHI | Keys | Where to get them |
|---|---|---|---|
| **Google sign-in** | "Continue with Google" on the login page. A new person gets an account; someone with the same verified email is linked to their existing account. | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google Cloud Console > APIs & Services > Credentials > OAuth client (Web). Redirect URI: `<APP_URL>/api/auth/google/callback`. Consent screen: add your privacy page link. |
| **SendGrid** | Alternative to Resend for all email. Delivery events (delivered, bounced, spam complaint) feed the same suppression list. | `SENDGRID_API_KEY`, `SENDGRID_WEBHOOK_PUBLIC_KEY`, `EMAIL_PROVIDER` | SendGrid: Settings > API Keys; Mail Settings > Event Webhook: URL `<APP_URL>/api/webhooks/sendgrid`, turn on **Signed** event webhook and paste its public key. Verify the sender domain. |
| **Twilio** | Opt-in SMS or WhatsApp alerts to the account owner's own verified phone (for example "a notice delivery changed"). Texts never contain names or amounts and are never sent to a customer. STOP replies switch alerts off. | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, `TWILIO_WHATSAPP_FROM` | Twilio console. Inbound webhook for the number: `<APP_URL>/api/webhooks/twilio` (POST). India SMS needs DLT registration of sender and templates: ask Twilio. |
| **ElevenLabs** | Natural multilingual voice for "Listen", and speech-to-text (Scribe) for "Speak your question". | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | elevenlabs.io > API keys. Without it: speech-to-text uses Gemini, "Listen" uses the browser's built-in voice. |
| **Razorpay / PayPal / Stripe** | Payments for Pro. See `docs/DEPLOYMENT.md` steps 4, 4b, 4c. | see there | |
| **Image model** | A few simple illustrations a month, Pro only, off by default. | `IMAGE_GEN_ENABLED=true`, `IMAGE_MONTHLY_CAP`, `IMAGE_MODEL` | Uses your Gemini key. Check Google's current image model name before enabling. |

## Sign-in options for people
Email and password (always on, with optional two-step code), and Google. People stay signed in for 30 days and the period renews while they use the app.
A person who turned on the app's two-step sign-in cannot skip it through Google: they are asked to use their password and code.

## Instant decisions ("Jev")
`backend/lib/decide.py` sorts and scores with plain rules in code: no AI, no cost, same answer every time, and every result lists its reasons.
Used for: the order of cases on the Home screen ("needs attention" first, with why) and the hint on the Ask screen (money owed, or something to take to a lawyer soon).
To change what counts as urgent, edit `CASE_RULES` and `CASE_BANDS`; `backend/tests/test_decide.py` shows each rule.

## Things to confirm in each provider's test mode (they follow the provider's documentation and could not be tried against the live services here)
- Google: sign in with a new and an existing Google account.
- SendGrid: a bounce and a delivery appear on the case; the signature check accepts real events.
- Twilio: the code arrives; replying STOP switches alerts off.
- ElevenLabs: Hindi and Tamil text is read in the right language; a recording in your language is transcribed.
- Razorpay and PayPal: renewal and cancellation (see `docs/DEPLOYMENT.md`).
## Monthly AI spending cap
`backend/lib/aibudget.py` enforces a cap on AI spending (default Rs 20,000 a month, Indian calendar month) for every paid call: AI answers, scan reading, voice and
illustrations. Before each call the worst-case cost is reserved with one atomic database update that refuses if the cap would be passed, so simultaneous
requests cannot overshoot. After the call the reservation becomes the real cost from the provider's own token counts (or a cautious estimate). A failed
call is released. At 80% the owner is emailed once a month (`OWNER_ALERT_EMAIL`; without it the alert is only logged and shown in the admin console);
at 100% every AI call is refused with a clear message until next month. The ledger keeps provider, task, tokens and cost, never prompts or answers.
**Set `AI_PRICES_JSON` to each provider's real current prices**: the defaults are placeholders that lean high. The cap protects you only as well as these numbers are right,
and it counts what VIDHI sends, so also set a spending limit inside each provider's own console as a second wall.

## Account security (built in, no keys needed except Turnstile)
- **Where you are signed in** (Settings): every session with its device ("Chrome on Windows"), the network with its last part hidden, and when it was last used; any can be ended at once.
- **Sign-in alerts**: an email to the confirmed address when someone signs in from a device not seen before, and when the password or two-step setting changes. The first device is simply remembered.
- **Two-step sign-in is required for owners and admins of a team** (an organisation with more than one person). They get `TWO_STEP_GRACE_DAYS` (7) of notice with a banner; after that everything except the account, privacy and help pages is closed until they turn it on. People working alone are never affected, and the operator's admin console always requires it.
- **Bot protection on signup**: Cloudflare Turnstile once `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` are set (the page loads Cloudflare's script, which is why `deploy/security-headers.conf` allows `challenges.cloudflare.com`). Before that, a weaker fallback stops only simple bots (a hidden field and a minimum time on the form). Switch Turnstile on before launch.
- **Dependabot** (`.github/dependabot.yml`) proposes weekly updates for Python, JavaScript, Docker and GitHub Actions; every proposal runs the full tests first.
