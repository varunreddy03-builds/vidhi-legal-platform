# VIDHI architecture decisions for the legal-data layer (Phase 2)

Date: 2026-10-20. This document decides the shape of what Phases 3 to 8 will build. It changes no application behaviour. Where it names a technology, nothing has been installed or downloaded. Existing architecture is described in `docs/ARCHITECTURE_DECISIONS.md` and `CLAUDE.md`; this file adds to it.

## 1. Decisions

| # | Decision | Status |
|---|---|---|
| D-1 | **Keep MongoDB.** Add MongoDB text indexes and exact-citation indexes for legal text. No vector store now. | Approved 2026-10-20 |
| D-2 | **OCR:** benchmark Tesseract (eng, tel, hin) against the current hosted OCR before adopting; hosted OCR stays as fallback. | Approved (plan only; installs need separate approval with sizes) |
| D-3 | **Local models:** no download until the evaluation harness exists; first candidates are small Qwen3 / Gemma3 variants for classification and query rewriting only. | Approved (plan only) |
| D-4 | **Verification stays in code and stays library-gated.** Ingested legal text is stored as *unreviewed candidate* and can never produce VERIFIED until a named lawyer approves it through the existing review path. | Rule carried over from the owner's earlier instructions |
| D-5 | **Official sources only, manual-first.** Legal text enters from official publications (India Code, gazettes, court sites). Each source is checked (live page, terms, CAPTCHA, any API) before design; where automation is not permitted or practical, a person supplies the official PDF and VIDHI records provenance. | Proposed; applies source by source |
| D-6 | **Reuse the existing review gate** (`lib/library.py`, `scripts/library_review.py`) rather than a second approval system. | Proposed |
| D-7 | **Jobs in MongoDB** (leases, retry counts) for OCR and ingestion; no new queue service. | Proposed |
| D-8 | **Semantic search only if measured to help** and never as the only way to find a citation. | Proposed |

Open: the reviewing lawyer's identity, the priority order of Acts (proposed order in section 8), and the removal list for tracked leftovers (Phase 3).

## 2. What stays as it is

Authentication and role table; per-organisation scoping; spend cap; encrypted file storage; prompt-injection fencing; verification code (`lib/verify.py`); templates, portal, reminders, payments, help. The legal-data layer is added beside them.

## 3. Data model (new MongoDB collections)

All legal-data collections hold **shared public text**, not customer data, so they carry no `organization_id`. Customer-facing answers that cite them remain organisation-scoped. Every new customer-data route still gets cross-organisation tests.

* `legal_sources`: registry. Fields: `id`, `name`, `publisher`, `jurisdiction`, `document_types`, `access_method` (`manual-supplied | public-page | api`), `licence_note`, `terms_checked_on`, `robots_or_captcha_note`, `update_frequency`, `known_limits`, `coverage` (counts measured by the system, never typed by hand), `status`.
* `legal_documents`: one row per acquired file. `id`, `source_id`, `source_page_url`, `file_url` (if one was found), `title`, `issuing_authority`, `published_on`, `effective_on` (nullable), `version_label`, `supersedes_id`, `sha256`, `format`, `licence_note`, `retrieved_on`, `ocr_status`, `index_status`, `stored_file_id` (encrypted GridFS).
* `instruments`: an Act, Code, Rule or Notification as a concept. `id`, `title`, `short_names`, `kind`, `jurisdiction`, `year`.
* `instrument_versions`: `instrument_id`, `document_id`, `label` (original, amendment, consolidated), `effective_from`, `effective_to`, `evidence` (required whenever a date is set), `repealed_by` (with evidence).
* `provisions`: the **canonical parent**. `id`, `instrument_version_id`, `path` (part/chapter/section/subsection), `heading`, `components` (ordered list of `rule | proviso | explanation | illustration | exception | schedule-entry` with text and page), `text_full`, `review_status` (`unreviewed | reviewed`), `reviewed_by`, `reviewed_on`, `content_sha256`.
* `provision_chunks`: children for long provisions: `parent_id`, `ordinal`, `text`, `component_range`. A chunk never exists without its parent, and retrieval always returns the parent context.
* `code_mappings`: schema in section 6.
* `judgments` (Phase 4, after statutes): section 7.
* `jobs`: `id`, `kind`, `payload`, `state`, `lease_until`, `attempts`, `last_error`, `result_ref`.

Existing `legal_library` files remain the **only** verifier. A `reviewed` provision is exported to the library format (exact text, source, version, SHA-256, named verifier) so verification has one path.

## 4. Retrieval design

1. **Exact first:** parse citations ("Section 420 IPC", "s. 103 BNS", case identifiers) and look up by structured fields; never let a semantic step override an exact hit.
2. **Full-text:** MongoDB text index over `heading` and `text_full` with language-aware analyzers where available; Indian scripts handled by the existing tokenisation helper (`lib/text.py`, `lib/query_lang.py`).
3. **Metadata filters:** instrument, version date, jurisdiction, court.
4. **Parent expansion:** results are expanded to the full parent provision (rule, provisos, explanations, exceptions) before the model sees them. A test fails if a proviso is dropped.
5. **Semantic layer:** not built; adopted only if the evaluation shows a recall gain without harming exact retrieval (D-8).
6. **Answer contract:** statements link to a provision id and version; the date of conduct, when given, selects the version; otherwise the answer says which version it used and why.

