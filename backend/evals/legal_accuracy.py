"""The legal-accuracy evaluation set (evals/legal_accuracy_set.json): QUESTIONS ONLY until a qualified person fills in a reference answer from official text.

Nothing here states what any law says. Each entry has a question, a category, the BEHAVIOUR a good answer must show (checkable by code), and an empty `reference` block that a
reviewing lawyer fills in (the reference answer, the official sources it rests on, their name and the date). `accuracy_report` refuses to produce a score for any entry whose
reference is missing or unreviewed, and says "NOT MEASURABLE" when there are none, so no one can quote a legal-accuracy figure that was never measured."""

import json
from pathlib import Path

PATH = Path(__file__).with_name("legal_accuracy_set.json")
CATEGORIES = [
    "basic_interpretation", "multi_provision", "historical_law", "amendment_commencement", "conflicting_judgments", "binding_vs_persuasive", "telangana_specific",
    "msme_delayed_payment", "incomplete_facts", "unsettled_law", "no_reliable_source", "false_assumption", "nonexistent_citation",
]
BEHAVIOURS = {
    "answer_from_sources": "answer only from retrieved, cited source text; unsupported points flagged",
    "state_date_and_version": "name which version of the text applies on which date, or say the dates are not available",
    "ask_for_facts": "say which facts are missing instead of guessing",
    "present_both_views": "set out each view with its source and say it is not settled",
    "say_insufficient": "say plainly that no reliable source was found; no citation invented",
    "reject_false_premise": "point out that the premise is unsupported or wrong rather than accepting it",
    "refuse_nonexistent_citation": "say the citation could not be found; no text or summary invented",
    "state_authority_level": "say whether each authority is binding, persuasive or unverified, and why",
}


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def is_reviewed(entry: dict) -> bool:
    r = entry.get("reference") or {}
    return bool((r.get("answer") or "").strip() and r.get("sources") and (r.get("reviewer") or "").strip() and r.get("reviewed_on"))


def accuracy_report(scores: dict[str, float]) -> dict:
    """scores: {entry id: 0-100 from a reviewer or from a rubric applied against the reference}. Only entries with a reviewed reference count."""
    entries = {e["id"]: e for e in load()["entries"]}
    counted = {k: v for k, v in scores.items() if k in entries and is_reviewed(entries[k])}
    if not counted:
        return {"status": "NOT MEASURABLE", "why": "No entry has a reviewed reference answer, so no legal-accuracy figure can be given.", "entries": len(entries), "reviewed": 0}
    return {"status": "MEASURED", "reviewed": len(counted), "entries": len(entries), "average": round(sum(counted.values()) / len(counted), 1),
            "note": "Covers only the reviewed entries; the rest are untested."}
