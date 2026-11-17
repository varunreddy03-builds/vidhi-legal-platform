# What to do when an alert fires

Written 2026-11-05. Two kinds of alert exist: **the site is down or unhealthy** (an uptime monitor) and **an error happened in the code** (error tracking). Neither ever carries client text: the error reports hold only the kind of error and where in our code it happened, and the health page holds only status words and job names (tests: `backend/tests/test_log_leaks.py`).

## One-time setup (you; I cannot create accounts)

1. **Error tracking (Sentry, free Developer plan to start).** Create a project, copy its DSN, and put it in the GitHub environment secret `SENTRY_DSN` for `staging` (and later `production`), then deploy. Leave it empty to keep error tracking off. Check where Sentry stores data when you create the organisation, and put the answer in `docs/RESIDENCY_CHECK.md`. Then force one test error on staging and look at the event in Sentry: it must show the error class and file and line only, with no message text.
2. **Uptime (UptimeRobot free plan).** Add a *keyword* monitor on `https://<your-domain>/api/health/ready` that expects the text `"status":"ok"`, checked every 5 minutes, with your email as the alert contact. Set the same contact in `UPTIME_ALERT_CONTACT` so the admin screen stops warning. Leave the repository variable `UPTIME_URL` empty so the GitHub uptime workflow stays off and does not use up Actions minutes.

## When the uptime alert fires (site down, or `/api/health/ready` is not "ok")

1. Open `https://<your-domain>/api/health` and `/api/health/ready` in a browser. `unavailable` with `"database":"down"` means the app is up but MongoDB is not answering. No answer at all means the app, the proxy or the server is down. `degraded` means a scheduled job is late (next section).
2. On the server, in the deploy folder: `docker compose ps`, then `docker compose logs --tail=200 backend`. The logs hold request ids, routes, error classes and file and line numbers, never client text. A live site that stops on purpose names the missing setting (never its value).
3. Disk full? `df -h`. The database and backups grow; container logs are capped at 5 files of 10 MB.
4. If the database container is the problem, `docker compose restart mongo`, then `backend`. Check `/api/health/ready` again.
5. If it started after a deploy, roll back: run **Deploy** again from the last good commit (`docs/hosting-runbook.md` section 10).
6. If data is damaged, restore the newest backup (`docs/hosting-runbook.md` 9.3). You will already have run `tools/restore_drill.py`, so you know it works and how long it takes.
7. Write what happened in `docs/PROJECT_MEMORY.md` (time, cause, fix).

## When the status is "degraded" (a job is late or failed)

`/api/health/ready` lists the job name and `overdue` or `last run failed`. Run that job once by hand (Actions, Scheduled jobs, Run workflow). If it fails again, look at the job's stored error: it is the error class only, so read the backend log by time for the file and line. The usual cause is a wrong or changed `CRON_SECRET`/`WEBHOOK_CRON_SECRET` (they must be equal) or the schedule not being switched on.

## When the error-tracking alert fires

1. Open the event. You will see the error class, the files and lines of our code, the route and the status. There is no message: that is deliberate.
2. Find the same moment in the backend log by time or by the request id (`rid=`). The log line has the class and the same file and line.
3. Reproduce it with **invented** data. Do not copy a client's document, name or address into Sentry, GitHub, a chat or this repository.
4. Fix it with a test, deploy to staging, then production. Mark the event resolved.
5. An error that repeats for many people, or involves login, payments, uploads or deletion, is urgent: tell users by email, and consider rolling back.

## Other alerts that share this page

- **AI spending at 80%** (email to the owner address): the platform cap is near. Check the admin AI-spend screen; raise the cap only after looking at the cost records (`docs/VIDHI_COST_MODEL.md`).
- **Restore drill says FAIL or "backup is N hours old"**: backups have stopped or cannot be read. Fix this before anything else; run `tools/restore_drill.py` again after the fix (`docs/STAGING_PLAN.md` section 4).
- **Suspected exposure of client data**: stop, keep the logs, and call the advocate. Breach duties need a lawyer (`docs/PRIVACY_REVIEW.md`, section 7).
