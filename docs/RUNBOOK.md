# VIDHI runbook - running it for real clients

Short, practical. Commands run from the folder that holds `docker-compose.yml` and `.env`.

## 1. Monitoring (set this up on day one)

| Check | How | Alert when |
|---|---|---|
| Is it up? | Point an uptime monitor (UptimeRobot, Better Stack, your cloud's health check) at `https://<your-domain>/api/health/ready` every minute | HTTP is not 200, or two failures in a row |
| Are the jobs running? | The same URL: `"status":"degraded"` and a `jobs` list means a scheduled job is overdue (> 36 h) or its last run failed | Any `degraded` for more than an hour |
| Errors | Every API response carries `X-Request-ID`. A user who sees "Something went wrong" is shown a reference; search the API logs for it (`docker compose logs backend \| grep <reference>`) | - |
| Access log | One line per request: `rid= method= route= status= ms=`. It deliberately holds **no** personal data, query strings, tokens or ids: only the route template | - |

### Error tracking, uptime and the admin console
- **Error tracking (Sentry).** Create a free project at sentry.io and copy its DSN into `SENTRY_DSN`. Reports are scrubbed in code before they leave (no request bodies, cookies, local variables or personal data; emails and long numbers in messages are replaced). Leave `SENTRY_DSN` empty to keep it off. Sentry is a processor outside India: it is named in the privacy policy and in `docs/ARCHITECTURE_DECISIONS.md`.
- **Uptime alerts.** Set the repository variable `UPTIME_URL` (GitHub, Settings, Secrets and variables, Variables) to switch on `.github/workflows/uptime.yml`, which checks `/api/health/ready` every 10 minutes; a failed run emails the account that last edited the schedule. For faster alerts to a verified phone or email add UptimeRobot or Better Stack on the same URL, and record who is told in `UPTIME_ALERT_CONTACT` (the admin console shows whether it is set). No alert contact is invented: give the system the genuine one.
- **Admin console** (`/admin`): only emails in `PLATFORM_ADMIN_EMAILS` that have a confirmed email AND two-step sign-in are let in, checked on the server for every call. It shows health, people, AI spend, support messages, data requests and unusual activity; blocking signs the person out at once. It never shows passwords, keys, documents or answers.

`/api/health/ready` returns 503 when the database does not answer and reveals nothing else. The job timestamps live
in the `job_runs` collection.

## 2. Backups

`scripts/backup.sh` dumps the database (documents are stored inside it), compresses it and encrypts it with GnuPG
(AES-256). Keep the passphrase **off the server** (a password manager, plus a sealed copy with a second trusted
person). Without it a backup is unreadable - by design.

```bash
umask 077
openssl rand -base64 36 > /secure/backup.pass         # once; store a copy elsewhere
BACKUP_PASSPHRASE_FILE=/secure/backup.pass bash scripts/backup.sh /var/backups/vidhi
```

Schedule it daily (host cron, e.g. `15 2 * * * cd /srv/vidhi && BACKUP_PASSPHRASE_FILE=... bash scripts/backup.sh /var/backups/vidhi`),
then **copy the encrypted files off the machine** (another cloud account or region, e.g. `rclone copy`). A backup that
lives only on the same disk is not a backup. Old files are removed after 30 days (`KEEP_DAYS`).

The file-encryption key (`DATA_ENCRYPTION_KEY`) is NOT in the database backup. Store it with the backup passphrase (password manager + sealed copy). A restore without it brings back records but the uploaded files stay unreadable.

Deleted data and backups: an organisation's erasure removes it from the live database at once; copies inside older
backups disappear when those backups expire (30 days by default). Say so to clients who ask.

## 3. Restore (practise it before you need it)

```bash
BACKUP_PASSPHRASE_FILE=/secure/backup.pass bash scripts/restore.sh /var/backups/vidhi/vidhi-<stamp>.archive.gz.gpg
docker compose restart backend
```

It asks you to type the database name (this replaces the data). **Do a restore drill every quarter** on a spare
machine: start the stack from scratch, restore the newest backup, log in, open a matter and download a document. Write
the date of the last successful drill below.

Last restore drill: _not yet done_

## 4. Routine checks

* Weekly: look at `degraded`/job failures; look at `ORG_EXPORT`, `MEMBER_*` and `*_DELETE` entries in the audit log.
* Monthly: apply security updates (`docker compose pull && docker compose up -d --build`), then re-run the checks.
* After staff leave: remove them under Settings > Team (this ends their sessions immediately).
* A lost phone / suspected password leak: the person uses "Sign out everywhere" and changes the password; an admin
  can remove and re-invite them.

## 5. Data requests

| Request | What to do |
|---|---|
| "Give us all our data" | An owner/admin opens Settings > Data & privacy > Download export (a zip of JSON plus original files) |
| "Delete our data" | An owner uses Settings > Data & privacy > Erase organisation (password + typed name). Backups age out within 30 days |
| "Delete one matter / case" | Delete it in the app. It removes the files, facts, drafts, email records; audit lines are kept with their text blanked |
| "Keep this matter, a dispute is coming" | An admin turns on **Legal hold** on the matter; neither hand-deletion nor retention can remove it |
| Automatic clean-up | Settings > Data & privacy > retention period. Off by default. When on, owners are emailed 30 days before anything is deleted |

## 6. If something goes wrong

1. Look at `/api/health/ready`, then `docker compose ps` and `docker compose logs --tail 200 backend`.
2. Database down: `docker compose restart mongo`; if the volume is damaged, restore (section 3).
3. A secret was exposed: rotate it at the provider (Gemini, Stripe, Resend), put the new value in `.env`,
   `docker compose up -d`. Rotating `WEBHOOK_CRON_SECRET` also means updating the `CRON_SECRET` GitHub secret.
4. Suspected unauthorised access: use the audit log (Settings > Audit), end sessions (`db.sessions.deleteMany({})` in
   mongosh signs everyone out), reset passwords, tell affected clients. Keep a written timeline.

> Legal note: if you hold clients' personal data you may have duties under India's Digital Personal Data Protection
> Act, 2023 and its rules (notices, breach reporting, retention). This runbook is operational, not legal advice -
> have a lawyer review the privacy notice and your breach procedure.
