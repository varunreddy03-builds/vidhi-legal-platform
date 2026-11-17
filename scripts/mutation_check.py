"""A hand-picked mutation check: break the application in a specific, realistic way, run a focused set of tests, and record whether they notice.

    python scripts/mutation_check.py [--only N] [--fast]

For each mutant: one exact piece of code is replaced, the focused tests run against a fresh server, and the file is restored (also from git if anything goes wrong).
A mutant is KILLED when at least one test fails, SURVIVED when everything still passes (a weakness in the tests, or the code is genuinely unused).
This is not a complete mutation test (a tool would try thousands of changes); it checks the rules that matter most. Results are written to docs/mutation_results.json."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
B = ROOT / "backend"

TESTS = ["tests/test_audit_findings.py", "tests/test_recovery_cases.py", "tests/test_notice_amounts.py", "tests/test_truth_engine.py", "tests/test_recovery_stage1.py",
         "tests/test_recovery_stage2.py", "tests/test_tenancy.py", "tests/test_stress_intel.py", "tests/test_polarity.py", "tests/test_authority_level.py", "tests/test_authority_wiring.py"]

# (id, file, exact old text, new text, what a correct test suite must notice)
MUTANTS = [
    ("M01", "lib/textmatch.py", "if after and wordchar(needle[-1]) and wordchar(after):", "if False:", "a quote may end inside a longer number or word"),
    ("M02", "lib/textmatch.py", "if len(q) < MIN_QUOTE or substance(q) < MIN_SUBSTANCE:", "if len(q) < 1:", "very short or empty quotes prove something"),
    ("M03", "lib/textmatch.py", "return len(wanted & near) / len(wanted) > 0.5", "return True", "any quote supports any claim"),
    ("M04", "lib/textmatch.py", "if not numbers(claim_text) <= page_numbers:", "if False:", "a claim's figures need not be on the page"),
    ("M05", "lib/verify.py", "        if not all_citations_valid:\n            gaps.append", "        if False:\n            gaps.append", "an invented citation beside a real one is ignored"),
    ("M06", "lib/verify.py", "        if negative_claim:", "        if False:", "a 'there is no X' claim can be verified by a quote"),
    ("M07", "lib/verify.py", '        if absence.get("unlinked"):', "        if False:", "absence search terms need not appear in the claim"),
    ("M08", "lib/verify.py", '        if absence.get("short_terms"):', "        if False:", "terms too short to search are silently dropped"),
    ("M09", "lib/verify.py", "        if unread:\n            gaps.append(\"these documents were not read (no text): \" + \", \".join(unread))\n        if conflicts:", "        if conflicts:", "unread documents do not stop verification"),
    ("M10", "lib/neutral.py", "or any(w in p for w in _OTHER)", "or False", "accusations in Indian languages pass"),
    ("M11", "lib/neutral.py", 'return unicodedata.normalize("NFKC", INVISIBLE.sub("", sentence))', "return sentence", "hidden characters hide an accusation"),
    ("M12", "lib/notice_checks.py", "figures = bool(expected_balance is not None and current_balance is not None and abs(float(expected_balance) - float(current_balance)) > 0.004)", "figures = False", "a notice can go out after the money changed"),
    ("M13", "lib/notice_checks.py", "changed = bool(statement and _STATEMENT_HEAD in t and statement not in t)", "changed = False", "the statement of account can be edited by hand"),
    ("M14", "lib/balance.py", 'if not str(c.get("basis") or "").strip():', 'if False:', "a charge with no written basis is counted"),
    ("M15", "routers/recovery.py", "if d.year < MIN_PAYMENT_YEAR or d > today:", "if False:", "a payment can be dated in the future or before 1990"),
    ("M16", "routers/recovery.py", '{"id": case_id, "organization_id": user["organization_id"]}\n    )\n    if not doc:', '{"id": case_id}\n    )\n    if not doc:', "another business can read a recovery case"),
    ("M17", "routers/recovery_notice.py", 'if state in ("SENT", "ESCALATED", "RESPONSE_RECEIVED"):', "if False:", "a sent notice can be approved and sent again"),
    ("M18", "lib/route_checks.py", 'elif route.get("existing_proceedings") == "unsure":', "elif False:", "'unsure' about an existing case is treated as no problem"),
    ("M19", "routers/research.py", "claim_backed = textmatch.supports(c[\"text\"], passages) if passages else True", "claim_backed = True", "research ignores whether the quote backs the claim"),
    ("M20", "lib/delivery.py", 'return "delivered" in words and not any(w in _NOT_RECEIPT or w.endswith("n\'t") for w in words)', 'return "delivered" in words', "'yet to be delivered' counts as receipt"),
    ("M21", "routers/research.py", 'polarity = textmatch.polarity_differs(c["text"], passages) if passages and kind == "LEGAL" else False', "polarity = False", "research ignores a claim that says the opposite of its quote"),
    ("M22", "lib/textmatch.py", "negation = bool(_NEGATION.search(claim)) != bool(_NEGATION.search(quoted))", "negation = False", "the opposite-polarity check never finds a reversed rule"),
    ("M23", "lib/library.py", 'return "UNKNOWN", CASE_NOTE', 'return "PRIMARY", ""', "a case is labelled primary law again"),
    ("M24", "routers/research.py", "authority_level=level,  # type: ignore[arg-type]", 'authority_level="PRIMARY",', "the research route labels every library entry primary again"),
    ("M25", "lib/textmatch.py", r"|cannot|prohibit\w*|forbid\w*)\b|n't\b", r"|cannot)\b|n't\b", "'prohibited' no longer counts as reversing a rule"),
    ("M26", "lib/textmatch.py", "exception = bool(_EXCEPTION.search(claim)) != bool(_EXCEPTION.search(quoted))", "exception = False", "a missing 'unless' exception is no longer noticed"),
]


def run_tests(fast: bool) -> tuple[bool, str]:
    env = dict(os.environ, STRESS_LIMIT="150" if fast else "300")
    cmd = ["powershell", "-NoProfile", "-File", str(ROOT / "scripts" / "test-backend.ps1"), *TESTS, "-x", "-q"]
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=1500)
    tail = (p.stdout or "").strip().splitlines()[-1:] or [""]
    return p.returncode == 0, tail[0]


def main() -> None:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    fast = "--fast" in sys.argv
    results = []
    for mid, rel, old, new, meaning in MUTANTS:
        if only and mid != only:
            continue
        path = B / rel
        original = path.read_text(encoding="utf-8")
        nl = "\r\n" if "\r\n" in original else "\n"
        o, n = old.replace("\n", nl), new.replace("\n", nl)
        if original.count(o) != 1:
            results.append({"id": mid, "file": rel, "meaning": meaning, "result": "NOT APPLIED", "note": f"found {original.count(o)} matches"})
            print(mid, "NOT APPLIED", flush=True)
            continue
        t0 = time.time()
        try:
            path.write_text(original.replace(o, n), encoding="utf-8", newline="")
            passed, tail = run_tests(fast)
        finally:
            path.write_text(original, encoding="utf-8", newline="")
            subprocess.run(["git", "-c", "safe.directory=*", "diff", "--quiet", "--", str(path)], cwd=ROOT)
        results.append({"id": mid, "file": rel, "meaning": meaning, "result": "SURVIVED" if passed else "KILLED", "seconds": round(time.time() - t0), "last_line": tail})
        print(mid, results[-1]["result"], meaning, flush=True)
    killed = sum(1 for r in results if r["result"] == "KILLED")
    if only:  # a partial run must not replace the record of the full one
        print(f"{killed} of {len(results)} killed; partial run, results file left as it was")
        return
    out = ROOT / "docs" / "mutation_results.json"
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"{killed} of {len(results)} killed; results in {out}")


if __name__ == "__main__":
    main()
