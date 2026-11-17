# Verified law library

This folder is EMPTY on purpose. VIDHI contains no law of its own: a legal citation can only be shown as
*verified* if its exact text is an entry here, signed off by a named lawyer.

## Adding an entry (a lawyer or a developer working from a lawyer's instructions)

1. Copy the provision's text **exactly** from the official source (for example India Code or an official
   gazette / court website). Do not paraphrase, summarise or type it from memory.
2. Run the helper, which computes the hash for you:

   ```
   python scripts/library_add.py --id ni-act-138 --kind STATUTE_SECTION ^
     --citation "Section 138, Negotiable Instruments Act, 1881" ^
     --alias "Section 138 NI Act" ^
     --text-file path\to\exact-text.txt ^
     --source-name "India Code" --source-url "https://..." ^
     --version "as amended up to <date>" ^
     --verified-by "<lawyer's full name>" --verified-on 2026-10-19
   ```

3. Commit the new file. The commit history is the audit trail of who added what and when.
4. Restart the server (the library is loaded at startup). Check `GET /api/library` shows the entry.

## Drafts and the review gate

A draft goes in `pending/` (copy `pending/_TEMPLATE.json`). Everything there is shown as **UNVERIFIED - pending lawyer review**, whatever the file says about itself,
and can never verify a claim. A lawyer approves it with `python scripts/library_review.py approve --id <id> --reviewer "<name>" --on <date>`, which
checks it is complete, records the reviewer and date, computes the hash and moves it into the library (`IN/` for India). Other countries (`AE`, `UK`, `US`, `SG`)
have folders but are **not supported**: see `lib/jurisdictions.py`. `schema.json` describes the fields.

## What happens to bad entries

An entry is **rejected** (logged, never used) if any required field is missing, `verified_by` is empty,
the `text_sha256` does not match the text, the `kind` is unknown or the id is duplicated.

To withdraw a provision, delete its file (or fix it). Withdrawn entries stop being usable immediately after restart.

## Required fields

`id`, `citation`, `kind` (STATUTE_SECTION | RULE | CASE | OTHER), `text`, `text_sha256`, `source_name`,
`source_url`, `version`, `verified_by`, `verified_on`. Optional: `title`, `aliases` (other ways people cite it).
