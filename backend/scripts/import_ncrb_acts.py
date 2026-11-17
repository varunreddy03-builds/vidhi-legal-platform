"""Loads the three Ministry-portal Acts (BNS, BNSS, BSA) from the draft files into the structured law store as UNREVIEWED provisions, using the same code as POST /admin/legal/import-drafts.

Needs NCRB_PORTAL_USE_REF in backend/.env (who decided, and when): without it the drafts are not loaded and the import is refused. Nothing it loads is verified: a named reviewer must sign each provision.
Safe to run again: an Act whose version is already stored is reported, not duplicated.

    python scripts/import_ncrb_acts.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import db, library, legal_store  # noqa: E402

SOURCE = {
    "name": "NCRB Sankalan portal (Ministry of Home Affairs)", "publisher": "National Crime Records Bureau, Ministry of Home Affairs", "jurisdiction": "IN", "document_types": ["act"],
    "access_method": "public-page", "licence_note": "No licence or reuse terms are stated on the portal pages (read 2026-11-03). Used on the owner's decision as UNVERIFIED drafts; a lawyer's view is advised before users see it.",
    "terms_checked_on": "2026-11-03", "known_limits": "No consolidation date, amendment history or commencement date is printed on these pages. The portal's own comparison labels were cut from headings.",
    "permission_required": True,
}
ACTS = [
    ("ncrb-bns", {"title": "The Bharatiya Nyaya Sanhita, 2023", "short_names": ["BNS"], "kind": "act", "year": 2023, "jurisdiction": "IN"}),
    ("ncrb-bnss", {"title": "The Bharatiya Nagarik Suraksha Sanhita, 2023", "short_names": ["BNSS"], "kind": "act", "year": 2023, "jurisdiction": "IN"}),
    ("ncrb-bsa", {"title": "The Bharatiya Sakshya Adhiniyam, 2023", "short_names": ["BSA"], "kind": "act", "year": 2023, "jurisdiction": "IN"}),
]


async def main() -> None:
    ref = (os.environ.get("NCRB_PORTAL_USE_REF") or "").strip()
    if len(ref) < 10:
        sys.exit("NCRB_PORTAL_USE_REF is not set in backend/.env: nothing was loaded.")
    print("writing to database:", os.environ["DB_NAME"], "(the dev app uses vidhi_dev: set DB_NAME=vidhi_dev, because backend/.env names a different database)")
    sync = await library.sync_library()
    print("drafts synced:", {k: v for k, v in sync.items() if not isinstance(v, (list, dict))})
    src = await db.db.legal_sources.find_one({"name": SOURCE["name"]}, {"_id": 0})
    if not src:
        src = await legal_store.register_source(dict(SOURCE))
    if not (src.get("permission_reference") or "").strip():
        src = await legal_store.record_permission(src["id"], ref, "owner decision (import_ncrb_acts.py)")
    print("source:", src["id"])
    for act_id, instrument in ACTS:
        try:
            out = await legal_store.ingest_drafts(act_id, src["id"], instrument, "other", evidence="As printed on the NCRB Sankalan portal. Chapters and Sections page of the NCRB Sankalan portal, retrieved 2026-11-03; no consolidation date is printed on it")
            print(act_id, {k: v for k, v in out.items() if k != "warnings"}, "| warnings:", len(out.get("warnings", [])), (out.get("warnings") or [""])[:3])
        except ValueError as exc:
            print(act_id, "REFUSED:", str(exc)[:300])


if __name__ == "__main__":
    asyncio.run(main())
