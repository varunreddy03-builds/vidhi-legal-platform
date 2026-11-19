# VIDHI

**AI assists. Sources support. Graphs connect. Logic verifies. Lawyers decide.**

**Try it (demo):** https://macintosh-acids-touch-chan.trycloudflare.com . It runs on the owner's own computer through a free Cloudflare tunnel, so it is only there while that computer is on, the address changes when it restarts, sign-up is by invitation, and it holds no real client data. Use invented documents only.

VIDHI is an AI legal workflow platform for India, written as a prototype. It is **not** legal advice, it is **not** a lawyer, and it has **not** been tried with real clients.

## What it is

* **Legal Intelligence**: matters and documents, research with source-checked answers, drafting, a Word-style editor and a PDF reader, judgments search, and a directory of courts, official portals, legal aid bodies and Law Commission reports. Also: a **Vault** (many documents at once, a summary of each and one review table with a checked quote and page for every answer), a **Tax** workspace that carries no tax law of its own, **Translate and transcribe** (a program check that every number survived), **review requests** between colleagues, a **client portal** that can show a client a filtered graph of the documents shared with them, a read-only **Microsoft 365** connection (not yet run against a live tenant; iManage is not built), and a reviewer sign-off register in which advocates are shown only by code.
* **VIDHI Legal Katalyst**: five checks written as plain code (no AI decides them): Authority Check, Deadline engine, Old-code to new-code checker, Pre-filing defect check, and List of dates with page references. Add-ins for Word and Google Docs are in `addins/`.
* **Legal Recovery**: a small free helper for people owed money. It is in the code but **switched off by default** (`RECOVERY_ENABLED`).

## The rules the code enforces

1. **Never invent law, sections or citations.** A claim is `VERIFIED` only when its exact words are found in a source that was checked; otherwise `PARTIALLY_VERIFIED` or `UNSUPPORTED`. The label is decided by code (`backend/lib/verify.py`, `backend/lib/textmatch.py`), never by the AI model.
2. **Neutral wording.** The app flags differences between documents; it never says someone lied.
3. **Documents are data, not instructions.** Uploaded text is fenced before an AI model sees it.
4. **No secrets in code.** Keys come from the environment; see `.env.example`.

## What is NOT in this repository

* **No Acts or other law text.** The law library is empty on purpose: copying the text of Acts needs the publisher's permission, and a lawyer must check every provision before it can verify anything. `backend/data/legal_library/README.md` explains how a reviewed entry is added.
* **No real judgments.** The judgments search reads two public datasets (loaders in `backend/scripts/`): *Indian High Court Judgments* and *Indian Supreme Court Judgments*, by Dattam Labs, from the eCourts website, licence CC-BY-4.0 (https://registry.opendata.aws/indian-high-court-judgments). Attribution is kept on every record.
* **No customer data, keys or deployment secrets.**

## Status, honestly

* The backend test suite of this very copy passes (about 11,700 tests; a few tests of private data and recorded evaluation runs were left out with that data), and the front end type-checks, lints, passes its 196 unit tests and builds. But **the AI answers have never been measured with a real AI key on real questions**, and the Hindi and Telugu answers are untested. The Old-code to New-code checker has no mapping tables here (they contain Act text), so it starts empty.
* The law library has **no reviewed entries**; legal statements therefore come out `UNSUPPORTED` or "No supporting authority found" until a named advocate reviews sources.
* The server package (`docker-compose.yml`, `deploy/`) has never been run on a real server.
* Optional meaning-based search (`backend/lib/embeddings.py`) and re-ranker are off by default.

## Layout

| Folder | What is in it |
|---|---|
| `backend/` | FastAPI and MongoDB: routers, the verification rules in `lib/`, tests in `tests/` |
| `frontend/` | React, Vite and TypeScript web app; unit tests and Playwright browser tests |
| `mobile/` | Capacitor wrapper for Android |
| `addins/` | Word and Google Docs add-ins |
| `deploy/`, `docker-compose.yml` | One-server deployment with HTTPS and encrypted backups |
| `docs/` | Architecture, deployment and runbooks |

## Running it locally

Needs Python 3.11, Node 22, Yarn and MongoDB 7. Copy `.env.example` to `backend/.env` and fill in only what you need; outside services (AI, e-mail, payments) are faked in development.

```
cd backend && pip install -r requirements.txt && uvicorn server:app --port 8001
cd frontend && yarn install && yarn dev
```

Tests: `pytest` in `backend/`, and `yarn typecheck && yarn lint && yarn test` in `frontend/`. See `docs/RUNBOOK.md` and `docs/DEPLOYMENT.md`.

## Licence

All rights reserved. The code is public to be read; see `LICENSE`.
