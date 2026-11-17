# Legal sources: what their terms allow (read 2026-10-26)

This file records what each official source's own published terms say, as read by VIDHI's engineer. It is **not legal advice**; points marked "needs a lawyer to confirm" need an advocate's view.

## India Code (indiacode.gov.in, run by the Legislative Department, Ministry of Law and Justice)
Read in a browser on 2026-10-26: "Term of Use" (page last updated 22 June 2026) and "API Access Procedure".

| Point | What the site says (paraphrased) | Effect on VIDHI |
|---|---|---|
| Who may use the content, and how | You may access, download and print materials for **personal, non-commercial use only**, keeping the copyright notices. | VIDHI is a commercial product. Storing the text in its law library is not personal use. |
| Commercial reproduction | Modification, reproduction, distribution or republication for commercial purposes **without prior written permission is prohibited**. | Written permission is needed before any India Code text is loaded. |
| Automated access | Users agree **not to use any automated means to access the Portal for any purpose without express written permission.** | No script, crawler or API call to India Code without that permission. |
| The API | The "IndiaCode Backend API" is for **authorized organizations**, after a written request to the Legislative Department and its approval; credentials, rate limits and conditions are then issued. | A public-looking API endpoint existed, but using it without approval would go around the stated procedure. |
| Accuracy | Information is "as is"; the portal says its material is an exact reproduction of the officially adopted PDF, the English text prevails in a discrepancy, and it takes no legal liability for completeness or accuracy. | Every loaded section stays DRAFT until a named advocate compares it with the official text. |

**What this changed in the build.** No India Code text has been loaded and none will be until written permission is recorded. In the code, a source whose name or publisher matches India Code always carries `permission_required`, and loading a document or ingesting a version from it is refused until a permission reference is recorded (`POST /api/admin/legal/sources/{id}/permission`). A draft request to the Legislative Department is in `docs/india-code-permission-request.md`. The owner has to send it.

**Disclosure.** While checking whether the site could be read at all (before reading its terms), the engineer made about eight automated read-only requests to India Code (its home page, `robots.txt`, the API root, one search, one section record, the translation file). Nothing from them was stored in VIDHI; only the structure was inspected. No further automated requests were made after the terms were read.

## Legislative Department site (legislative.gov.in)
Its server refused an automated request ("Access Denied", HTTP 403). VIDHI does not work around such a block. Terms not read.

## eGazette of India (egazette.gov.in)
Its certificate could not be validated from the build machine, and its search is behind a CAPTCHA. VIDHI does not bypass CAPTCHAs. Terms not read.

## Possible routes forward (the owner decides)
1. **Ask for permission** from the Legislative Department (the email draft is ready). This is the clean route and would also cover the API.
2. **Ask a lawyer** whether the Copyright Act, 1957 allows reproducing Acts of a legislature in some circumstances, and whether the Government's open-data policy covers any official copy of the Acts. *Needs a lawyer to confirm; nothing here relies on it.*
3. **Individual Ministry sites** sometimes publish the Acts they administer under their own terms; each would need its own terms read and recorded here first.
4. **Buy or license** a commercial legal database under a licence that permits this use.

Until one of these is settled, the law library has no Acts, and every statute reference in Authority Check says "Not in reviewed library".
