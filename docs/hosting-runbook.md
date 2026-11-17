# Hosting runbook: VIDHI pilot on one small India-region server

Written 2026-10-26. This is the single document to follow to put VIDHI online for an invite-only pilot (decision D6), staging first. Anything marked **needs a lawyer to confirm** is a legal point the engineer cannot settle. Anything marked **check current prices** is an estimate that must be checked on the provider's own site.

## 0. What is ready, and what has not been run

| Part | State |
|---|---|
| The app, tests, secrets scan, startup check, invite-only sign-up, 30-day upload expiry, migrations, encrypted backup and restore (Python) | Built and tested on the build machine, including a real backup, a restore into a fresh database and a tampered-backup test. |
| `docker-compose.yml`, Dockerfiles, `deploy/Caddyfile`, `deploy/nginx.conf` | Written. **Docker is not installed on the build machine, so the containers have never been started there.** The first start happens in the CI job `stack` (see 6.1), which builds the images, starts the stack, runs outside checks and a backup and restore. Read its result before you rely on this. |
| `.github/workflows/deploy.yml` | Written, **never run**. It does nothing until you set the variable `DEPLOY_ENABLED` to `true`. |
| A hosted server, a domain, DNS, certificates, GitHub environments, off-site backup copies | Do not exist. Only you can create them (section 1). |

## 1. What only you can do
1. **Create the accounts** and pay: a cloud provider (section 3), a domain name registrar, a GitHub organisation or repository with Actions enabled, an email-sending service, an error-tracking account (optional), and the AI provider keys. VIDHI cannot create accounts or pay for anything.
2. **Choose and register the domain** (for example `app.yourfirm.in`) and the staging name (for example `staging.yourfirm.in`).
3. **Put the secrets in the GitHub environments** (section 5). Never paste a key in chat or email; if one was pasted anywhere, rotate it.
4. **Approve production deploys** (you are the required reviewer).
5. **Name the reviewing advocate** and decide the open points in `docs/decisions.md` (Indian Kanoon permission, India Code permission, other Toolkit cards).
6. **Get a lawyer's confirmation** of the legal points in section 11 before real client material is uploaded.
7. **Keep the backup passphrase safe, away from the server** (a password manager plus a printed copy in a safe). Lose it and every backup is unreadable.

## 2. What you will run
One Linux server running Docker Compose with: MongoDB (password-protected, not reachable from the internet), the API, the web server, **Caddy** (gets and renews the HTTPS certificate by itself) and a **backup** container (encrypted, every 24 hours, 30 copies kept). Only ports 22 (SSH), 80 and 443 are open. Everything is in `docker-compose.yml`.

A staging server and a production server are two separate copies (two servers, or two folders and two domains on one larger server). **Staging never shares a database with production** (the profiles use `vidhi_staging` and `vidhi`).

## 3. The server (India region)
- **Where:** a data-centre region in India (for example Mumbai or Bengaluru) at any large cloud provider or an Indian provider. Pick one you can pay in rupees or by card. *Check current prices.*
- **Size for a pilot:** 2 vCPU, 4 GB memory, 40 GB SSD, Ubuntu 24.04 LTS. Add a separate small block volume or object storage for backup copies (section 9).
- **Rough monthly cost (check current prices):** server about USD 20-40; backup storage about USD 1-5; domain about INR 600-1,500 per year; email sending free to about USD 20; error tracking free tier; AI usage varies with use (see `docs/VIDHI_COST_MODEL.md`) and is capped by `AI_MONTHLY_CAP_INR`. Plan for roughly **INR 2,500-5,000 per month before AI usage** for staging plus production on small servers. This is an estimate, not a quote.
- **Security basics on the server:**
  1. Log in with an SSH key only (turn off password login).
  2. Firewall: allow 22, 80, 443 only. In the provider's console too.
  3. Turn on automatic security updates (`unattended-upgrades`).
  4. Create a normal user for deploys (not root) and add it to the `docker` group.
  5. Install Docker Engine and the Compose plugin from Docker's own instructions.

