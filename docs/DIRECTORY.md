# Lawyer directory and e-signing

## Lawyer directory (OFF by default)
Lawyers who choose to be listed appear at `/lawyers`; a visitor can send a consultation request. **It is switched off** (`DIRECTORY_ENABLED=false`): the public pages answer 404 until you turn it on.

### Why it is off: needs a lawyer first
Rules on how advocates may advertise, or be found by prospective clients, are set by their professional bodies, and a listing like this may be restricted or need a particular form. VIDHI cannot decide that. **Do not enable it until a lawyer has confirmed in writing that your lawyers may be listed this way, and what the listing may and may not say** (for example whether a bio or enrolment number is allowed). Also settle who answers for the content of each listing.

### How it works
* **Opt-in per person** (Settings > Directory, owner/admin/lawyer only): name, city, state, practice areas and languages from fixed lists, a short bio, and an enrolment number *as the lawyer states it*. The public sees it labelled "not verified by VIDHI". VIDHI verifies nothing about a lawyer.
* **No ranking, no payment, no promotion.** Results are alphabetical; filters are practice area, language and city. No email address or phone number is ever shown, and no internal id of the person or firm.
* **Consultation request** (no payment): name, email, optional phone, a message (20 to 1,500 characters) and a tick that it is not legal advice and creates no lawyer-client relationship. It is stored for that lawyer only and read inside VIDHI after signing in; the lawyer's email gets a notice that one is waiting, never its content. Contact details are marked unverified. Nothing is emailed to the requester (so the form cannot be used to send mail to other people).
* **Abuse limits:** bot check (Turnstile if configured, else a hidden field and a minimum time), 5 requests per hour per IP, 3 per day per email address, 30 per day per lawyer. A removed team member's listing and requests are deleted at once; organisation erasure deletes them too.
* The requester's details are personal data held for the lawyer; the privacy page (lawyer review pending) must describe this before launch.

## E-signing and e-stamping: extension point only
`lib/esign.py` defines the interface and an "unavailable" default. **Nothing signs or stamps anything**, no route exists, and a test checks that no page or template claims a signature. To add Digio, Leegality or another provider later:
1. A lawyer decides which document types and states can be e-signed and how stamp duty is paid (e-stamping is a separate service).
2. Open the provider account yourself (contract, price, data location: see `docs/RESIDENCY_CHECK.md`).
3. Implement `ESignProvider` and register it in `PROVIDERS`. Store only the provider's own status (never infer "signed"), and keep the signed file and audit trail under the retention rules (`docs/DATA_STORAGE.md`).