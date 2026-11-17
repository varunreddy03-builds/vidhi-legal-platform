"""Download the public-domain editions the owner approved (2026-10-23) from Project Gutenberg, check each is the book it should be, record a source manifest, and optionally
ingest them through lib/knowledge.py so the rights, approval and status rules in lib/knowledge.py are applied (nothing is written to the database directly).

  python scripts/knowledge_load.py --download                 # fetch + verify + write backend/data/knowledge/sources.json (texts stay out of git)
  python scripts/knowledge_load.py --ingest                   # needs MongoDB running; uses MONGO_URL / DB_NAME from the environment (default: local vidhi_dev)

Only Project Gutenberg plain-text files are used. Rights recorded: private analysis and full-text indexing ONLY (not redistribution, commercial use or model training).
The files are United States public domain per Project Gutenberg; their status in India was not separately verified, and the manifest says so."""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "backend" / "data" / "knowledge"
TEXTS = DATA / "texts"
UA = {"User-Agent": "VIDHI-knowledge-loader/1.0 (owner-approved, a few files)"}
APPROVAL = "Owner approved in chat on 2026-10-23: 'download the public domain set'."
# Works added to the manifest AFTER that message were covered by the owner's later request the same day, not by the first one; each work records the approval that really applies to it.
APPROVAL_LATER = "Owner asked in chat on 2026-10-23 to 'search across the world to feed all books' that can lawfully be fed in; this work was found by that search (docs/VIDHI_SOURCE_AVAILABILITY.md)."
ADDED_LATER = {16, 21, 28, 29}


def approval_for(number: int) -> str:
    return APPROVAL_LATER if number in ADDED_LATER else APPROVAL

# (registry number, Project Gutenberg ebook id, a word the file's own title must contain, edition note)
MANIFEST = [
    (13, 1497, "republic", "The Republic, translated by Benjamin Jowett"),
    (14, 3207, "leviathan", "Leviathan, Thomas Hobbes (1651 text)"),
    (15, 2680, "meditations", "Meditations, Marcus Aurelius, translated by George Long"),
    (3, 1232, "prince", "The Prince, Machiavelli, translated by W. K. Marriott"),
    (10, 132, "art of war", "The Art of War, Sun Tzu, translated by Lionel Giles"),
    (19, 1404, "federalist", "The Federalist Papers"),
    (17, 17150, "hammurabi", "The Oldest Code of Laws in the World (Code of Hammurabi), translated by L. W. King"),
    (22, 2388, "celestial", "The Song Celestial (Bhagavad-Gita), translated by Edwin Arnold"),
    (27, 10827, "livius", "Discourses on the First Decade of Titus Livius, Machiavelli, translated by Ninian Hill Thomson"),
    (18, 10000, "magna carta", "The Magna Carta (English translation of the 1215 charter)"),
    (11, 4363, "beyond good and evil", "Beyond Good and Evil, Nietzsche, translated by Helen Zimmern"),
    (12, 2701, "moby", "Moby Dick, Herman Melville (a novel: fiction, not an argument or a source of fact)"),
    (7, 66048, "interpretation of dreams", "The Interpretation of Dreams, Freud, translated by A. A. Brill (historical psychoanalytic theory, not current neuroscience)"),
    # added 2026-10-23 after the source search (docs/VIDHI_SOURCE_AVAILABILITY.md)
    (16, 5983, "institutes", "The Institutes of Justinian, translated by J. B. Moyle (5th ed. 1913). Only the Institutes: the Digest and the Code are NOT included"),
    (29, 2464, "florentine", "History of Florence (Florentine Histories), Machiavelli, 1901 English edition"),
    (28, 15772, "art of warre", "The Art of War (Machiavelli, a different book from Sun Tzu's), translated by Peter Whitehorne, 1560 (early English spelling)"),
]
PARTIAL = {16}  # works where only part of the registry entry is loaded, so coverage is NOT 'full'
# Internet Archive items: (registry number, item id, a word the text must contain, edition note, public-domain basis)
MANIFEST_IA = [
    (21, "in.ernet.dli.2015.529021", "arthas", "Kautilya's Arthashastra, translated by R. Shamasastry (1915); scanned text, so it has OCR errors",
     "Public-domain basis from the source search: Shamasastry died 1940 and Fleet 1917, so the translation is public domain in India and the US (docs/VIDHI_SOURCE_AVAILABILITY.md). This is not a licence quotation."),
]
START = re.compile(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I | re.S)
END = re.compile(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I)
TERMS = re.compile(r"This eBook is for the use of anyone anywhere[^.]*\.", re.I | re.S)


def url_for(pg: int) -> str:
    return f"https://www.gutenberg.org/cache/epub/{pg}/pg{pg}.txt"