## 4. The domain
1. At the registrar, create an `A` record from your domain (`app.yourfirm.in`) to the server's public IP address. Do the same for staging.
2. Wait until `nslookup app.yourfirm.in` shows the server's address. Caddy can only get a certificate when this is true and ports 80 and 443 are open.

## 5. GitHub: environments, secrets, variables
1. In the repository: **Settings → Environments →** create `staging` and `production`. On `production`, tick **Required reviewers** and add yourself.
2. In **each** environment add these **secrets** (values differ between staging and production):
   - Server access: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH` (for example `/srv/vidhi-staging`), `DEPLOY_SSH_KEY` (a private key made only for deploys; its public half goes in the server user's `authorized_keys`), `DEPLOY_KNOWN_HOSTS` (the server's host-key line: on your own computer run `ssh-keyscan -t ed25519 your.server.ip` once, **check the fingerprint in the provider's console**, and paste it).
   - App: `DOMAIN` (host only, no https://), `APP_URL` (`https://…`), `CORS_ORIGINS` (the same https address, never `*`), `MONGO_ROOT_PASSWORD` and `MONGO_APP_PASSWORD` (24 or more letters and digits, no symbols), `LINK_SECRET` and `WEBHOOK_CRON_SECRET` (random, 40 or more characters), `DATA_ENCRYPTION_KEY` (see below), at least one AI key (`GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY`), `PLATFORM_ADMIN_EMAILS` (your email), `RESEND_API_KEY` or another email provider's key and `EMAIL_FROM`, and, optional, `SENTRY_DSN`, the Turnstile keys, `INDIANKANOON_API_TOKEN` (only after you confirm the terms), and the business details (`BUSINESS_LEGAL_NAME`, `GRIEVANCE_OFFICER_*`, `SUPPORT_EMAIL`).
   - Make random values with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Make the encryption key with: `python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` and **keep a copy offline: without it uploaded files cannot be opened**.
3. In **repository variables** add `DEPLOY_ENABLED` = `true` only when you are ready for the first deploy.
4. The workflow `Deploy` (Actions tab → Deploy → Run workflow) runs the whole CI first and deploys only if all of it is green.

## 6. First deploy: staging
### 6.1 Before anything: read CI
Push to `main` and open the **Actions** tab. Every job must be green, especially `stack`: it is the first time the containers run. If `stack` is red, fix that before going further; its log shows what failed.

### 6.2 Prepare the server folder (once)
On the server, as the deploy user (replace the path with your `DEPLOY_PATH`):
```bash
sudo mkdir -p /srv/vidhi-staging/secrets /srv/vidhi-staging/backups
sudo chown -R "$USER":"$USER" /srv/vidhi-staging
# the backup container runs as user 10001: it must read the passphrase and write the backups
openssl rand -base64 32 > /srv/vidhi-staging/secrets/backup_passphrase
sudo chown 10001:10001 /srv/vidhi-staging/secrets/backup_passphrase /srv/vidhi-staging/backups
sudo chmod 400 /srv/vidhi-staging/secrets/backup_passphrase
sudo chmod 700 /srv/vidhi-staging/backups
```
**Copy the passphrase off the server now** (`sudo cat /srv/vidhi-staging/secrets/backup_passphrase`) into your password manager. Do this once per server and use a different passphrase for production.

### 6.3 Run the deploy
Actions → Deploy → Run workflow → environment `staging`. The job builds the `.env` from the environment's secrets, copies the release and the `.env` to the server, runs `docker compose --profile https up -d --build`, then runs `deploy/smoke.sh` against the live address.

### 6.4 Check staging by hand (about 30 minutes)
1. Open `https://staging…`: the padlock is shown and the app loads.
2. Sign in as the operator (your email must be in `PLATFORM_ADMIN_EMAILS`; turn on two-step sign-in in Settings, which the admin console requires).
3. Admin console → **Pilot invites**: invite a test address, open the link, create the account. Try sign-up **without** a code: it must be refused.
4. Upload a small file into a matter; delete it; see that it is gone.
5. Admin console → AI spend: the monthly cap is what you intend.
6. Run the **restore drill** (section 9.3) on staging.
7. Look at the logs (section 10) and confirm no client text appears.
8. Work through `docs/device-test-checklist.md` on a laptop, an iPhone and an Android phone, using the staging address.

