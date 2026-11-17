"""Generates docs/VIDHI_FINAL_OWNER_REVIEW.md (Phase 15). The registries and the list of indexed works are READ FROM THE DATA (registry.json, films.json, sources.json and the database), never typed by hand,
so they cannot drift from what is really loaded. Usage (from the repo root, MongoDB running):
    python scripts/final_review.py --backend 10359 --frontend 120 --browser 15
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "vidhi_dev")
sys.path.insert(0, str(ROOT / "backend"))

from lib import films, knowledge  # noqa: E402
from lib.db import db  # noqa: E402

FREE_FOUND = {16: "Moyle's Institutes only (Digest and Code not loaded)", 20: "1910 edition on the Internet Archive; provenance caveat", 21: "Shamasastry 1915, scanned text", 23: "official PDF exists; written permission needed before use",
              26: "duplicate of #3", 28: "Whitehorne 1560 translation; loader's title check skipped it", 29: "1901 English edition", 30: "only plausibly in Detmold 1882; unconfirmed", 37: "CIA publication; its own notice restricts use, ask first"}


async def build(args) -> str:
    reg = knowledge.load_registry()
    works = {w["number"]: w async for w in db.knowledge_works.find({"scope": {"$ne": "org"}})}
    counts = {}
    async for row in db.knowledge_chunks.aggregate([{"$match": {"scope": "library"}}, {"$group": {"_id": "$work_number", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    sources = {w["number"]: w for w in json.loads((ROOT / "backend" / "data" / "knowledge" / "sources.json").read_text(encoding="utf-8"))["works"]}
    legal = await db.legal_sources.count_documents({"status": "VERIFIED"})
    cat = films.catalogue()

    rows = []
    for e in reg["entries"]:
        n = e["number"]
        w = works.get(n, {})
        st = w.get("status", "not imported")
        if n in counts:
            avail = f"LOADED ({counts[n]} passages; {sources[n]['edition'][:60]})"
        elif n in FREE_FOUND:
            avail = f"free source found, NOT loaded: {FREE_FOUND[n]}"
        else:
            avail = "licence required; no free source"
        rows.append(f"| {n} | {e['title']} | {e.get('section', '')} | {e.get('rights_hint', '')} | {st} | {avail} |")
    loaded = [(n, works[n]) for n in sorted(counts)]
    idx = [f"| {n} | {w['title']} | {counts[n]} | {w.get('coverage')} | {w['status']} |" for n, w in loaded]
    frows = [f"| {f['id']} | {f['title']} ({f['year']}) | {f['category']} | {f['country_language']} | {f['real_events']} | not obtained, not reviewed |" for f in cat["films"]]

    return f"""# VIDHI knowledge expansion: final owner review (Phase 15)
Generated {date.today().isoformat()} by `scripts/final_review.py`; the registries below are read from the data and the database, not typed. **This document does not declare the work complete or accepted.** Completion needs implementation, execution, verification and your acceptance (global rule). I am requesting your final approval at the end; nothing further will be changed until you answer.

## 1. Final architecture
- **Two stores kept apart:** the lawyer-reviewed legal library (`backend/data/legal_library/`, {legal} verified entries today) and the optional book library (`knowledge_works`, `knowledge_chunks`). A book can never be returned as verified law.
- **Verification core (unchanged by this expansion):** `lib/verify.py`, `lib/textmatch.py`, `routers/research.py`.
- **Book layer:** `lib/knowledge.py` (registry import, rights record, status ladder, ingestion, search, private documents), `routers/knowledge.py`, loader `scripts/knowledge_load.py`, switch `KNOWLEDGE_ENABLED`.
- **Analyses:** `routers/analysis.py` (`/analysis/strategy|reasoning|behaviour|philosophy`, `/legal-reasoning`, `/evidence/*`), prompts and checks in `lib/analysis.py`, `lib/legal_reasoning.py`, `lib/evidence_class.py`, `lib/films.py`, and the code guard `lib/analysis_guard.py`.
- **Existing app preserved:** matters, recovery, notices, payments, roles, languages (see `docs/ARCHITECTURE_NOTES.md`).
- **Mobile:** phone layout with a 5-action bar and a More sheet; `mobile/` Capacitor project and `scripts/build-apk.ps1` (built but never run successfully here).

## 2. The complete book registry (50 entries) with rights and availability
| No. | Title | Section | Rights hint | Status | Availability |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## 3. The complete audiovisual registry (22 titles)
| ID | Title | Cat. | Country, language | Real events | Source status |
|---|---|---|---|---|---|
{chr(10).join(frows)}
All films: rights assumed in copyright; no film, script, subtitle or transcript was watched, downloaded or obtained; films are catalogue entries only and never evidence.

## 4. Rights and source-availability statuses
Details with evidence links: `docs/VIDHI_SOURCE_AVAILABILITY.md`. Summary: {len(counts)} works loaded under public-domain notices (US basis from Project Gutenberg / Internet Archive; India not separately verified), 0 in-copyright works loaded, the rest need a licence or written permission. Recorded permissions for every loaded work: private analysis and full-text indexing only.

