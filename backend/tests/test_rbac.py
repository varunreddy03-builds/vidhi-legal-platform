"""Roles: who may do what, enforced centrally (lib/rbac.py) and tested across every role."""

import uuid

import httpx
import pytest

from tests.conftest import API_URL, mongo, new_member, outbox, token_from_mail, verify_email, mark_stub_paid

ALL = ("OWNER", "ADMIN", "LAWYER", "MEMBER")


@pytest.fixture
def team(user_a):
    """One organisation with a verified owner and one member of each other role."""
    verify_email(user_a)
    t = {"OWNER": user_a, "ADMIN": new_member(user_a, "ADMIN"), "LAWYER": new_member(user_a, "LAWYER"), "MEMBER": new_member(user_a, "MEMBER")}
    yield t
    for role in ("ADMIN", "LAWYER", "MEMBER"):
        t[role].close()


def test_capabilities_by_role(team):
    caps = {r: set(c.get("/auth/me").json()["capabilities"]) for r, c in team.items()}
    assert caps["OWNER"] == {"read", "write", "ai", "send_mail", "delete", "admin", "billing", "owner", "advocate_review", "approve_draft", "account"}
    assert caps["ADMIN"] == {"read", "write", "ai", "send_mail", "delete", "admin", "advocate_review", "approve_draft", "account"}
    assert caps["LAWYER"] == {"read", "write", "ai", "send_mail", "advocate_review", "approve_draft", "account"}
    assert caps["MEMBER"] == {"read", "write", "account"}
    assert [team[r].get("/auth/me").json()["role"] for r in ALL] == list(ALL)


# (method, path, body) -> roles that must be REFUSED (403). Everyone else must get past the role check
# (a 404/422/502 from the handler is fine - it just must not be a 403 from the policy).
MATRIX = [
    ("POST", "/research", {"question": "what happened here"}, {"MEMBER"}),
    ("POST", "/documents/nope/analyze", None, {"MEMBER"}),
    ("POST", "/matters/nope/synthesize", None, {"MEMBER"}),
    ("POST", "/recovery/cases/nope/extract", None, {"MEMBER"}),
    ("POST", "/recovery/cases/nope/notice", None, {"MEMBER"}),
    ("POST", "/recovery/cases/nope/email/prepare", {"debtor_email": "d@example.com"}, {"MEMBER"}),
    ("POST", "/recovery/cases/nope/email", {"confirmation_id": "x" * 12, "acknowledged": True}, {"MEMBER"}),
    ("POST", "/recovery/cases/nope/statement-email", {"email": "d@example.com"}, {"MEMBER"}),
    ("PUT", "/recovery/cases/nope/accountants", {"emails": []}, {"MEMBER"}),
    ("DELETE", "/matters/nope", None, {"MEMBER", "LAWYER"}),
    ("DELETE", "/documents/nope", None, {"MEMBER", "LAWYER"}),
    ("DELETE", "/drafts/nope", None, {"MEMBER", "LAWYER"}),
    ("DELETE", "/recovery/cases/nope", None, {"MEMBER", "LAWYER"}),
    ("DELETE", "/matters/nope/facts/x", None, set()),  # routine edit: every role may
    ("DELETE", "/matters/nope/evidence/x", None, set()),
    ("POST", "/matters", {"title": "A matter"}, set()),
    ("GET", "/matters", None, set()),
    ("GET", "/org/members", None, {"MEMBER", "LAWYER"}),
    ("GET", "/org/invites", None, {"MEMBER", "LAWYER"}),
    ("POST", "/org/invites", {"email": "someone@example.com", "role": "MEMBER"}, {"MEMBER", "LAWYER"}),
    ("PATCH", "/org/branding", {"firm_name": "X"}, {"MEMBER", "LAWYER"}),
    ("POST", "/org/logo", None, {"MEMBER", "LAWYER"}),
    ("GET", "/org/branding", None, set()),
    ("POST", "/payments/checkout", {"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"}, {"ADMIN", "LAWYER", "MEMBER"}),
    ("GET", "/payments/history", None, {"ADMIN", "LAWYER", "MEMBER"}),
    ("GET", "/audit", None, {"MEMBER", "LAWYER"}),  # organisation-wide log
    ("GET", "/audit?matter_id=nope", None, set()),  # one matter's activity
]