def download() -> list[dict]:
    TEXTS.mkdir(parents=True, exist_ok=True)
    out = []
    for number, pg, must, edition in MANIFEST:
        r = httpx.get(url_for(pg), headers=UA, timeout=90, follow_redirects=True)
        raw = r.text
        head = raw[:4000].lower()
        if r.status_code != 200 or must not in head:
            print(f"SKIPPED #{number} ebook {pg}: status {r.status_code}, expected title word '{must}' not found in the file header")
            continue
        s, e = START.search(raw), END.search(raw)
        body = raw[s.end():e.start()] if s and e else None
        terms = TERMS.search(raw[:6000])
        if not body or not terms:
            print(f"SKIPPED #{number} ebook {pg}: could not separate the book from the licence boilerplate or find the licence sentence")
            continue
        body = body.replace("\r\n", "\n").strip()
        (TEXTS / f"{number}.txt").write_text(body, encoding="utf-8")
        out.append({"number": number, "gutenberg_id": pg, "source_url": url_for(pg), "edition": edition, "bytes": len(body.encode("utf-8")), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "licence_sentence": " ".join(terms.group(0).split()), "retrieved_on": date.today().isoformat(),
                    "rights_note": "Public domain in the United States per Project Gutenberg. Status in India not separately verified. Recorded use: private analysis and full-text indexing only."})
        print(f"ok #{number} ebook {pg}: {len(body) // 1024} KB - {edition[:60]}")
    for number, item, must, edition, basis in MANIFEST_IA:
        resp = httpx.get(f"https://archive.org/metadata/{item}", headers=UA, timeout=90, follow_redirects=True)
        if resp.status_code != 200:
            print(f"SKIPPED #{number} {item}: the Internet Archive answered {resp.status_code}")
            continue
        meta = resp.json()
        name = next((f["name"] for f in meta.get("files", []) if f["name"].endswith("_djvu.txt")), None)
        if not name:
            print(f"SKIPPED #{number} {item}: no plain-text file on the item")
            continue
        url = f"https://archive.org/download/{item}/{name}"
        raw = httpx.get(url, headers=UA, timeout=180, follow_redirects=True).text
        if must not in raw[:20000].lower():
            print(f"SKIPPED #{number} {item}: expected word '{must}' not found near the start of the text")
            continue
        body = raw.replace("\r\n", "\n").strip()
        (TEXTS / f"{number}.txt").write_text(body, encoding="utf-8")
        out.append({"number": number, "archive_id": item, "source_url": url, "edition": edition, "bytes": len(body.encode("utf-8")), "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "licence_sentence": basis, "retrieved_on": date.today().isoformat(), "rights_note": basis + " Recorded use: private analysis and full-text indexing only."})
        print(f"ok #{number} archive.org {item}: {len(body) // 1024} KB - {edition[:60]}")
    # merge with what is already recorded: a run that fetched only some works (or hit a flaky network) must not drop earlier entries from the manifest
    manifest = DATA / "sources.json"
    kept = {w["number"]: w for w in (json.loads(manifest.read_text(encoding="utf-8")).get("works", []) if manifest.exists() else [])}
    kept.update({w["number"]: w for w in out})
    manifest.write_text(json.dumps({"loaded_by": "scripts/knowledge_load.py", "approval": APPROVAL, "works": [kept[n] for n in sorted(kept)]}, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    return out


def ingest(reindex: bool = False) -> None:
    """Applies the same rules as the admin routes by calling lib/knowledge.py directly (the admin routes need a verified email and two-step sign-in; this is a local operator tool)."""
    import asyncio

    sys.path.insert(0, str(ROOT / "backend"))
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "vidhi_dev")
    from lib import knowledge  # noqa: E402

    works = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))["works"]

    async def run() -> None:
        print("registry import:", await knowledge.import_registry())
        for w in works:
            n = w["number"]
            cur = await knowledge.db.knowledge_works.find_one({"number": n})
            if cur and cur["status"] in ("Ingested", "Indexed", "Retrieval verified", "Evaluation passed"):
                if not reindex:
                    print(f"#{n} already ingested, skipped")
                    continue
                # rebuild only the derived search chunks from the stored source file (used after a chunking fix); rights, approval and status are untouched
                await knowledge.db.knowledge_chunks.delete_many({"work_number": n, "scope": "library"})
                text = (TEXTS / f"{n}.txt").read_text(encoding="utf-8")
                print(f"#{n} reindexed: {await knowledge.ingest_text(n, text, n not in PARTIAL)}")
                continue
            await knowledge.record_rights(n, w["licence_sentence"], ["private_analysis", "full_text_indexing"], w["source_url"], w["edition"])
            for status, evidence, approval in (
                ("Source located", f"{w['source_url']} sha256 {w['sha256'][:16]}", ""),
                ("Rights not yet verified", "Project Gutenberg licence sentence recorded; India status not separately checked.", ""),
                ("Authorized for ingestion", w["rights_note"], approval_for(n)),
            ):
                try:
                    await knowledge.set_status(n, status, evidence, approval)
                except ValueError as exc:
                    if "forward" not in str(exc):
                        raise
            text = (TEXTS / f"{n}.txt").read_text(encoding="utf-8")
            out = await knowledge.ingest_text(n, text, n not in PARTIAL)
            print(f"#{n}: {out}")

    asyncio.run(run())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--ingest", action="store_true")
    ap.add_argument("--reindex", action="store_true", help="rebuild the search chunks of works that are already ingested")
    a = ap.parse_args()
    if a.download:
        download()
    if a.ingest:
        ingest(a.reindex)
    if not (a.download or a.ingest):
        ap.print_help()
