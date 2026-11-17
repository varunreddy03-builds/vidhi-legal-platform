"""Embeddings pilot, step A: what today's keyword retrieval returns for the 24 statute questions (and the Hindi and Telugu versions of eight of them), saved so the pilot (step B, a
separate Python environment) can compare against it.

  python scripts/embed_pilot_lexical.py [--out C:\\vidhi-tools\\embed-pilot\\lexical.json]

Runs the same function the baseline uses (`legal_search.search`, no AI, nothing written to the database). The question in another language is sent as it is: the app's translate-for-search
step needs an AI call and is not part of this measurement. Needs the app's own Python environment and the dev database (vidhi_dev)."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DB_NAME", "vidhi_dev")

FIXTURE = ROOT / "evals" / "retrieval_set.json"
EXTRA = ROOT / "evals" / "embed_pilot_queries.json"


async def main(out: Path) -> int:
    from lib import legal_search

    async def ids(text: str) -> list[str]:
        res = await legal_search.search(text, limit=10)
        return [p["id"] for e in res["exact"] for p in e["provisions"]] + [v["id"] for v in res["text"]]

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ranked: dict[str, list[str]] = {}
    for q in data["questions"]:
        if q["kind"] == "statute":
            ranked[q["id"]] = await ids(q["question"])
    for q in json.loads(EXTRA.read_text(encoding="utf-8"))["queries"]:
        ranked[f"{q['qid']}-{q['lang']}"] = await ids(q["text"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ranked, indent=1), encoding="utf-8")
    print(f"wrote {out}: {len(ranked)} questions, {sum(1 for v in ranked.values() if v)} with at least one result")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"C:\vidhi-tools\embed-pilot\lexical.json")
    raise SystemExit(asyncio.run(main(Path(ap.parse_args().out))))