## 7. Production
Repeat sections 6.2 and 6.3 with the `production` environment and its own server folder, domain, secrets and passphrase. A production deploy waits for your approval. Production starts **invite-only** (`SIGNUP_MODE=invite`), uploads expire after 30 days (`UPLOAD_MAX_DAYS=30`), and Authority Check is off (`AUTHORITY_CHECK_ENABLED=false`) until you change it in `deploy/profiles/production.env` and deploy again.

## 8. Running the pilot
- **Invite people:** Admin console → Pilot invites. Each invite works once, for one email address, for 14 days. Tick "Email it to them" or copy the link yourself (shown once).
- **Scheduled jobs:** the GitHub workflow `Scheduled jobs` calls the server's `/api/cron/*` endpoints (set repository secrets `APP_URL` and `CRON_SECRET`, which equals `WEBHOOK_CRON_SECRET`). These include reminders, retention and the **30-day upload expiry**. If it stops, `/api/health/ready` reports the job as overdue.
- **Uptime:** `.github/workflows/uptime.yml` watches `/api/health/ready`; set `UPTIME_ALERT_CONTACT`.
- **Law library:** empty until permission and a reviewing advocate exist (`docs/legal-sources-terms.md`, `docs/reviewer-brief-law-library.md`).

## 9. Backups
### 9.1 What runs
The `backup` container writes an encrypted file to `backups/` every 24 hours (`BACKUP_EVERY_HOURS`), checks it can be read back, and removes copies older than 30 days (`BACKUP_KEEP_DAYS`). It contains the whole database, including the (already encrypted) uploaded files.

### 9.2 Copy backups off the server (you must set this up)
A backup on the same disk as the database does not survive losing the server. Copy `backups/` somewhere else every day: another provider's object storage or a second small server, using `rclone` or `rsync` from a cron job on a **different** machine (so a compromised web server cannot delete its own backups). Keep the passphrase somewhere else again.

### 9.3 Restore drill (do it on staging before production, then every month)
```bash
cd /srv/vidhi-staging
# 1. check the newest backup can be decrypted and every hash matches (changes nothing)
docker compose run --rm --no-deps -v "$PWD/secrets/backup_passphrase:/pp:ro" -v "$PWD/backups:/backups" --entrypoint python backend \
  tools/db_restore.py /backups/<file>.gpg --passphrase-file /pp --verify-only
```
To really restore (for example after a bad change), **stop the API first**, then restore over the database and start again:
```bash
docker compose stop backend web
docker compose run --rm --no-deps -v "$PWD/secrets/backup_passphrase:/pp:ro" -v "$PWD/backups:/backups" --entrypoint python backend \
  tools/db_restore.py /backups/<file>.gpg --passphrase-file /pp --replace
docker compose up -d
bash deploy/smoke.sh https://your-address
```
**Then, before anyone signs in, erase again what was erased after that backup was made.** A restore brings back whatever existed on the backup's day. Every erasure (a person, a matter, a case, a document, an organisation) is written to `backups/erasures.jsonl` as a kind and an id. Run, from the same folder:
```bash
docker compose run --rm --no-deps -v "$PWD/backups:/backups" -e ERASURE_LEDGER_FILE= --entrypoint python backend tools/reapply_erasures.py --ledger /backups/erasures.jsonl --dry-run
docker compose run --rm --no-deps -v "$PWD/backups:/backups" -e ERASURE_LEDGER_FILE= --entrypoint python backend tools/reapply_erasures.py --ledger /backups/erasures.jsonl
```
The first line only lists how many had come back; the second erases them. It is safe to run twice. Keep `erasures.jsonl` with the backups when you copy them off the server.
Tested on the build machine: a backup restored into a fresh database is identical, byte for byte; a wrong passphrase or a changed byte stops the restore before anything is written.

