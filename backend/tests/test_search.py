"""The search box finds money recoveries and their papers too, and only the caller's own."""

import uuid

from tests.conftest import new_matter
from tests.test_recovery_stage1 import new_case


def groups(c, q):
    return {g["type"]: g["items"] for g in c.get("/search", params={"q": q}).json()["groups"]}


def test_search_finds_recoveries_by_name_invoice_and_paper_and_never_across_organisations(user_a, user_b):
    tag = uuid.uuid4().hex[:8]
    cid, debtor = new_case(user_a, debtor=f"Zenith{tag} Traders")
    user_a.patch(f"/recovery/cases/{cid}/intake", json={"invoice_number": f"INV-{tag}"})
    user_a.post(f"/recovery/cases/{cid}/proofs", files={"file": (f"challan-{tag}.txt", b"delivered")}, data={"kind": "DELIVERY_PROOF"})
    mid, title = new_matter(user_a, f"Matter{tag}")

    assert groups(user_a, f"Zenith{tag}")["Money recoveries"][0]["href"] == f"/recovery/cases/{cid}"
    assert groups(user_a, f"INV-{tag}")["Money recoveries"][0]["id"] == cid
    assert groups(user_a, f"challan-{tag}")["Papers in recoveries"][0]["href"] == f"/recovery/cases/{cid}"
    assert "Matters" in groups(user_a, f"Matter{tag}")
    assert user_b.get("/search", params={"q": f"Zenith{tag}"}).json()["groups"] == []
    assert user_a.get("/search", params={"q": "a"}).json()["groups"] == []  # too short to search