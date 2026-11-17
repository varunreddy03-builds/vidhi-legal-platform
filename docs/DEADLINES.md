# Dates, reminders and the installable app

## What it does
* **Dates and hearings** (`/deadlines`): a person saves a title, a kind (hearing, deadline, filing, meeting, other), a local date and time, a time zone, and optionally a matter. The team of one organisation sees the same list.
* **Reminders** a week, three days, a day, two hours, an hour or fifteen minutes before. Channels per date: email, browser notification, and text message (opt-in).
* **Calendar files**: `.ics` for one date or all open dates, importable into Google Calendar, Outlook and Apple Calendar. Times are written in UTC with the local time in the description; each chosen reminder becomes an alarm in the calendar.
* **Installable app**: `manifest.webmanifest` and `sw.js`. The service worker only enables installing and shows notifications. It caches nothing on purpose (no stale app, no legal data left in a cache on a shared device).

## What it does NOT do (on purpose)
* Every date is **entered by a person**. VIDHI does not look up courts, does not read cause lists and does not calculate limitation or filing periods. Reminders and calendar files carry that sentence. A court lookup, if ever built, needs its own verified source.
* Text messages and browser notifications never contain the title, names or case details (they pass through phone networks and push services): only "A date you saved in VIDHI is coming up in one hour." The email goes only to the person who saved the date and does carry the title.
* Text messages are sent only to a phone the person verified and switched alerts on for (`lib/phone_alerts.py`, 20 a day at most). Never to a client or a third party.

## Time zones
A date is typed as local time plus an IANA zone name (default `Asia/Kolkata`), stored in UTC and shown back in the same zone. A local time that does not exist (the hour skipped when clocks go forward) is refused. A time that happens twice (clocks go back) means its first occurrence. An explicit offset in the text (`...+05:30`) is honoured. Moving a date resets its reminders.

## Setup (once)
1. `python scripts/make-vapid-keys.py` and put the printed `VAPID_PRIVATE_KEY=...` line in `.env` on the server (secret). Set `SUPPORT_EMAIL` (or `VAPID_SUBJECT`): the push services want a contact. Changing the key later makes every browser subscribe again.
2. Add the scheduled trigger (already in `.github/workflows/scheduled-jobs.yml`, every 15 minutes): `POST /api/cron/deadline-reminders` with the cron secret. GitHub can start scheduled runs several minutes late and sometimes skips one; a reminder is sent at the first run after its moment, never twice (each is claimed atomically first). For steadier timing use a real scheduler (cron container, cloud scheduler) on the same URL. `/api/health/ready` shows "degraded" if the job has not run for 3 hours.
3. Text messages need the Twilio settings (`docs/INTEGRATIONS.md`).

## Browser notes
* Chrome, Edge and Firefox: after "Turn on notifications on this device" the browser asks for permission.
* iPhone and iPad (Safari): web notifications work only after "Share > Add to Home Screen" and opening the app from there.
* A device address is accepted only from the push services of Chrome/Android (Google), Firefox (Mozilla), Edge on Windows (`notify.windows.com`) and Safari (Apple), over https. This stops the server being pointed at any other address.
* Up to five devices per person. A device the push service reports as gone is removed automatically.

## Checked and not checked
* Checked by automated tests: time-zone conversion including clock changes, reminder planning (no repeats, no reminders for finished dates), the calendar file format, access across organisations, device-address rules, generic wording of texts and notifications, and the service worker's behaviour on push and click against a stand-in worker scope.
* NOT checked by me: a real notification arriving on a real phone or browser through the real push services, and service-worker registration in a real browser (the browser pane I had refuses every service worker). Do this once on staging: turn notifications on, create a date 20 minutes ahead with a 15-minute reminder, and wait.
* The app icons are a stand-in drawn from the diamond mark already used on the sign-in page (`scripts/make-icons.py`). The previous icons were a leftover logo of another platform. Replace the files in `frontend/public` with your designed logo when you have one (same names and sizes).