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

## Other official sites: added 2026-11-18 (terms NOT read)

The owner supplied official PDFs from six more publishers. Their terms of use have not been read, so under the rule above each stays **off** until the operator records what that site's terms allow (who decided, when) in its own setting. Each switch is separate; none turns on another, and the India Code switch turns on none of them (tested in `backend/tests/test_library_gate.py`).

| Publisher | Setting | Drafts made (unreviewed, mechanical cut, missing section numbers noted on each entry) |
|---|---|---|
| CBIC (Central Board of Indirect Taxes and Customs) | `CBIC_USE_REF` | CGST Act 2017, CBIC copy "as on 01.01.2022": 174 sections, section 151 not found. **Out of date** (amended since). |
| SEBI | `SEBI_USE_REF` | SEBI Act 1992, SEBI copy of January 2020: 83 sections. May be out of date. |
| Ministry of Labour and Employment | `LABOUR_MINISTRY_USE_REF` | none yet (see held back) |
| Central Information Commission | `CIC_USE_REF` | RTI Act 2005, CIC consolidated "as on 18 November 2025": 31 sections. |
| Competition Commission of India | `CCI_USE_REF` | Competition Act 2002, CCI compilation: 70 sections, eight numbers not found (23, 24, 25, 28, 34, 37, 40, 41). Appears older than the 2023 amendment. |
| IP India | `IPINDIA_USE_REF` | Patents Act 1970, consolidated to 1 August 2024: 165 sections, seven numbers not found (5, 95 to 98, 116, 121). |

**Held back, not loaded (the cut found too few sections to trust; the PDFs are kept in `data/legal_sources_raw/.../12_Other_Official_Sources/` and listed in `VIDHI_Other_Official_Manifest.csv` with `Extract = no: <reason>`):** IGST Act 2017 (5 of about 25 found), UTGST Act 2017 (4 of about 25), GST (Compensation to States) Act 2017 (none), CGST Rules 2017 Part A, September 2021 (7 of over 100), SEBI Insider Trading Regulations 2015 (8), SEBI LODR Regulations 2015, original Gazette text (15), Industrial Relations Code 2020 (10 of over 100), Code on Wages 2019 (none). These need a better cutting rule for Acts whose margin headings come before the section numbers, or OCR, or a person to cut them.

**Not copied, because already in the library or not sections:** NCRB Sankalan BNS, BNSS, BSA; IBC 2016 (IBBI copy of 2021); IT Act 2000 "as passed" (superseded by the loaded India Code text); DPDP Act 2023 (already loaded from India Code); the older CGST Rules compilation of November 2020 (the 2021 one is newer); the CGST Rules forms volume of August 2020 (forms, not sections). The "master" and "for review" PDFs are bundles of the same files.

Every draft is `UNVERIFIED - pending lawyer review`. Nothing here was compared with the official page, and a draft can never make a claim verified.
