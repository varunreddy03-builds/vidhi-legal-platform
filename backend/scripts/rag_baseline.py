"""Retrieval baseline: how often the right source is among the first 1, 3, 5 or 10 results. No AI is called and nothing is written to the database.

  python scripts/rag_baseline.py --build     writes backend/evals/retrieval_set.json from the database (needs the law and judgments loaded: vidhi_dev)
  python scripts/rag_baseline.py --run       reads the fixture, runs the retrieval functions the research screen uses, prints recall and the misses, writes a dated report in docs/evals/

The questions: 24 about provisions of the six criminal-law Acts we hold, in plain words (each expected provision is looked up in the data and its heading checked, so nothing is taken from memory), and 16 about
real judgments, picked by a rule fixed beforehand (the first judgment with two named parties for each year 2005 to 2020, newest first) and asked as the parties, court and year. Four of the statute questions come
from docs/research/INDIAN_LEGAL_QUESTION_BANK.md (the only bank rows that touch the Acts we hold); the rest are marked DATA. The question bank's other rows need Acts or judgment text that are not loaded,
so they cannot be tested yet (see the report)."""
import argparse
import asyncio
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "evals" / "retrieval_set.json"
KS = (1, 3, 5, 10)  # 3 is what the research screen shows of whole provisions

# (id, question, source, [(Act, section, a word that must be in the heading)])
STATUTES = [
    ("S01", "What is the punishment for murder?", "DATA", [("IPC", "302", "murder"), ("BNS", "103", "murder")]),
    ("S02", "What is cheating?", "DATA", [("IPC", "415", "cheating"), ("BNS", "318", "cheating")]),
    ("S03", "What is the punishment for criminal breach of trust?", "DATA", [("IPC", "406", "breach of trust"), ("BNS", "316", "breach of trust")]),
    ("S04", "What is dowry death?", "DATA", [("IPC", "304B", "dowry")]),
    ("S05", "Can a husband or his relatives be punished for cruelty to a wife?", "DATA", [("IPC", "498A", "cruelty"), ("BNS", "85", "cruelty")]),
    ("S06", "When is each person liable for an act done by several people with a common intention?", "DATA", [("IPC", "34", "common intention")]),
    ("S07", "Which section lets the High Court direct bail to a person who fears arrest (anticipatory bail)?", "BANK B2", [("CrPC", "438", "bail"), ("BNSS", "482", "bail")]),
    ("S08", "How is information about a cognizable offence recorded by the police?", "DATA", [("CrPC", "154", "cognizable"), ("BNSS", "173", "cognizable")]),
    ("S09", "When can the police arrest without a warrant?", "DATA", [("CrPC", "41", "arrest without warrant"), ("BNSS", "35", "arrest without warrant")]),
    ("S10", "Can a wife, child or parent get an order for maintenance?", "BANK E3", [("CrPC", "125", "maintenance")]),
    ("S11", "Which documents need a certificate when an electronic record is used as evidence?", "BANK J3", [("IEA", "65B", "electronic records"), ("BSA", "63", "electronic records")]),
    ("S12", "Is a confession made to a police officer admissible?", "DATA", [("IEA", "25", "confession to police"), ("BSA", "23", "confession to police")]),
    ("S13", "How much of the information received from an accused person may be proved?", "DATA", [("IEA", "27", "accused")]),
    ("S14", "When may a court presume that certain facts exist?", "DATA", [("IEA", "114", "presume")]),
    ("S15", "What is the punishment for theft?", "DATA", [("IPC", "379", "theft"), ("BNS", "303", "theft")]),
    ("S16", "What is defamation?", "DATA", [("IPC", "499", "defamation")]),
    ("S17", "What is the punishment for robbery?", "DATA", [("IPC", "392", "robbery"), ("BNS", "309", "robbery")]),
    ("S18", "What is attempt to murder?", "DATA", [("IPC", "307", "attempt to murder")]),
    ("S19", "What is the punishment for culpable homicide not amounting to murder?", "DATA", [("IPC", "304", "culpable homicide")]),
    ("S20", "What is forgery for the purpose of cheating?", "DATA", [("IPC", "468", "forgery")]),
    ("S21", "What power does a police officer have to investigate a cognizable case?", "DATA", [("CrPC", "156", "investigate")]),
    ("S22", "How does a Magistrate examine the complainant?", "DATA", [("CrPC", "200", "complainant")]),
    ("S23", "Who has the burden of proof?", "DATA", [("IEA", "101", "burden of proof")]),
    ("S24", "When are the opinions of experts relevant?", "DATA", [("IEA", "45", "experts")]),
]


