"""3,000 generated Legal Intelligence cases judged by the independent auditor (evals/auditor.py), not by expectations written alongside the cases.
See evals/stress.py for what is generated and evals/auditor.py for the rules the app's every output is checked against."""

import os

import pytest

from evals import auditor
from evals.stress import all_cases
from tests.conftest import new_matter, stub, upload

CASES = all_cases()[: int(os.environ.get("STRESS_LIMIT", "3000"))]  # STRESS_LIMIT=150 runs a quick slice (used by scripts/mutation_check.py)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_stress_case(user_a, case):
    mid, title = new_matter(user_a, "Stress")
    for i, text in enumerate(case["documents"], start=1):
        upload(user_a, mid, f"doc{i}.txt", text)
    stub("research", {**case["gold"]}, contains=title)
    r = user_a.post("/research", json={"question": f"{case['question']} {title}", "matter_id": mid, "mode": "MATTER", "language": case["language"]})
    assert r.status_code == 200, r.text
    problems = auditor.audit(case, r.json(), records=[title])
    assert not problems, problems
