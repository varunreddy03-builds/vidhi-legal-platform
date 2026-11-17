# VIDHI AI Checker for Word and Google Docs

Two small add-ins that put four Legal Katalyst checks beside the draft being written. The checks are plain code on the VIDHI server (no AI), the same readers as the Katalyst screens.
Every finding only points to a place to look. A lawyer decides.

| Check | What it does | Where it stops |
|---|---|---|
| Authority and citations | Reads cited cases and Acts. Labels: `VERIFIED`, `PARTLY_VERIFIED`, `NOT_SUPPORTED`. | `VERIFIED` only for a provision in VIDHI's reviewed library. A case found in the open dataset is at most `PARTLY_VERIFIED`. Current status of a case or Act is not checked. Off unless `AUTHORITY_CHECK_ENABLED=true`. |
| Old code to new code | Finds IPC, CrPC and Evidence Act references. | A suggested replacement exists only when a named reviewer marked a one-to-one, exact mapping in the reviewed store, and the text names exactly one section. Otherwise "no verified mapping is recorded". The fixed caveat (VIDHI has not decided which text applies) is on every finding. Off unless `OLD_CODE_CHECK_ENABLED=true`. |
| Pre-filing defects | Blanks, placeholders, numbering gaps, annexure gaps. | Knows no court's rules. Off unless `DEFECT_CHECK_ENABLED=true`. |
| List of dates | Every date written, with where it is. | Does not work out limitation. Off unless `DATE_LIST_ENABLED=true`. |

A check that is switched off is reported as off, never as clean.

## Server side (already in the app)

- `POST /api/v1/katalyst/analyze-text` - paragraphs (or raw text) in; findings with `start_index` / `end_index` (Unicode code points), `defect_type`, `status_label`, `suggested_replacement`, `reviewer_source_note` out.
- `POST /api/v1/katalyst/redline-docx` - a `.docx` in; the same file with native Word comments (and, only if `apply_replacements=true`, tracked changes for reviewed suggestions) plus a one-page "Pre-Filing Scrutiny Audit Summary" (PDF) and the JSON report out, as base64 in one JSON answer.
- `POST/GET/DELETE /api/v1/katalyst/keys` - add-in keys for Google Docs (below). Backend code: `backend/lib/katalyst_addin.py`, `docx_redline.py`, `katalyst_audit.py`, `addin_keys.py`, `backend/routers/katalyst_addin.py`.

## Word (Windows, Mac, web)

The task pane is a page of the VIDHI app itself (`/addin/word`), so the person's normal sign-in applies and nothing else is called. Source: `frontend/src/addin/` (`wordService.ts`, `TaskPane.tsx`). Needs WordApi 1.4.

1. Edit `addins/word/manifest.xml`: replace every `https://YOUR-VIDHI-ADDRESS` with the https address of the VIDHI app and the `Id` with a new GUID.
2. **Server headers (a deploy step, not done here).** The app sends `X-Frame-Options: DENY` and a strict Content-Security-Policy (`deploy/security-headers.conf`). Word on the web shows the pane in a frame and the pane loads `https://appsforoffice.microsoft.com/lib/1/hosted/office.js`. For the path `/addin/` only, the production server must allow that script and allow framing by the Office hosts. Keep every other path strict. Do not loosen the headers of the whole site.
3. Try it: Word, Insert > Add-ins > My Add-ins > Upload My Add-in (Word on the web) or sideload from a shared folder (desktop). Open "VIDHI AI Checker" on the Home tab. Sign in to VIDHI in a browser first.
4. Scan document: findings in three groups plus the list of dates. Click a card to select those words in the document. "Add comment" puts a native Word comment. "Replace with ..." (only shown for a reviewed suggestion) turns Track Changes on, replaces the words, then puts the person's earlier tracking mode back, so the lawyer accepts or rejects it in Word.

## Google Docs

Apps Script files: `addins/google-docs/Code.gs`, `Sidebar.html`, `appsscript.json`. A Google add-on cannot use the browser's sign-in cookie, so it uses an **add-in key**:

- Made in VIDHI by a signed-in person (`POST /api/v1/katalyst/keys`), shown once, kept only as a hash, expires in 30 days (`ADDIN_KEY_DAYS`, 1 to 90), at most five live keys, removable at once.
- It works for the two check routes above and nothing else: not the app, not a matter, not another key. It stops working at once if the person is blocked.
- The VIDHI address and the key are kept in the person's own Apps Script user properties, never in the document.

Setup: create an Apps Script project bound to a Google Doc (or a standalone add-on project), paste the three files (replace `YOUR-VIDHI-ADDRESS` in `appsscript.json`), reload the document, open Extensions > VIDHI AI Checker, enter the address and the key under Settings, then Scan. "Highlight" colours the words and selects them. "Replace" edits the text directly after a confirmation: **Google Docs cannot be put in suggestion mode by a script**, so it is not a tracked change; File > Version history undoes it.

## What has and has not been tested

Tested: the backend (positions, labels, the rule that a suggestion needs a reviewed one-to-one mapping, tracked changes and comments in the produced `.docx` read back with python-docx, keys: scope, expiry, removal, block, other organisations), the pane's helper functions (unit tests), and the pane page outside Word (browser test with the accessibility scan). The Apps Script and the Office manifest have only been syntax-checked.

**Not tested (needs real Word / Google Docs, which could not be run here):** the Word task pane inside Word (reading paragraphs, `range.select()`, comments, tracked replacement), the Word-on-the-web framing and header carve-out, the manifest's load in Word, and everything in the Google Docs add-on running inside Google Docs (menu, sidebar, highlight, replace, `UrlFetchApp` calls). Try each once on a copy of a draft before relying on it. A produced `.docx` was not opened in Word itself; its comments and tracked changes were checked as XML and with python-docx.

Known limits: findings inside text boxes, headers and footers are not read (body and table paragraphs are). In the Word-file check, a paragraph holding parts such as fields that cannot be matched exactly is left unmarked and listed as skipped. The chronology check is the list of dates plus the date reader's own notes (for example, a date later than today); it does not compare dates between documents.
