"""Firm-to-firm isolation: organization B must never read, change or delete organization A's data
by guessing/knowing an ID. These tests must stay green through every later phase."""

import pytest

NOT_FOUND = (404,)


@pytest.fixture
def seeded(user_a):
    """Create one of each tenant-owned object in org A and return their ids."""
    a = user_a
    matter = a.post("/matters", json={"title": "A v. B", "description": "secret-A"}).json()
    mid = matter["id"]
    doc = a.post(
        f"/matters/{mid}/documents",
        files={"file": ("note.txt", b"confidential note about the matter", "text/plain")},
    )
    assert doc.status_code == 200, doc.text
    fact = a.post(f"/matters/{mid}/facts", json={"value": "A fact"}).json()
    event = a.post(
        f"/matters/{mid}/timeline", json={"event_date": "2026-01-02", "description": "Something happened"}
    ).json()
    draft = a.post("/drafts", json={"title": "A draft", "body": "secret body", "matter_id": mid}).json()
    case = a.post(
        "/recovery/cases", json={"creditor_name": "A Traders", "debtor_name": "Debtor X", "amount": 1000}
    ).json()
    proof = a.post(
        f"/recovery/cases/{case['id']}/proofs",
        files={"file": ("p.txt", b"invoice 1000 due 1 Jan", "text/plain")},
    )
    assert proof.status_code == 200, proof.text
    return {
        "matter": mid,
        "doc": doc.json()["id"],
        "fact": fact["id"],
        "event": event["id"],
        "draft": draft["id"],
        "case": case["id"],
    }


def test_other_org_cannot_read_by_id(seeded, user_b):
    b, s = user_b, seeded
    for path in (
        f"/matters/{s['matter']}",
        f"/matters/{s['matter']}/documents",
        f"/matters/{s['matter']}/facts",
        f"/matters/{s['matter']}/timeline",
        f"/matters/{s['matter']}/graph",
        f"/documents/{s['doc']}",
        f"/drafts/{s['draft']}",
        f"/recovery/cases/{s['case']}",
        f"/recovery/cases/{s['case']}/proofs",
        f"/recovery/cases/{s['case']}/statement.pdf",
        f"/recovery/cases/{s['case']}/statement-preview",
        f"/recovery/cases/{s['case']}/nudge-preview",
    ):
        r = b.get(path)
        assert r.status_code in NOT_FOUND, f"GET {path} -> {r.status_code}: {r.text[:200]}"


def test_other_org_cannot_modify_or_delete(seeded, user_b, user_a):
    b, s = user_b, seeded
    attempts = [
        ("PATCH", f"/matters/{s['matter']}", {"title": "hijacked"}),
        ("DELETE", f"/matters/{s['matter']}", None),
        ("POST", f"/matters/{s['matter']}/facts", {"value": "planted"}),
        ("DELETE", f"/matters/{s['matter']}/facts/{s['fact']}", None),
        ("POST", f"/matters/{s['matter']}/timeline", {"event_date": "2026-01-01", "description": "x"}),
        ("DELETE", f"/matters/{s['matter']}/timeline/{s['event']}", None),
        ("DELETE", f"/documents/{s['doc']}", None),
        ("PATCH", f"/drafts/{s['draft']}", {"body": "overwritten"}),
        ("DELETE", f"/drafts/{s['draft']}", None),
        ("DELETE", f"/recovery/cases/{s['case']}", None),
        ("POST", f"/recovery/cases/{s['case']}/payment", {"amount": 5}),
        ("POST", f"/recovery/cases/{s['case']}/resolve", None),
        ("POST", f"/recovery/cases/{s['case']}/handoff", None),
        ("POST", f"/recovery/cases/{s['case']}/extract", None),
        ("POST", f"/recovery/cases/{s['case']}/notice", None),
        ("PATCH", f"/recovery/cases/{s['case']}/reminders", {"enabled": False}),
        ("PATCH", f"/recovery/cases/{s['case']}/statement-schedule", {"schedule": "OFF"}),
    ]
    for method, path, body in attempts:
        r = b.request(method, path, json=body)
        assert r.status_code in NOT_FOUND, f"{method} {path} -> {r.status_code}: {r.text[:200]}"
    # …and org A's data is untouched.
    assert user_a.get(f"/matters/{s['matter']}").json()["title"] == "A v. B"
    assert user_a.get(f"/drafts/{s['draft']}").json()["body"] == "secret body"
    assert user_a.get(f"/recovery/cases/{s['case']}").status_code == 200


