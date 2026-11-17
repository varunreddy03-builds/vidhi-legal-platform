# Client portal and conflict check

## Client portal (read-only)
A lawyer shares a matter with a client from the matter's **Client** tab. The client gets a private sign-in and sees only what was shared.

**What a client can see:** the matter's title and status, the updates a lawyer wrote for clients, and the documents a lawyer ticked as shared (download only). Nothing else: not the matter's description, parties, facts, research, drafts, notes, other documents, other matters, other clients, or anything of another firm.

**How it is enforced (on the server, not in the screen):**
* A client has the role `CLIENT`, which holds only `account` (own sign-in settings, sessions, data requests) and `portal`. It holds no `read` or `write`, and the single policy table in `lib/rbac.py` refuses every route for which the role lacks the capability. A new route is therefore closed to clients by default.
* A test walks **every route the API has** with a client's session and fails unless each non-portal, non-public route answers 403 (`tests/test_portal.py`).
* Each portal route looks up the signed-in client's access row (client, matter, organisation). No row, or a revoked one, answers 404, the same as a matter that does not exist. A document is served only if it belongs to that matter AND was shared.
* Removing access takes effect on the next request. Removing the client from Settings signs them out everywhere and deletes their access. Deleting a matter, or a document, deletes its portal data and shares. Organisation erasure removes all of it.
* Viewing a shared document is written to the matter's audit log.

**Rules for the firm's side:** inviting, posting updates and sharing need the `send_mail` capability (owner, admin, lawyer), because it is sharing outside the firm; the inviter's email must be confirmed. An invitation never mentions the matter. A "new update" email says only that something is new. A client's role cannot be changed (invite them as staff separately if needed). An email that already has a VIDHI account with another firm cannot be invited: one person, one organisation.

**Not built:** clients uploading or replying (read-only by design), sharing hearing dates with clients, billing or time tracking (deferred).

## Conflict check
`/conflicts` compares names (a prospective client and the other parties) with this organisation's own records: matter parties and titles, people found in documents (with their stated role), and recovery-case creditors and debtors.

* Matching is code, not AI: honorifics (Mr, Smt, Shri, Dr, Adv, M/s) and company words (Pvt, Ltd, LLP) are ignored; word order does not matter; an initial matches a full word; small spelling differences are tolerated. Strength is shown: strong (same words), possible, weak (one shared word such as a surname). The same name written in two different scripts is NOT recognised; search each spelling.
* **No match is never a clearance, and a match is not necessarily a conflict.** The screen and the API say so every time, and show how many records were searched. Relationships between people, other firms' records and anything outside VIDHI are not checked: the result is only as complete as the data entered.
* Only the signed-in organisation's records are searched. The audit log records that a check happened and how many matches it found, never the names searched.