@pytest.mark.parametrize("method,path,body,refused", MATRIX, ids=[f"{m} {p}" for m, p, _, _ in MATRIX])
def test_role_matrix(team, method, path, body, refused):
    for role in ALL:
        r = team[role].request(method, path, json=body) if body is not None else team[role].request(method, path)
        if role in refused:
            assert r.status_code == 403, f"{role} should be refused on {method} {path}, got {r.status_code}: {r.text[:120]}"
        else:
            assert r.status_code != 403, f"{role} should be allowed on {method} {path}, got 403: {r.text[:120]}"


def test_refusal_message_names_the_role_and_who_to_ask(team):
    r = team["MEMBER"].post("/research", json={"question": "what happened here"})
    assert r.status_code == 403 and "Member" in r.json()["detail"] and "owner or admin" in r.json()["detail"]


def test_unauthenticated_is_still_401_not_403(anon):
    assert anon.post("/research", json={"question": "abc def"}).status_code == 401
    assert anon.delete("/matters/x").status_code == 401


# ---------------- no route can become public by accident ----------------
PUBLIC_ALLOWLIST = {
    ("GET", "/api/health"), ("GET", "/api/public/legal-config"), ("GET", "/api/public/support-info"), ("POST", "/api/public/support"),
    ("POST", "/api/auth/signup"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/verify-email"), ("POST", "/api/auth/forgot-password"), ("POST", "/api/auth/reset-password"),
    ("POST", "/api/auth/accept-invite"), ("GET", "/api/auth/invites/{token}"),
    ("GET", "/api/auth/options"), ("GET", "/api/auth/google/start"), ("GET", "/api/auth/google/callback"),
    ("GET", "/api/public/consent/{token}"), ("POST", "/api/public/consent/{token}"),
    ("POST", "/api/webhook/stripe"), ("POST", "/api/webhook/razorpay"), ("POST", "/api/webhook/paypal"), ("POST", "/api/webhooks/resend"), ("POST", "/api/webhooks/sendgrid"), ("POST", "/api/webhooks/twilio"),
    ("POST", "/api/cron/recovery-reminders"), ("POST", "/api/cron/scheduled-statements"), ("POST", "/api/cron/retention"), ("POST", "/api/cron/upload-expiry"), ("POST", "/api/cron/deadline-reminders"), ("POST", "/api/cron/jobs"),
    ("GET", "/api/public/directory"), ("GET", "/api/public/lawyers"), ("GET", "/api/public/lawyers/{profile_id}"), ("POST", "/api/public/lawyers/{profile_id}/requests"),
    ("GET", "/api/payments/status/{session_id}"), ("GET", "/api/org/logo/{org_id}"),
    ("GET", "/api/health/ready"),
}


def _all_routes():
    from server import app

    return [(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops if m in ("get", "post", "put", "patch", "delete")]


def test_only_the_listed_routes_are_public_and_the_rest_need_a_role():
    from lib.rbac import ROLE_CAPS, required_cap

    public = {(m, p) for m, p in _all_routes() if required_cap(m, p) is None}
    assert public == {r for r in PUBLIC_ALLOWLIST if r in set(_all_routes())}, sorted(public ^ PUBLIC_ALLOWLIST)
    known = set().union(*ROLE_CAPS.values())
    for m, p in _all_routes():
        cap = required_cap(m, p)
        assert cap is None or cap in known, (m, p, cap)


KATALYST_ADDIN_ROUTES = {"/api/v1/katalyst/analyze-text", "/api/v1/katalyst/redline-docx"}


def test_sensitive_actions_demand_the_right_capability():
    from lib.rbac import required_cap

    must = {
        ("POST", "/api/research"): "ai", ("POST", "/api/documents/{document_id}/analyze"): "ai",
        ("POST", "/api/matters/{matter_id}/synthesize"): "ai", ("POST", "/api/recovery/cases/{case_id}/notice"): "ai",
        ("POST", "/api/recovery/cases/{case_id}/email"): "send_mail", ("POST", "/api/recovery/cases/{case_id}/statement-email"): "send_mail",
        ("PUT", "/api/recovery/cases/{case_id}/accountants"): "send_mail",
        ("DELETE", "/api/matters/{matter_id}"): "delete", ("DELETE", "/api/recovery/cases/{case_id}"): "delete",
        ("POST", "/api/payments/checkout"): "billing", ("GET", "/api/payments/history"): "billing",
        ("GET", "/api/org/members"): "admin", ("POST", "/api/org/invites"): "admin", ("PATCH", "/api/org/branding"): "admin",
        ("DELETE", "/api/org"): "owner", ("GET", "/api/org/export"): "admin",
    }
    for (m, p), cap in must.items():
        assert required_cap(m, p) == cap, (m, p, required_cap(m, p))
    # anything that can email somebody or call the AI must not fall through to a plain "write"
    for m, p in _all_routes():
        if p in KATALYST_ADDIN_ROUTES:
            continue  # plain code, no AI and no email: "analyze" here means reading text; tests/test_katalyst_addin.py proves the modules import no AI and no mail code
        if m == "POST" and "/payments/" not in p and any(w in p for w in ("/email", "statement-email", "/analyze", "/synthesize", "/extract", "/research")):
            assert required_cap(m, p) in ("ai", "send_mail"), (m, p)


# ---------------- the subscription belongs to the organisation ----------------
def test_members_use_the_owners_plan(team):
    from tests.conftest import set_plan

    owner, lawyer = team["OWNER"], team["LAWYER"]
    set_plan(owner, "FREE")
    assert lawyer.get("/auth/entitlement").json()["plan"] == "FREE"  # the team is on the organisation's plan, whatever their own
    r = owner.post("/payments/checkout", json={"package_id": "vidhi_pro", "origin_url": "http://localhost:3000"})
    sid = r.json()["session_id"]
    mark_stub_paid(sid, amount_total=199900, user_id=owner.user["id"], subscription_id="sub_rbac_1")
    assert owner.get(f"/payments/status/{sid}").json()["payment_status"] == "paid"
    assert team["MEMBER"].get("/auth/entitlement").json()["plan"] == "PRO"
    assert lawyer.get("/auth/entitlement").json()["plan"] == "PRO"
    # a lawyer can run AI (the scripted model has no reply queued, so the handler answers 502 - not 402/403)
    assert lawyer.post("/research", json={"question": "what is the position here"}).status_code == 502


# ---------------- inviting, accepting, managing ----------------
def test_invitation_flow_and_rules(user_a):
    verify_email(user_a)
    new_email = f"inv-{uuid.uuid4().hex[:8]}@example.com"
    # unverified inviter cannot invite
    with httpx.Client(base_url=API_URL) as other:
        o = other.post("/auth/signup", json={"email": f"o-{uuid.uuid4().hex[:8]}@example.com", "password": "Pw-" + "z9" * 12, "full_name": "O", "organization_name": "O Org", "accept_privacy": True})
        assert other.post("/org/invites", json={"email": new_email, "role": "MEMBER"}).status_code == 403 and "verify your email" in other.post("/org/invites", json={"email": new_email, "role": "MEMBER"}).json()["detail"]
    assert user_a.post("/org/invites", json={"email": user_a.user["email"], "role": "MEMBER"}).status_code == 409  # already has an account

    assert user_a.post("/org/invites", json={"email": new_email, "role": "LAWYER"}).status_code == 200
    assert [i["email"] for i in user_a.get("/org/invites").json()] == [new_email]
    mail = outbox(to=new_email, subject_has="invited")[-1]
    assert user_a.user["organization_name"] in mail["html"] and "Lawyer" in mail["html"]
    token = token_from_mail(mail, "token=")

    with httpx.Client(base_url=API_URL) as anon:
        info = anon.get(f"/auth/invites/{token}").json()
        assert info["email"] == new_email and info["role"] == "LAWYER" and info["organization_name"] == user_a.user["organization_name"]
        assert anon.get("/auth/invites/not-a-token").status_code == 404
        body = {"token": token, "full_name": "New Person", "password": "Pw-" + "k7" * 12, "accept_privacy": True}
        assert anon.post("/auth/accept-invite", json={**body, "accept_privacy": False}).status_code == 422  # must acknowledge
        assert anon.post("/auth/accept-invite", json={**body, "password": "password123"}).status_code == 422  # weak -> invitation survives
        ok = anon.post("/auth/accept-invite", json=body)
        assert ok.status_code == 200 and ok.json()["role"] == "LAWYER" and ok.json()["email_verified"] is True
        assert "vidhi_session" in ok.cookies
        assert anon.get("/auth/me").json()["organization_id"] == user_a.user["organization_id"]
        assert anon.post("/auth/accept-invite", json=body).status_code == 404  # single use
    assert user_a.get("/org/invites").json() == []


def test_expired_and_cancelled_invitations_are_dead(user_a):
    from datetime import datetime, timedelta, timezone

    verify_email(user_a)
    e1, e2 = (f"x{i}-{uuid.uuid4().hex[:8]}@example.com" for i in (1, 2))
    for e in (e1, e2):
        assert user_a.post("/org/invites", json={"email": e, "role": "MEMBER"}).status_code == 200
    t1 = token_from_mail(outbox(to=e1, subject_has="invited")[-1], "token=")
    t2 = token_from_mail(outbox(to=e2, subject_has="invited")[-1], "token=")
    mongo().invites.update_one({"email": e1}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}})
    inv2 = next(i for i in user_a.get("/org/invites").json() if i["email"] == e2)
    assert user_a.delete(f"/org/invites/{inv2['id']}").status_code == 200
    with httpx.Client(base_url=API_URL) as anon:
        for t in (t1, t2):
            assert anon.get(f"/auth/invites/{t}").status_code == 404
            assert anon.post("/auth/accept-invite", json={"token": t, "full_name": "N", "password": "Pw-" + "q3" * 12, "accept_privacy": True}).status_code == 404


