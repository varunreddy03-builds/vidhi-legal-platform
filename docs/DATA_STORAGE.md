# How data is stored

| Data | How it is kept |
|---|---|
| Passwords | bcrypt hashes only (long passphrases count in full). Never readable, never emailed. |
| Sign-in sessions | Only a hash of the session token is stored; 30 days, renewed while the person is active; "sign out everywhere" ends them all. |
| Google sign-in | Only Google's account id and the verified email are kept. No Google access or refresh tokens are stored. Sign-in attempts (state, nonce) live 10 minutes and are deleted on use. |
| Two-step sign-in | The secret is encrypted (AES-GCM). Recovery codes are stored as keyed hashes; each works once. |
| Phone number (alerts) | Encrypted; only the last four digits and a keyed hash (to find the number when someone replies STOP) are readable. Removing the number deletes it. |
| Uploaded files (documents, proof, illustrations) | Encrypted at rest (AES-256-GCM) when `DATA_ENCRYPTION_KEY` is set. Back the key up outside the server. |
| Voice | Recordings and the text read aloud are processed in memory and never stored. Only a daily usage counter is kept. |
| Card, UPI and PayPal details | Never reach VIDHI. People pay on Stripe's, Razorpay's or PayPal's own page; only the provider's ids and amounts are stored. |
| Messages sent | An email log (recipient, status, time) and an SMS counter; no message text is kept for SMS. |
| Exports | The organisation export leaves out passwords, session hashes, two-step secrets, the stored phone number and Google ids. |
| Deleting an organisation | Removes its cases, matters, files, illustrations, members, sessions and audit trail (see `lib/purge.py`); payment rows stay but are anonymised. |
| Backups | Encrypted with a passphrase (see `docs/RUNBOOK.md`). The file-encryption key is stored separately. |

All records carry the organisation id and every query filters by it; tests prove one organisation cannot read another's data.