def _clean_title(title: str) -> str | None:
    t = re.sub(r"^[A-Z0-9().\- ]*?/[0-9]+/[0-9]{4} of ", "", title or "").strip()
    t = re.sub(r"(?i)\s+and\s+ors\.?|\s+and\s+anr\.?|\s+and\s+another", "", t)
    m = re.split(r"\s+[Vv][Ss]\.?\s+", t)
    if len(m) != 2:
        return None
    a, b = (re.sub(r"[^A-Za-z .&'-]", " ", x).strip() for x in m)
    if min(len(re.findall(r"[A-Za-z]{2,}", a)), len(re.findall(r"[A-Za-z]{2,}", b))) < 2:
        return None
    return f"{a.title()} v {b.title()}"


async def build() -> int:
    os.environ.setdefault("DB_NAME", "vidhi_dev")
    from lib import hc_judgments
    from lib.db import db

    inst = {i["short_names"][0]: i["id"] async for i in db.instruments.find({}, {"id": 1, "short_names": 1})}
    questions, problems = [], []
    for qid, text, src, exp in STATUTES:
        expected = []
        for act, num, word in exp:
            p = await db.provisions.find_one({"instrument_id": inst.get(act), "number": num})
            if not p or word not in (p.get("heading") or "").lower().replace("  ", " "):
                problems.append(f"{qid}: {act} {num} does not have '{word}' in its heading ({(p or {}).get('heading')!r})")
                continue
            expected.append({"act": act, "section": num, "provision_id": p["id"], "heading": p["heading"]})
        questions.append({"id": qid, "kind": "statute", "question": text, "source": src, "expected": expected})
    for year in range(2005, 2021):
        items, _ = await hc_judgments.search("", None, 0, 60, year, year)
        for r in items:
            name = _clean_title(r.get("case_title", ""))
            if name:
                questions.append({"id": f"J{year}", "kind": "judgment", "question": f"{name}, {r['court_name']}, {year}", "source": "DATA", "expected": [{"judgment_id": r["id"], "case_title": r["case_title"], "court": r["court_name"], "year": year}]})
                break
        else:
            problems.append(f"no qualifying judgment for {year}")
    if problems:
        print("\n".join(problems))
        return 2
    FIXTURE.write_text(json.dumps({"made": date.today().isoformat(), "database": os.environ["DB_NAME"], "questions": questions}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {len(questions)} questions to {FIXTURE}")
    return 0


def recall(ranks: list[int | None], k: int) -> float:
    """Share of questions whose right source is within the first k results (a miss counts as not found)."""
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks) if ranks else 0.0


def first_rank(returned: list[str], expected: set[str]) -> int | None:
    for i, rid in enumerate(returned, start=1):
        if rid in expected:
            return i
    return None


async def run() -> int:
    os.environ.setdefault("DB_NAME", "vidhi_dev")
    from lib import hc_judgments, legal_search

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = []
    for q in data["questions"]:
        if q["kind"] == "statute":
            res = await legal_search.search(q["question"], limit=10)
            returned = [p["id"] for e in res["exact"] for p in e["provisions"]] + [v["id"] for v in res["text"]]
            expected = {e["provision_id"] for e in q["expected"]}
        else:
            items, _ = await hc_judgments.search(q["question"], None, 0, 10)
            returned = [r["id"] for r in items]
            expected = {e["judgment_id"] for e in q["expected"]}
        rows.append({"id": q["id"], "kind": q["kind"], "question": q["question"], "rank": first_rank(returned, expected), "returned": len(returned)})
    lines = [f"# Retrieval baseline, {date.today().isoformat()}", "", f"Database `{data['database']}`, fixture `evals/retrieval_set.json` ({len(rows)} questions). Retrieval only: no AI call. Recall at k = share of questions whose right source is in the first k results.", ""]
    lines += ["| Kind | Questions | Recall@1 | Recall@3 | Recall@5 | Recall@10 | Nothing returned |", "|---|---|---|---|---|---|---|"]
    for kind in ("statute", "judgment", "all"):
        sel = [r for r in rows if kind == "all" or r["kind"] == kind]
        lines.append(f"| {kind} | {len(sel)} | " + " | ".join(f"{round(100 * recall([r['rank'] for r in sel], k))}%" for k in KS) + f" | {sum(1 for r in sel if r['returned'] == 0)} |")
    lines += ["", "## Misses (not in the first 10)", ""]
    lines += [f"- {r['id']} ({r['kind']}): {r['question']} (returned {r['returned']} results)" for r in rows if r["rank"] is None] or ["none"]
    lines += ["", "## Where the right source ranked", "", "| Id | Rank |", "|---|---|"] + [f"| {r['id']} | {r['rank'] or 'not found'} |" for r in rows]
    out = ROOT.parent / "docs" / "evals" / f"retrieval-baseline-{date.today().isoformat()}.md"
    n = 2
    while out.exists():
        out = out.with_name(f"retrieval-baseline-{date.today().isoformat()}-{n}.md")
        n += 1
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8]))
    print("saved", out)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.build:
        raise SystemExit(asyncio.run(build()))
    if a.run:
        raise SystemExit(asyncio.run(run()))
    print(__doc__)
