"""Second-source comparison: the same Act loaded from two different official sources, section by section.

Where two official sources word a section differently (or one is missing it), the loaded provision is FLAGGED for the reviewer. Nothing is decided here: a difference may be a
typing error in either source, an amendment applied by one and not the other, or only layout. The comparison ignores case, quote marks and spacing (lib/textmatch.norm) and nothing else, so a
changed word or figure is a difference.

Statuses per section number: SAME, DIFFERENT, ONLY_IN_LOADED (the second source has no such section), ONLY_IN_SECOND (the loaded text has none)."""

import difflib
from datetime import date

from lib import legal_structure, textmatch
from lib import verified_store as store
from lib.db import db

SAME, DIFFERENT, ONLY_IN_LOADED, ONLY_IN_SECOND = "SAME", "DIFFERENT", "ONLY_IN_LOADED", "ONLY_IN_SECOND"
MAX_DIFFS = 5
CONTEXT_WORDS = 5


def _words(text: str) -> list[str]:
    return textmatch.norm(text).split(" ")


def differences(a: str, b: str) -> list[dict]:
    """Where the two wordings part: up to MAX_DIFFS spans, each with the words from the loaded text, the words from the second source, and a little context."""
    wa, wb = _words(a), _words(b)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append({"loaded": " ".join(wa[i1:i2]), "second": " ".join(wb[j1:j2]), "before": " ".join(wa[max(0, i1 - CONTEXT_WORDS):i1])})
        if len(out) >= MAX_DIFFS:
            break
    return out


def compare_sections(loaded: dict[str, str], second: dict[str, str]) -> dict[str, dict]:
    """loaded / second: {section number (upper case): text}. Returns {number: {status, similarity, differences}}."""
    result = {}
    for num in sorted(set(loaded) | set(second), key=lambda n: (len(n), n)):
        if num not in second:
            result[num] = {"status": ONLY_IN_LOADED, "similarity": 0.0, "differences": []}
        elif num not in loaded:
            result[num] = {"status": ONLY_IN_SECOND, "similarity": 0.0, "differences": []}
        elif textmatch.norm(loaded[num]) == textmatch.norm(second[num]):
            result[num] = {"status": SAME, "similarity": 1.0, "differences": []}
        else:
            ratio = difflib.SequenceMatcher(None, _words(loaded[num]), _words(second[num]), autojunk=False).ratio()
            result[num] = {"status": DIFFERENT, "similarity": round(ratio, 3), "differences": differences(loaded[num], second[num])}
    return result


async def compare_version(version_id: str, second_document_id: str, checked_by: str) -> dict:
    """Compare a loaded version with a second registered document and flag each provision. The second document must come from a DIFFERENT source, or it is not a second opinion."""
    version = await db.instrument_versions.find_one({"id": version_id})
    if not version:
        raise ValueError("Unknown version.")
    first = await db.legal_documents.find_one({"id": version["document_id"]}, {"pages": 0})
    second = await db.legal_documents.find_one({"id": second_document_id})
    if not second:
        raise ValueError("Unknown second document.")
    if second["source_id"] == first["source_id"] or second["sha256"] == first["sha256"]:
        raise ValueError("The second document must come from a different source (and be a different file) than the one the text was loaded from.")
    parsed = legal_structure.parse_provisions(second["pages"])
    second_text = {p["number"].upper(): p["text_full"] for p in parsed["provisions"]}
    rows = await db.provisions.find({"instrument_version_id": version_id}).to_list(20000)
    loaded_text = {p["number_norm"]: p["text_full"] for p in rows}
    result = compare_sections(loaded_text, second_text)
    today = date.today().isoformat()
    for p in rows:
        r = result[p["number_norm"]]
        flag = {"document_id": second_document_id, "source_id": second["source_id"], "status": r["status"], "similarity": r["similarity"], "differences": r["differences"], "checked_on": today, "checked_by": checked_by}
        await store.change(db, "provisions", {"id": p["id"]}, {"second_source": flag})
    counts = {s: sum(1 for r in result.values() if r["status"] == s) for s in (SAME, DIFFERENT, ONLY_IN_LOADED, ONLY_IN_SECOND)}
    return {"version_id": version_id, "second_document_id": second_document_id, "counts": counts, "parser_warnings_second": parsed["warnings"],
            "different": [n for n, r in result.items() if r["status"] == DIFFERENT], "only_in_second": [n for n, r in result.items() if r["status"] == ONLY_IN_SECOND]}
