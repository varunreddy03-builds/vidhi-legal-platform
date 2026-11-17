# Document templates

Five starting drafts for India: residential rent agreement, loan agreement, NDA, legal notice for a cheque returned unpaid, employment (appointment) letter. They live as data in `backend/data/templates/`.

## How they are made safe
* **Filled by code, not AI.** The person answers questions; `lib/templates.py` inserts the answers into fixed wording. Answers are validated (dates, rupee amounts, whole numbers, choices, length), control characters are removed, and an answer containing `{{...}}` is inserted as plain text and never expanded.
* **No law from memory.** The wording names no statute, section or case (a test scans for citations and statute names). Anything legal (stamp duty, registration, governing law and forum, statutory periods, statutory benefits and deductions, remedies) is a visible `[LAWYER TO CONFIRM: ...]` item. Missing optional values needed by a chosen clause become `[... - to be filled]`. The draft screen counts the items still open.
* **Neutral wording.** A test rejects words like "lied", "cheat", "fraud". The cheque notice states dates and the bank's stated reason and nothing about intent.
* **Review gate (same idea as the law library).** Files in `pending/` are always "UNVERIFIED - pending lawyer review", whatever they say. A lawyer approves with `python backend/scripts/template_review.py approve --id <id> --reviewer "Full Name" --on YYYY-MM-DD`, which moves the file to `<COUNTRY>/`, records the reviewer and date, and stores a hash of the wording they read. If the wording is edited afterwards, the hash no longer matches and the template reads as **not reviewed** again. `... status` lists every template and its state.
* **Every draft says what it is.** The draft starts with a note: "DRAFT FROM A TEMPLATE - NOT REVIEWED BY A LAWYER" (or who reviewed the wording and when, and that this does not cover the facts). The editor shows an amber banner. The audit log records the template, its version and its review state.
* **Countries.** A template belongs to one country and works only for a country VIDHI covers (`lib/jurisdictions.py`: India only today). Asking for another country returns "VIDHI does not cover ... law yet" and no templates. A draft attached to a matter must match the matter's country.
* **Editable.** The result is an ordinary draft (versioned, searchable, deletable).

## What is NOT done
* No lawyer has reviewed any of these five. Until one does, they are drafting aids only. Sending them to a lawyer: give them `backend/data/templates/pending/*.json` (the `lawyer_checks` list in each file says what to look at) or the rendered drafts.
* English only. Hindi, Telugu and other versions need a lawyer who reads those languages, then a file per language.
* The loan and employment templates are generic. Rules for particular lenders, workplaces, states or sectors are not included.
* No signing or stamping: see `docs/INTEGRATIONS.md` (e-signature is an extension point only).