## 5. Source ingestion policy

For each source (before any code): record the live URL and what is actually served; read the terms and robots rules; note CAPTCHAs, rate limits and whether an API exists (do not assume one); decide `manual-supplied`, `public-page` or `api`. Never bypass a CAPTCHA, never bulk-download beyond what terms allow, never hardcode a guessed file URL. Every acquired file is hashed, stored encrypted, and registered with provenance. Failed or inaccessible material is recorded as such, not as retrieved. Sources named in the directive (India Code, Legislative Department, e-Gazette, Telangana Gazette and portal, Supreme Court, Telangana High Court and district courts, eCourts, MSME Samadhaan and Ministry) are all **unchecked** today.

## 6. Code-mapping record (IPC to BNS, CrPC to BNSS, Evidence Act to BSA)

One row per relationship, directional pairs created together so reverse lookup is a query, not a guess:

`id`, `legacy_instrument`, `legacy_provision`, `new_instrument`, `new_provision`, `relationship` (`one-to-one | partial | split | merged | modified | absent | unresolved`), `legacy_text_ref`, `new_text_ref` (exact text from provisions), `differences_in_effect`, `commencement` (with evidence), `transitional_and_saving` (links to the provisions or notifications involved), `verified_on`, `reviewer`, `review_status`, `confidence` (only `reviewed` or `unreviewed`, no invented numbers), `authorities` (supporting sources).

Rules: matching numbers or similar headings never create a mapping; an unmapped provision displays "no verified mapping"; a legacy lookup shows the verified newer cross-reference plus the fixed caveat that applicability depends on the facts, relevant dates, commencement and saving provisions; the newer provision is never substituted automatically into a historical case.

## 7. Judgments (Phase 4, after statutes)

`judgments`: `court`, `date`, `identifier`, `bench`, `kind` (final | interim), `paragraphs` (numbered text), `propositions` (each linked to paragraphs), `status`, `subsequent_treatment` (only with source), `authority_level` (binding or persuasive relative to the forum, stated with reason), `source_id`. Conflicting judgments are shown together; publication date and semantic similarity never resolve a conflict.

## 8. Proposed order of work for the legal data (for the lawyer to confirm)

1. BNS, BNSS, BSA and the legacy IPC, CrPC, Indian Evidence Act (largest user need; mapping depends on all six).
2. MSMED Act 2006 (Sections 15 to 18 first), Commercial Courts Act 2015, Arbitration and Conciliation Act 1996.
3. Constitution of India.
4. IT Act 2000 and data-protection law (check commencement of the 2023 Act and its rules first).
5. Telangana Acts, rules, notifications and High Court rules (source check first).
6. Judgments: Supreme Court, then Telangana High Court.

Throughput is limited by lawyer review, not engineering; ingestion may run ahead of review because unreviewed text cannot verify anything.

## 9. Documents and OCR design

* Keep `pypdf`/`python-docx`. Add table and heading capture only where tests show loss.
* OCR chain: embedded text, then Tesseract (when installed and benchmarked), then hosted vision model. Each page records `engine`, `languages`, `warnings`, and `confidence` **only when the engine really reports one**. Low-confidence or unreadable pages are marked uncertain and cannot be shown as verified statutory wording.
* Official law PDFs use the same chain, then enter the provision parser; a human reviews parser output for the provisions above before they can be reviewed as law.

## 10. Models, cost and caching

* Routing: unchanged for existing features; cheaper or local models are used only for low-risk steps (classification, query rewriting, structured extraction) and only after passing the benchmark. The verification code is model-independent.
* Benchmark harness: a version-controlled evaluation set (extended per R-31) run against named models; records exact model id, date, citation support, unsupported-claim rate, language quality, latency, memory and cost per request.
* Hardware: laptop-class (about 16 GB RAM, small GPU) caps local model size; a model is chosen from measurements, not parameter count.
* Caching: only public retrieval results keyed by source version; amendments invalidate; private answers are never cached across users.

## 11. Phases 3 to 8: scope and gates

| Phase | Scope | Main acceptance | Needs your approval for |
|---|---|---|---|
| 3 Critical fixes | Remove old-platform leftovers tracked in git (listed file by file first) and delete the local, untracked test-credentials file; install and run a secret scanner and dependency audit; fix findings; add cross-org tests as new routes appear | Scanners clean or each finding resolved; no tracked credential; tests green | The exact file removal list; installing scanners |
| 4 Legal data | Source registry, provenance, structure schema, versions, parser, mappings, hybrid and parent-child retrieval, evaluation extension | Provisions retrievable with provisos intact; mappings reviewed; unreviewed text cannot verify | Each source after its terms check; the reviewing lawyer |
| 5 Documents | OCR benchmark, page-level metadata, resumable jobs | Benchmark report; killing a job mid-run loses nothing | Installing Tesseract and Poppler (sizes shown first) |
| 6 Cost | Routing, caching, limits, measured cost model, optional local model | Cost doc with measured figures; accepted model passes criteria | Any model download (sizes shown first) |
| 7 Product | Coverage dashboard, source views, multilingual refinements, accessibility of new screens | Axe sweep includes new pages | Feature scope |
| 8 Release | Regression, security, restore drill, legal-quality gate, deployment checks | `docs/VIDHI_TEST_REPORT.md`; readiness label | Go decision |