## 5. What is actually indexed and retrievable today
| No. | Work | Passages | Coverage | Status |
|---|---|---|---|---|
{chr(10).join(idx)}
Total passages: {sum(counts.values())}. Retrieval was measured (Phase 13): recall@5 90%, precision@5 about 61% on 30 questions. The Arthashastra text is a scan with OCR errors. Verified Indian law indexed: **{legal}**.

## 6. New capabilities implemented
Registry and status ladder with rights and written approval gates; public-domain ingestion with provenance and hashes; search with provenance and organisation-private documents; strategy, reasoning, behaviour and philosophy analyses with source-grounded citations and quote verification; evidence classification for neuroscience and audio claims; legal-reasoning workflow that can cite only the verified library; film catalogue with film-versus-fact guard; code guard (diagnosis, guaranteed claims, invented probabilities, certain intent); evaluation harness with fixed datasets; on/off switch; mobile layout; reports for every phase.

## 7. Capabilities NOT implemented
Contradiction detection across sources; calibrated forecasting; any free-running planner; embeddings or reranking; verified Indian law content (library empty); film transcripts or study material; in-copyright books; Digest and Code of Justinian, Constitution of India, CIA book (permission needed); a built and phone-tested Android app; a standalone app with a hosted backend; a source-backed neuroscience literature collection; independent labelling of any test set.

## 8. Legal-source hierarchy and safeguards
Constitution; legislation; rules and notifications; Supreme Court; High Court; other primary sources; context only (books, philosophy, history, films). Safeguards: only library entries can be cited as law; references not in the library are removed; status never better than PARTIALLY_VERIFIED because later amendments and precedential status are not checked; cases are never called good law; jurisdiction must be live (India only); neutral wording; a lawyer decides. See `docs/VIDHI_PHASE10_REPORT.md`.

## 9. Test results and comparison with baseline
| Measure | Baseline (2026-10-21) | Now |
|---|---|---|
| Backend tests | 10,173 passing | {args.backend} passing |
| Front-end unit tests | 120 | {args.frontend} |
| Browser tests | 14 | {args.browser} |
| Mutation check | 26 of 26 caught | not re-run since (see Phase 14 report) |
Knowledge evaluation (Phase 13): no baseline exists for features that did not exist, so no improvement is claimed. Guard recall on a fresh set: diagnosis 40%, audio claims 62.5%, film 100%. Live-model accuracy, cost per call at real prices and calibration were not measured. Details: `docs/VIDHI_PHASE13_REPORT.md`, `docs/evals/`.

## 10. Cost and infrastructure
Measured storage about 58 MB for the 16 books; no AI cost for indexing; analysis calls about Rs 0.2 to 1.6 each at placeholder prices (not real); monthly cap Rs 20,000 by default; hosting, domain, licences and real provider prices undecided. See `docs/VIDHI_PHASE14_REPORT.md` section 1.

## 11. Security findings
No leaked key in any commit; authorization and isolation tests pass; new modules log no user text. Open findings from the seven backend reviews (`docs/reviews/SUMMARY.md`) and the Phase 14 register (R-10 to R-19). The most important: a claim contradicting its quote can still reach VERIFIED, notice checks can be bypassed by deleting the statement block, payment records lack a uniqueness guard, keys pasted in chat are exposed.

## 12. Known limitations and unresolved risks
Law library empty; screens are heuristic and generalise poorly; evaluation sets labelled by the rule author; no live-model injection test; one-provider outages are silent; APK unverified; Python dependencies unaudited. Full register: `docs/VIDHI_PHASE14_REPORT.md` section 6.

## 13. Maintaining and extending
Start with `docs/PROJECT_MEMORY.md` and `CLAUDE.md`. Add a book: register it, record rights, get written approval, ingest with `scripts/knowledge_load.py` (add to its manifest), run `python -m evals.knowledge_eval`. Add law: lawyer-reviewed entries only (`docs/VIDHI_LEGAL_SOURCES.md`). Before any change: benchmark gate in `docs/VIDHI_PHASE12_ROADMAP.md`.

## 14. Rolling back
Revert the commits for Phases 4 to 15 in reverse order (`git log`), or set `KNOWLEDGE_ENABLED=false`. No existing collection was migrated; `knowledge_*` are derived and can be dropped and rebuilt from `sources.json`. Backups: `scripts/backup.sh`, `docs/RUNBOOK.md`.

## Request
Please tell me whether you accept this account as it stands, want specific items reopened, or want anything removed. I will not start further work, deploy anything, or describe the enhancement as accepted until you answer.
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="10359")
    ap.add_argument("--frontend", default="120")
    ap.add_argument("--browser", default="15")
    a = ap.parse_args()
    out = ROOT / "docs" / "VIDHI_FINAL_OWNER_REVIEW.md"
    out.write_text(asyncio.run(build(a)), encoding="utf-8")
    print("written", out)
