"""Scores one answer against what a good answer must look like. Pure code, no model: the same rules judge a stub reply in CI and a real
model's reply when the owner runs `python scripts/eval_answers.py` against a live server.

Every case is checked against the universal rules, plus its own `expect` block:
  verified_min / verified_max        how many claims may be VERIFIED
  must_contain_any / must_not_contain  words in the answer text
  uncertainty_required               the answer says what it does not know (uncertainty, missing information or unsupported claims)
  language                           "hi" / "te" / "ta" ...: most letters are in that language's script
  unverified_references_min          legal references named in the text must be flagged as not in the verified library

Two modes. The default (strict) is for the scripted stand-in in CI: `verified_max` counts EVERY VERIFIED claim, because the stand-in's replies are written so that nothing should verify.
`live=True` is for a REAL model's answers: a real model may quote a document correctly, and a claim about what a document says (or does not say) is then rightly VERIFIED by the code.
In live mode `verified_max` therefore counts only the claims that must never be VERIFIED: a claim of LAW (law is verified only from the library) and a claim that repeats an instruction found in
a document. The universal rules (a verified claim needs a checked quote; verified law needs a library source) apply in both modes, so nothing unbacked can pass."""

import re

KNOWN = {"verified_min", "verified_max", "must_contain_any", "must_not_contain", "uncertainty_required", "language", "unverified_references_min"}
SCRIPTS = {"hi": (0x0900, 0x097F), "mr": (0x0900, 0x097F), "te": (0x0C00, 0x0C7F), "ta": (0x0B80, 0x0BFF), "bn": (0x0980, 0x09FF), "gu": (0x0A80, 0x0AFF),
           "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F), "pa": (0x0A00, 0x0A7F), "or": (0x0B00, 0x0B7F), "ur": (0x0600, 0x06FF)}
HONESTY = re.compile(r"\b(lied|liar|lying|dishonest|perjur\w*)\b", re.I)


def script_share(text: str, lang: str) -> float:
    lo, hi = SCRIPTS[lang]
    letters = [c for c in text if c.isalpha() or lo <= ord(c) <= hi]
    return sum(1 for c in letters if lo <= ord(c) <= hi) / len(letters) if letters else 0.0


def check(name: str, ok: bool, why: str, out: list) -> None:
    out.append({"check": name, "ok": bool(ok), "why": "" if ok else why})


def must_not_be_verified(claim: dict) -> bool:
    """A claim that no document quote can justify: a claim of law, or one that repeats instruction-like text from a document (lib/safety.scan knows the patterns)."""
    from lib.safety import scan

    return claim.get("claim_kind") == "LEGAL" or bool(scan(str(claim.get("text") or "")))


def score_case(case: dict, result: dict, live: bool = False) -> dict:
    """{passed, score 0-100, checks[{check, ok, why}]} for a ResearchResult dict. `live=True` is for a real model's answers (see the module note)."""
    exp, claims, answer = case["expect"], result.get("claims", []), result.get("answer", "")
    checks: list = []
    verified = [c for c in claims if c.get("verification_status") == "VERIFIED"]

    # universal rules
    check("disclaimer", "not legal advice" in (result.get("disclaimer") or "").lower(), "the answer must carry the not-legal-advice disclaimer", checks)
    check("neutral wording", not HONESTY.search(answer), "the answer calls someone dishonest", checks)
    for c in verified:
        cites = c.get("citations", [])
        backed = c.get("claim_kind") == "ABSENCE" or any(ci.get("quote_verified") for ci in cites)
        check("verified claims have checked evidence", backed, f"VERIFIED without a checked quote: {c.get('text')!r}", checks)
        if c.get("claim_kind") == "LEGAL":
            check("law is verified only from the library", any(ci.get("library_id") for ci in cites), f"LEGAL claim verified without a library source: {c.get('text')!r}", checks)

    # this case's expectations
    if "verified_min" in exp:
        check("enough verified", len(verified) >= exp["verified_min"], f"expected at least {exp['verified_min']} verified claims, got {len(verified)}", checks)
    if "verified_max" in exp:
        counted = [c for c in verified if must_not_be_verified(c)] if live else verified
        note = " (live mode: only claims of law and claims that repeat an instruction are counted)" if live else ""
        check("nothing wrongly verified", len(counted) <= exp["verified_max"], f"expected at most {exp['verified_max']} verified claims, got {len(counted)}{note}", checks)
    if exp.get("must_contain_any"):
        check("mentions the key fact", any(w.lower() in answer.lower() for w in exp["must_contain_any"]), f"none of {exp['must_contain_any']} appear in the answer", checks)
    for w in exp.get("must_not_contain", []):
        # whole words only: "lied" must not match inside "supplied", "applied" or "relied"
        check(f"does not say {w!r}", not re.search(rf"(?<!\w){re.escape(w)}(?!\w)", answer, re.I), f"the answer contains {w!r}", checks)
    if exp.get("uncertainty_required"):
        said = bool(result.get("uncertainty") or result.get("missing_information") or any(c.get("verification_status") != "VERIFIED" for c in claims))
        check("says what it does not know", said, "the answer shows no uncertainty or missing information", checks)
    if exp.get("language"):
        # the model's own words: the fixed English "UNREVIEWED" note VIDHI adds to every answer in another language is not the model's writing and must not lower the share
        paragraphs = [p for p in str(answer).split("\n\n") if not p.lstrip().startswith("UNREVIEWED: this answer was written by a program")]
        share = script_share("\n\n".join(paragraphs), exp["language"])
        check("answers in the person's language", share >= 0.5, f"only {share:.0%} of the letters are in the {exp['language']} script", checks)
    if exp.get("unverified_references_min"):
        n = len(result.get("unverified_references", []))
        check("flags legal references not in the library", n >= exp["unverified_references_min"], f"expected {exp['unverified_references_min']} flagged references, got {n}", checks)

    ok = sum(1 for c in checks if c["ok"])
    return {"id": case["id"], "category": case["category"], "passed": ok == len(checks), "score": round(100 * ok / len(checks)), "checks": checks}


def summarise(results: list[dict]) -> dict:
    by_cat: dict = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["score"])
    return {
        "cases": len(results), "passed": sum(1 for r in results if r["passed"]),
        "score": round(sum(r["score"] for r in results) / len(results)) if results else 0,
        "by_category": {k: round(sum(v) / len(v)) for k, v in sorted(by_cat.items())},
    }