def test_who_may_invite_whom(team):
    owner, admin, lawyer = team["OWNER"], team["ADMIN"], team["LAWYER"]
    mk = lambda: f"i-{uuid.uuid4().hex[:8]}@example.com"  # noqa: E731
    assert admin.post("/org/invites", json={"email": mk(), "role": "LAWYER"}).status_code == 200
    assert admin.post("/org/invites", json={"email": mk(), "role": "MEMBER"}).status_code == 200
    assert admin.post("/org/invites", json={"email": mk(), "role": "ADMIN"}).status_code == 403
    assert admin.post("/org/invites", json={"email": mk(), "role": "OWNER"}).status_code == 403
    assert owner.post("/org/invites", json={"email": mk(), "role": "OWNER"}).status_code == 200
    assert lawyer.post("/org/invites", json={"email": mk(), "role": "MEMBER"}).status_code == 403


def test_role_changes_and_removal_follow_the_hierarchy(team):
    owner, admin, lawyer, member = team["OWNER"], team["ADMIN"], team["LAWYER"], team["MEMBER"]
    uid = {r: c.user["id"] for r, c in team.items()}
    # admin: may move lawyers/members between lawyer and member only
    assert admin.patch(f"/org/members/{uid['MEMBER']}", json={"role": "LAWYER"}).json()["role"] == "LAWYER"
    assert member.get("/auth/me").json()["capabilities"] == ["account", "advocate_review", "ai", "approve_draft", "read", "send_mail", "write"]  # takes effect at once
    assert admin.patch(f"/org/members/{uid['MEMBER']}", json={"role": "ADMIN"}).status_code == 403  # cannot grant admin
    assert admin.patch(f"/org/members/{uid['OWNER']}", json={"role": "MEMBER"}).status_code == 403  # cannot touch an owner
    assert admin.patch(f"/org/members/{uid['LAWYER']}", json={"role": "OWNER"}).status_code == 403
    assert admin.delete(f"/org/members/{uid['OWNER']}").status_code == 403
    assert lawyer.patch(f"/org/members/{uid['MEMBER']}", json={"role": "MEMBER"}).status_code == 403
    # nobody edits or removes themselves here
    assert owner.patch(f"/org/members/{uid['OWNER']}", json={"role": "ADMIN"}).status_code == 409
    assert admin.delete(f"/org/members/{uid['ADMIN']}").status_code == 409
    # owner may do anything to others, including promoting to owner
    assert owner.patch(f"/org/members/{uid['ADMIN']}", json={"role": "OWNER"}).json()["role"] == "OWNER"
    assert admin.get("/auth/me").json()["capabilities"].count("billing") == 1