def test_other_org_cannot_upload_into_foreign_container(seeded, user_b):
    b, s = user_b, seeded
    r = b.post(
        f"/matters/{s['matter']}/documents",
        files={"file": ("x.txt", b"planted", "text/plain")},
    )
    assert r.status_code in NOT_FOUND
    r = b.post(
        f"/recovery/cases/{s['case']}/proofs", files={"file": ("x.txt", b"planted", "text/plain")}
    )
    assert r.status_code in NOT_FOUND


def test_lists_and_search_do_not_leak(seeded, user_b):
    b = user_b
    assert b.get("/matters").json() == []
    assert b.get("/drafts").json() == []
    assert b.get("/recovery/cases").json() == []
    assert b.get("/research").json() == []
    assert b.get("/audit").json() == [] or all(
        "A v. B" not in str(e) for e in b.get("/audit").json()
    )
    hits = b.get("/search", params={"q": "confidential"}).json()["groups"]
    assert hits == []
    stats = b.get("/dashboard/stats").json()
    assert stats["matters"] == 0 and stats["documents"] == 0


def test_cross_org_matter_id_in_research_is_rejected(seeded, user_b):
    # Research is entitlement-gated and calls the LLM only after the org check, so a foreign
    # matter id must 404 before any model call is made.
    r = user_b.post("/research", json={"question": "what happened?", "matter_id": seeded["matter"]})
    assert r.status_code == 404


def test_receipts_and_payments_are_per_user(user_a, user_b):
    assert user_b.get("/payments/history").json() == []
    assert user_b.get("/payments/receipt/does-not-exist.pdf").status_code == 404


PROTECTED = [
    ("GET", "/auth/me"),
    ("GET", "/matters"),
    ("POST", "/matters"),
    ("GET", "/drafts"),
    ("GET", "/research"),
    ("POST", "/research"),
    ("POST", "/verify-citation"),
    ("GET", "/recovery/cases"),
    ("POST", "/recovery/cases"),
    ("GET", "/audit"),
    ("GET", "/dashboard/stats"),
    ("GET", "/search"),
    ("GET", "/payments/history"),
    ("POST", "/payments/checkout"),
    ("POST", "/org/logo"),
    ("GET", "/org/branding"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_unauthenticated_requests_are_rejected(anon, method, path):
    r = anon.request(method, path, json={} if method != "GET" else None)
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


@pytest.mark.parametrize("path", ["/cron/recovery-reminders", "/cron/scheduled-statements"])
def test_cron_requires_bearer_secret(anon, path):
    assert anon.post(path).status_code == 401
    assert anon.post(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_a_timeline_event_needs_a_real_calendar_date(user_a):
    """Found by the feature walk: 'not-a-date' used to be stored and sorted into the timeline."""
    import uuid

    mid = user_a.post("/matters", json={"title": f"Dates {uuid.uuid4().hex[:6]}", "description": "", "parties": "", "jurisdiction_id": "IN"}).json()["id"]
    for bad in ("not-a-date", "2026-13-01", "2026-02-30", "2026/05/03", "05-03-2026", "20260503", "2026-05-03junk", "0999", "2026-5", "2026-5-3", "2026-05-3", "2026-05-03 garbage", "2026-05-03T25:99", "2026-05-03Tjunk", "２０２６", "٢٠٢٦"):
        assert user_a.post(f"/matters/{mid}/timeline", json={"event_date": bad, "description": "x"}).status_code == 422, bad
    for good in ("2026", "2026-05", "2026-05-03", "2026-05-03T10:30", "2026-05-03 10:30"):
        assert user_a.post(f"/matters/{mid}/timeline", json={"event_date": good, "description": "ok"}).status_code == 200, good
