"""Shows, for one Act, how a draft section and its parsed provision differ (a dry run: nothing is stored). python scripts/draft_parse_diff.py bns [max]"""

import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import legal_structure, textmatch  # noqa: E402
from lib.legal_store import SECTION_NUMBER, draft_pages  # noqa: E402

PENDING = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "pending"


def main() -> None:
    name = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    data = json.loads((PENDING / f"{name}.json").read_text(encoding="utf-8"))
    drafts = data["entries"] if isinstance(data, dict) and "entries" in data else [data]
    pages, _ = draft_pages(drafts)
    parsed = legal_structure.parse_provisions(pages)
    by = {}
    for p in parsed["provisions"]:
        by.setdefault(p["number"].upper(), []).append(p)
    shown = 0
    for d in drafts:
        m = SECTION_NUMBER.match(str(d["citation"]))
        if not m:
            continue
        found = by.get(m.group("n").upper())
        body = textmatch.norm(str(d.get("text", "")))
        if found and body in textmatch.norm(found[0]["text_full"]):
            continue
        shown += 1
        print("=" * 80)
        print("DRAFT", d["citation"], "| heading:", d.get("heading"), "| len", len(d.get("text", "")))
        print("  draft  start:", repr(str(d.get("text", ""))[:160]))
        print("  draft  end  :", repr(str(d.get("text", ""))[-160:]))
        if found:
            t = found[0]["text_full"]
            print("  parsed start:", repr(t[:160]))
            print("  parsed end  :", repr(t[-160:]), "| len", len(t), "| copies", len(found))
        else:
            print("  parsed: NONE")
        if shown >= limit:
            break
    print("warnings:", parsed["warnings"][:6])


if __name__ == "__main__":
    main()
