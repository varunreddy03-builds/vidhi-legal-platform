"""The 15-phase Legal Intelligence campaign (1,500 cases) plus 100 "not solved yet" cases: see evals/campaign.py for what each phase tests.

Each case runs through the real /research pipeline with a scripted model reply and is scored by evals/scoring.py, which also applies the universal rules (disclaimer, neutral wording,
every VERIFIED claim backed by a checked quote). The case's `expect` block says how many claims may be VERIFIED, so a pass means every claim got the right verdict."""

import pytest

from evals import scoring
from evals.campaign import all_cases
from tests.conftest import new_matter, stub, upload

CASES = all_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_campaign_case(user_a, case):
    mid, title = new_matter(user_a, "Campaign")
    for i, text in enumerate(case["documents"], start=1):
        upload(user_a, mid, f"doc{i}.txt", text)
    stub("research", {**case["gold"]}, contains=title)
    r = user_a.post("/research", json={"question": f"{case['question']} {title}", "matter_id": mid, "mode": "MATTER", "language": case["language"]})
    assert r.status_code == 200, r.text
    result = scoring.score_case({"id": case["id"], "category": case["tier"], "expect": case["expect"]}, r.json())
    assert result["passed"], [c for c in result["checks"] if not c["ok"]]
