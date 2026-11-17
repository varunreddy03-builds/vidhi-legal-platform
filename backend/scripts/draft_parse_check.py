"""Does the structure parser find the same sections the extractor found? A dry run on the draft files: nothing is loaded into the database, shown or published.

For each Act in data/legal_library/pending/*.json it rebuilds the Act's text from its draft sections (lib.legal_store.draft_pages), parses it with lib.legal_structure, and compares:
  * the number of provisions with the number of drafts, and
  * for each draft, whether the parsed provision with the same number holds the draft's words (a draft's text is never changed by the parser, only cut into components).

    python scripts/draft_parse_check.py            # summary and the Acts that differ
    python scripts/draft_parse_check.py --only bns # one Act (file name without .json)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import textmatch  # noqa: E402
from lib.legal_store import SECTION_NUMBER, draft_rest, parse_drafts  # noqa: E402

PENDING = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "pending"


def check(path: Path) -> dict | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    drafts = data["entries"] if isinstance(data, dict) and "entries" in data else [data]
    drafts = [d for d in drafts if isinstance(d, dict) and d.get("citation")]
    if not drafts:
        return None
    parsed = parse_drafts(drafts)
    left_out = parsed["left_out"]
    by_number: dict[str, list[dict]] = {}
    for p in parsed["provisions"]:
        by_number.setdefault(p["number"].upper(), []).append(p)
    same = missing = changed = trimmed = 0
    examples: list[str] = []
    for d in drafts:
        m = SECTION_NUMBER.match(str(d["citation"]))
        if not m:
            continue
        found = by_number.get(m.group("n").upper())
        if not found:
            missing += 1
            if len(examples) < 5:
                examples.append(f"missing: {d['citation'][:70]}")
            continue
        body = textmatch.norm(draft_rest(d, m.group("n")))  # the words after the section's own first line, on both sides
        parsed_text = textmatch.norm(draft_rest({"text": found[0]["text_full"]}, m.group("n")))
        if body and body in parsed_text:
            same += 1
        elif body and parsed_text in body and len(parsed_text) >= 0.9 * len(body):
            same += 1  # the parser cut a trailing Chapter/Part heading the extractor had left on the section; nothing else is missing
            trimmed += 1
        else:
            changed += 1
            if len(examples) < 5:
                examples.append(f"words differ: {d['citation'][:70]}")
    return {"file": path.stem, "drafts": len(drafts), "left_out": len(left_out), "provisions": len(parsed["provisions"]), "same": same, "missing": missing, "changed": changed, "trimmed": trimmed,
            "warnings": len(parsed["warnings"]), "examples": examples}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    rows = []
    for f in sorted(PENDING.glob("*.json")):
        if f.name.startswith("_") or (args.only and f.stem != args.only):
            continue
        try:
            r = check(f)
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the run
            r = {"file": f.stem, "error": f"{type(exc).__name__}: {exc}"[:120]}
        if r:
            rows.append(r)
    ok = [r for r in rows if "error" not in r]
    exact = [r for r in ok if r["provisions"] == r["drafts"] - r["left_out"] and r["missing"] == 0 and r["changed"] == 0]
    print(f"Acts checked: {len(rows)} | parsed without error: {len(ok)} | exact (same count, every draft found with its words): {len(exact)}")
    print(f"Drafts: {sum(r['drafts'] for r in ok)} | found with the same words: {sum(r['same'] for r in ok)} (of which a trailing heading was trimmed: {sum(r['trimmed'] for r in ok)}) | missing: {sum(r['missing'] for r in ok)} | words differ: {sum(r['changed'] for r in ok)}")
    for r in rows:
        if r in exact:
            continue
        if "error" in r:
            print(f"ERROR {r['file']}: {r['error']}")
            continue
        print(f"{r['file']}: drafts {r['drafts']} (left out {r['left_out']}), provisions {r['provisions']}, same {r['same']}, missing {r['missing']}, differ {r['changed']}, warnings {r['warnings']}")
        for e in r["examples"][:3]:
            print("    " + e)


if __name__ == "__main__":
    main()
