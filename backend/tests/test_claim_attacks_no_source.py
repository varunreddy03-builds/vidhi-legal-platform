"""A legal claim with no retrieved source can never be VERIFIED, whatever the model says about it. Invented text only.

Covers the case the other attack tests do not name: the model states a point of law, says supports=YES, and gives no citation, or cites a source that is not in the verified library."""

import pytest

from lib import verify
from tests.conftest import answer, stub

NOT_VERIFIED = ("UNSUPPORTED", "PARTIALLY_VERIFIED")


def test_the_decision_for_a_legal_claim_without_a_valid_library_quote_is_unsupported():
    status, _ = verify.decide("LEGAL", valid_matter_quote=False, valid_library_quote=False, supports="YES", coverage_complete=True, has_matter=False, conflicts=[], absence=None)
    assert status == "UNSUPPORTED"


def _claims(user, marker, claims):
    stub("research", answer("Reply.", claims), contains=marker)
    r = user.post("/research", json={"question": f"Is there a rule about borrowed widgets? {marker}", "mode": "STANDARD"})
    assert r.status_code == 200, r.text
    return r.json()["claims"]


def test_a_legal_claim_with_no_citation_is_shown_unsupported(user_a):
    claims = _claims(user_a, "nosrc-1", [{"text": "A borrower must return a widget within thirty days.", "claim_kind": "LEGAL", "supports": "YES", "citations": [], "conflicts": []}])
    assert claims and all(c["verification_status"] in NOT_VERIFIED for c in claims)
    assert claims[0]["verification_status"] == "UNSUPPORTED"


@pytest.mark.parametrize("ref", ["not-in-the-library", "test-widget-1-but-wrong", ""])
def test_a_legal_claim_citing_a_source_that_is_not_verified_is_never_verified(user_a, ref):
    cit = [{"source": "LIBRARY", "ref": ref, "quote": "A person who borrows a widget shall return the widget to the lender within thirty days."}]
    claims = _claims(user_a, f"nosrc-2-{abs(hash(ref)) % 1000}", [{"text": "A borrower must return a widget within thirty days.", "claim_kind": "LEGAL", "supports": "YES", "citations": cit, "conflicts": []}])
    assert claims and all(c["verification_status"] in NOT_VERIFIED for c in claims)
    assert all(not ci.get("quote_verified") for c in claims for ci in c["citations"])