def test_removing_a_member_ends_their_sessions_and_keeps_their_work(team):
    owner, lawyer = team["OWNER"], team["LAWYER"]
    m = lawyer.post("/matters", json={"title": "Created by the lawyer"}).json()["id"]
    assert lawyer.get("/auth/me").status_code == 200
    assert owner.delete(f"/org/members/{lawyer.user['id']}").status_code == 200
    assert lawyer.get("/auth/me").status_code == 401  # signed out immediately, everywhere
    assert owner.get(f"/matters/{m}").status_code == 200  # the organisation keeps the work
    assert lawyer.user["email"] not in [x["email"] for x in owner.get("/org/members").json()]
    assert any(e["operation"] == "MEMBER_REMOVE" for e in owner.get("/audit").json())


def test_members_share_the_organisations_data_but_nobody_elses(team, user_b):
    owner, member = team["OWNER"], team["MEMBER"]
    mid = owner.post("/matters", json={"title": "Shared matter"}).json()["id"]
    assert member.get(f"/matters/{mid}").status_code == 200
    assert member.post(f"/matters/{mid}/facts", json={"value": "added by a member"}).status_code == 200
    assert user_b.get(f"/matters/{mid}").status_code == 404
    # another organisation's owner sees none of this team and cannot touch it
    assert user_b.get("/org/members").json() != [] and all(x["id"] not in {c.user["id"] for c in team.values()} for x in user_b.get("/org/members").json())
    assert user_b.patch(f"/org/members/{member.user['id']}", json={"role": "ADMIN"}).status_code == 404
    assert user_b.delete(f"/org/members/{member.user['id']}").status_code == 404


def test_org_wide_audit_log_is_for_admins(team):
    team["OWNER"].post("/matters", json={"title": "Something to log"})
    assert len(team["ADMIN"].get("/audit").json()) > 0
    assert team["MEMBER"].get("/audit").status_code == 403 and team["LAWYER"].get("/audit").status_code == 403


def test_whoever_may_make_a_toolkit_report_may_delete_it():
    from lib.rbac import ROLE_CAPS, required_cap

    for path in ("/api/datelists/{list_id}", "/api/defectchecks/{check_id}", "/api/oldcodechecks/{check_id}", "/api/authority/checks/{report_id}"):
        cap = required_cap("DELETE", path)
        assert cap == "write", path  # the screens show a Delete button to everyone who can make a report
        assert all(cap in ROLE_CAPS[r] for r in ("OWNER", "ADMIN", "LAWYER", "MEMBER")) and cap not in ROLE_CAPS["CLIENT"]
    assert required_cap("DELETE", "/api/matters/{matter_id}") == "delete"  # real deletions are still reserved