## 10. Updates, rollback, logs, secrets
- **Update:** push to `main`, wait for green CI, run **Deploy**. Database changes run as migrations when the API starts (`python scripts/migrate.py --status` shows them). Migrations must be safe to run twice.
- **Roll back:** run **Deploy** again from an earlier commit (Run workflow on that commit's tag or branch). If a migration changed data, restore the pre-deploy backup (take a manual one first: `docker compose run --rm --no-deps -v "$PWD/secrets/backup_passphrase:/pp:ro" -v "$PWD/backups:/backups" --entrypoint python backend tools/db_backup.py --out-dir /backups --passphrase-file /pp`).
- **Logs:** `docker compose logs --tail=200 backend`. VIDHI's logs carry request ids, routes, statuses and timings, **not client text**; a test checks that spoken words are never logged. The proxy log drops the web address and headers. Do not enable extra debug logging on a server holding client material.
- **Rotate a secret:** change it in the GitHub environment and run Deploy. Rotating `DATA_ENCRYPTION_KEY` needs care: set the new key first and keep the old one after it (comma-separated) so old files still open. Rotate any key that was ever pasted in chat or email.
- **Disk space:** watch it (`df -h`); the database and backups grow.

## 11. Data protection: needs a lawyer to confirm
These are the points to put to an advocate before real client material is uploaded. VIDHI's engineer has not decided any of them.
1. **Digital Personal Data Protection Act, 2023** (and its rules): whether VIDHI's operator is a data fiduciary or processor for law-firm clients' data, and what notice and consent the firm needs from its own clients. **Needs a lawyer to confirm.**
2. **Client confidentiality** (advocate-client privilege and Bar Council rules) when documents go to an AI provider outside India. The AI providers listed in `docs/INTEGRATIONS.md` process text abroad; the privacy page must say so. **Needs a lawyer to confirm.**
3. **Retention:** uploads are deleted after 30 days at most (D5), and a user can delete at once. Whether 30 days is right for legal and tax record-keeping, and what happens to audit logs, **needs a lawyer to confirm**.
4. **Breach reporting** duties (to the Data Protection Board and to affected people) and who is responsible. **Needs a lawyer to confirm.**
5. **Cross-border transfer** and **data localisation** expectations for the database (this runbook keeps it in India). **Needs a lawyer to confirm.**
6. The **grievance officer** details (`GRIEVANCE_OFFICER_*`) and the privacy page text (`Privacy.tsx`, `REVIEWED_BY_LAWYER`) must be filled and reviewed.
7. **Law text and judgments:** India Code and Indian Kanoon terms (`docs/legal-sources-terms.md`). No judgment text is stored (D3).

## 12. Cost sheet (estimates; check current prices)
| Item | Rough amount | Notes |
|---|---|---|
| Server, production (2 vCPU, 4 GB) | USD 20-40 / month | India region |
| Server, staging (smaller) | USD 10-20 / month | can be switched off between releases |
| Backup storage (off-site) | USD 1-5 / month | grows with data |
| Domain | INR 600-1,500 / year | |
| Email sending | free to USD 20 / month | by volume |
| Error tracking | free tier | optional |
| AI providers | variable | capped by `AI_MONTHLY_CAP_INR` and the daily caps `AI_DAILY_CAP_INR`, `AI_FREE_DAILY_CAP_INR`, `AI_USER_DAILY_CAP_INR`, `AI_FREE_USER_DAILY_CAP_INR`; see the cost model |
| Indian Kanoon lookups | per lookup | check Indian Kanoon's own price; the app's estimate is a placeholder |

## 13. If something goes wrong
| Sign | First thing to try |
|---|---|
| Browser says the certificate is wrong | DNS not pointing at the server yet, or port 80/443 closed. `docker compose logs proxy`. |
| API container keeps restarting | `docker compose logs backend`. A live site stops on purpose when a required setting is missing and names it (never the value). |
| `Database migration … failed` | `python scripts/migrate.py --status` (run in the backend container), fix, restart; a failed migration is retried. |
| Cannot sign up | The pilot is invite-only. Make an invitation. |
| Uploads disappeared | They expire after 30 days (D5). The owners were emailed 7 days before. |
| Deploy job red at "Check the live site" | The new containers started but a check failed; open the job log. Roll back (section 10). |
