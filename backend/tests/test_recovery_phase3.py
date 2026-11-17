"""Phase 3: Legal Recovery correctness - interest, limitation, notice blockers, safe outbound email.

The server runs with EMAIL_DRY_RUN=true, so every email lands in the email_outbox collection where the
tests can read it. Nothing is ever sent to a real address.
"""

import json
import time
import uuid

import httpx
import pytest

from tests.conftest import (
    API_URL,
    CLEAN_NOTICE,
    make_case,
    mongo,
    outbox,
    post_resend_event,
    resend_headers,
    token_from_mail,
    verify_email,
)


def _addr(prefix: str = "p3") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


# =============================================================================================
# Interest + limitation
# =============================================================================================
def test_interest_needs_due_date_and_rate_then_matches_the_calculator(user_a):
    case = make_case(user_a, notice=None)
    assert user_a.get(f"/recovery/cases/{case}/interest").status_code == 422  # no due date

    r = user_a.patch(f"/recovery/cases/{case}/details", json={"due_date": "2025-01-01"})
    assert r.status_code == 200 and r.json()["due_date"] == "2025-01-01"
    assert user_a.get(f"/recovery/cases/{case}/interest").status_code == 422  # still no rate

    user_a.patch(f"/recovery/cases/{case}/details", json={"interest_rate_pct": 12})
    r = user_a.get(f"/recovery/cases/{case}/interest", params={"as_of": "2026-01-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["interest"] == 6000.0 and body["total_due"] == 56000.0 and body["days"] == 365
    assert body["currency"] == "INR" and body["segments"] and body["assumptions"]


def test_interest_accounts_for_part_payments(user_a):
    case = make_case(user_a, notice=None)
    user_a.patch(f"/recovery/cases/{case}/details", json={"due_date": "2025-01-01", "interest_rate_pct": 12})
    user_a.post(f"/recovery/cases/{case}/payment", json={"amount": 10000})
    # The payment is dated "today" (after as_of below) so it must not reduce this result...
    r = user_a.get(f"/recovery/cases/{case}/interest", params={"as_of": "2025-06-01"}).json()
    assert r["interest"] == pytest.approx(50000 * 0.12 * 151 / 365, abs=0.01)
    # ...but it does count once as_of is after it.
    later = user_a.get(f"/recovery/cases/{case}/interest", params={"as_of": "2030-01-01"}).json()
    assert later["payments_counted"] == 10000.0 and later["principal_remaining"] == 40000.0


@pytest.mark.parametrize(
    "payload",
    [{"interest_rate_pct": 150}, {"interest_rate_pct": -1}, {"due_date": "not-a-date"}, {"due_date": "1800-01-01"}],
)
def test_details_validation(user_a, payload):
    case = make_case(user_a, notice=None)
    assert user_a.patch(f"/recovery/cases/{case}/details", json=payload).status_code == 422


def test_details_can_be_cleared(user_a):
    case = make_case(user_a, notice=None)
    user_a.patch(f"/recovery/cases/{case}/details", json={"due_date": "2025-01-01", "interest_rate_pct": 9})
    r = user_a.patch(f"/recovery/cases/{case}/details", json={"clear_due_date": True, "clear_interest": True}).json()
    assert r["due_date"] is None and r["interest_rate_pct"] is None


def test_limitation_never_invents_a_deadline(user_a):
    case = make_case(user_a, notice=None)
    assert user_a.get(f"/recovery/cases/{case}/limitation").json()["mode"] == "NEEDS_DUE_DATE"
    user_a.patch(f"/recovery/cases/{case}/details", json={"due_date": "2023-01-01"})
    body = user_a.get(f"/recovery/cases/{case}/limitation").json()
    assert body["mode"] == "GENERIC" and body["rules"] == []  # no verified rule exists yet
    assert body["age_days"] > 365 and "year" in body["age_text"]
    assert "lawyer" in body["message"] and not any(ch.isdigit() for ch in body["message"])


# =============================================================================================
# Demand notice: details required, blanks and legal references block export + email
# =============================================================================================
def test_notice_generation_requires_both_addresses(user_a):
    case = make_case(user_a, notice=None)
    r = user_a.post(f"/recovery/cases/{case}/notice")
    assert r.status_code == 422 and "address" in r.json()["detail"]
    user_a.patch(f"/recovery/cases/{case}/details", json={"creditor_address": "1 Market Road, Pune"})
    r = user_a.post(f"/recovery/cases/{case}/notice")
    assert r.status_code == 422 and "other party" in r.json()["detail"]


def test_blank_or_legal_reference_blocks_pdf_until_fixed(user_a):
    case = make_case(user_a, notice="Date: [date]\nTo: [address]\nPay Rs 40,000 within 15 days.\nThis is a draft.")
    got = user_a.get(f"/recovery/cases/{case}").json()
    assert got["notice_check"]["blocked"] and "[date]" in got["notice_check"]["placeholders"]
    r = user_a.get(f"/recovery/cases/{case}/notice.pdf")
    assert r.status_code == 409 and "fill in the blanks" in r.json()["detail"]

    fixed = user_a.patch(
        f"/recovery/cases/{case}/notice",
        json={"notice_body": "Date: 19 Oct 2026\nTo: Debtor X, Mumbai\nThis breaches Section 73 of the Contract Act. Pay Rs 40,000."},
    ).json()
    assert fixed["notice_check"]["legal_references"] and fixed["notice_check"]["blocked"]
    assert user_a.get(f"/recovery/cases/{case}/notice.pdf").status_code == 409

    ok = user_a.patch(f"/recovery/cases/{case}/notice", json={"notice_body": CLEAN_NOTICE}).json()
    assert ok["notice_check"]["blocked"] is False
    pdf = user_a.get(f"/recovery/cases/{case}/notice.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"


def test_cannot_edit_a_notice_that_does_not_exist(user_a):
    case = make_case(user_a, notice=None)
    assert user_a.patch(f"/recovery/cases/{case}/notice", json={"notice_body": CLEAN_NOTICE}).status_code == 409


# =============================================================================================
# Sender verification
# =============================================================================================
def test_signup_sends_a_verification_email_and_link_verifies(user_a):
    assert user_a.get("/auth/me").json()["email_verified"] is False
    mails = outbox(to=user_a.user["email"], subject_has="Confirm your email")
    assert len(mails) == 1
    token = token_from_mail(mails[0], "token=")
    with httpx.Client(base_url=API_URL) as anon:
        assert anon.post("/auth/verify-email", json={"token": "x" * 30}).status_code == 400
    verify_email(user_a)
    assert user_a.get("/auth/me").json()["email_verified"] is True
    assert user_a.post("/auth/verify-email/request").json()["already_verified"] is True
    with httpx.Client(base_url=API_URL) as anon:  # a used link cannot be replayed
        assert anon.post("/auth/verify-email", json={"token": token}).status_code == 400


def test_unverified_user_cannot_email_other_people(user_a):
    case = make_case(user_a)
    to = _addr("debtor")
    for method, path, body in (
        ("POST", f"/recovery/cases/{case}/email/prepare", {"debtor_email": to}),
        ("POST", f"/recovery/cases/{case}/email", {"confirmation_id": "x" * 20, "acknowledged": True}),
        ("PUT", f"/recovery/cases/{case}/accountants", {"emails": [_addr()]}),
        ("POST", f"/recovery/cases/{case}/statement-email", {"email": user_a.user["email"]}),
    ):
        r = user_a.request(method, path, json=body)
        assert r.status_code == 403 and "verify your email" in r.json()["detail"], (path, r.text)
    assert outbox(to=to) == []


# =============================================================================================
# Preview -> confirm -> send
# =============================================================================================
def test_notice_email_needs_preview_and_explicit_confirmation(verified_a):
    case, to = make_case(verified_a), _addr("debtor")
    # Cannot send with no/forged confirmation.
    assert verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": "f" * 36, "acknowledged": True}).status_code == 409
    assert outbox(to=to) == []

    prev = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to})
    assert prev.status_code == 200
    p = prev.json()
    assert p["to"] == to.lower() and p["cc"] == [] and p["notice_text"] == CLEAN_NOTICE
    assert p["subject"].startswith("Demand notice") and p["sender_copy_to"] == verified_a.user["email"].lower()
    assert outbox(to=to) == []  # previewing sends nothing

    unticked = verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"]})
    assert unticked.status_code == 422 and outbox(to=to) == []

    sent = verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True})
    assert sent.status_code == 200 and sent.json()["sent_to"] == to.lower() and sent.json()["status"] == "ACCEPTED"
    assert len(outbox(to=to)) == 1 and len(outbox(to=verified_a.user["email"], subject_has="Copy: Demand notice")) == 1
    assert verified_a.get(f"/recovery/cases/{case}").json()["debtor_email_status"] == "ACCEPTED"

    # One confirmation can never send twice.
    again = verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True})
    assert again.status_code == 409 and len(outbox(to=to)) == 1


def test_sends_only_to_the_previewed_recipient_not_whatever_the_request_says(verified_a):
    case, to, other = make_case(verified_a), _addr("debtor"), _addr("attacker")
    p = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to}).json()
    verified_a.post(
        f"/recovery/cases/{case}/email",
        json={"confirmation_id": p["confirmation_id"], "acknowledged": True, "debtor_email": other},
    )
    assert len(outbox(to=to)) == 1 and outbox(to=other) == []


def test_editing_the_notice_after_preview_invalidates_the_confirmation(verified_a):
    case, to = make_case(verified_a), _addr("debtor")
    p = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to}).json()
    verified_a.patch(f"/recovery/cases/{case}/notice", json={"notice_body": CLEAN_NOTICE + "\nExtra line added later."})
    r = verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True})
    assert r.status_code == 409 and "changed" in r.json()["detail"] and outbox(to=to) == []


def test_blocked_notice_cannot_even_be_previewed(verified_a):
    case = make_case(verified_a, notice="Pay Rs 40,000 to [name] within 15 days under Section 73 of the Contract Act.")
    r = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": _addr()})
    assert r.status_code == 409 and "Before you can" in r.json()["detail"]


def test_confirmation_is_bound_to_its_case_and_user(verified_a, verified_b):
    case_a, case_b = make_case(verified_a), make_case(verified_a)
    to = _addr("debtor")
    p = verified_a.post(f"/recovery/cases/{case_a}/email/prepare", json={"debtor_email": to}).json()
    # same user, different case
    r = verified_a.post(f"/recovery/cases/{case_b}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True})
    assert r.status_code == 409
    # another organisation can't use it on any case
    r = verified_b.post(f"/recovery/cases/{case_a}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True})
    assert r.status_code == 404
    assert outbox(to=to) == []


# =============================================================================================
# Accountant consent
# =============================================================================================
def _add_accountant(c, case, email):
    r = c.put(f"/recovery/cases/{case}/accountants", json={"emails": [email]})
    assert r.status_code == 200, r.text
    return r.json()


def test_accountant_gets_nothing_until_they_confirm(verified_a):
    case, acct, to = make_case(verified_a), _addr("acct"), _addr("debtor")
    out = _add_accountant(verified_a, case, acct)
    assert out["accountants"][0]["status"] == "PENDING" and out["accountant_emails"] == []
    reqs = outbox(to=acct)
    assert len(reqs) == 1 and "confirm" in reqs[0]["subject"].lower()

    # CC requested but accountant not confirmed -> not copied, not even listed in the preview.
    p = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to, "cc_accountants": True}).json()
    assert p["cc"] == []
    verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True})
    assert len(outbox(to=acct)) == 1  # still only the consent request

    # Statement to an unconfirmed address is refused.
    r = verified_a.post(f"/recovery/cases/{case}/statement-email", json={"email": acct})
    assert r.status_code == 403 and "confirmed" in r.json()["detail"]


def test_confirm_then_cc_and_statement_work_and_carry_a_stop_link(verified_a):
    case, acct, to = make_case(verified_a), _addr("acct"), _addr("debtor")
    _add_accountant(verified_a, case, acct)
    token = token_from_mail(outbox(to=acct)[0], "/consent/")

    with httpx.Client(base_url=API_URL) as anon:
        info = anon.get(f"/public/consent/{token}").json()
        assert info["status"] == "PENDING" and info["can_confirm"] is True and info["creditor_name"] == "A Traders"
        assert anon.get("/public/consent/not.a.token").status_code == 404
        tampered = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
        assert anon.post(f"/public/consent/{tampered}", json={"action": "confirm"}).status_code == 404
        assert anon.post(f"/public/consent/{token}", json={"action": "confirm"}).json()["status"] == "CONFIRMED"

    got = verified_a.get(f"/recovery/cases/{case}").json()
    assert got["accountant_emails"] == [acct.lower()]

    p = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to, "cc_accountants": True}).json()
    assert p["cc"] == [acct.lower()]
    sent = verified_a.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True}).json()
    assert sent["cc_sent"] == [acct.lower()]

    st = verified_a.post(f"/recovery/cases/{case}/statement-email", json={"email": acct})
    assert st.status_code == 200
    stmt = [m for m in outbox(to=acct) if "Balance statement" in m["subject"]][-1]
    assert "/consent/" in stmt["html"]  # stop-receiving link is in every copy

    # They can stop at any time using the link from a statement copy.
    stop_token = token_from_mail(stmt, "/consent/")
    with httpx.Client(base_url=API_URL) as anon:
        assert anon.post(f"/public/consent/{stop_token}", json={"action": "decline"}).json()["status"] == "DECLINED"
    assert verified_a.get(f"/recovery/cases/{case}").json()["accountant_emails"] == []
    assert verified_a.post(f"/recovery/cases/{case}/statement-email", json={"email": acct}).status_code == 403


def test_a_declined_accountant_cannot_be_asked_again_by_re_adding(verified_a):
    case, acct = make_case(verified_a), _addr("acct")
    _add_accountant(verified_a, case, acct)
    token = token_from_mail(outbox(to=acct)[0], "/consent/")
    with httpx.Client(base_url=API_URL) as anon:
        anon.post(f"/public/consent/{token}", json={"action": "decline"})
    verified_a.put(f"/recovery/cases/{case}/accountants", json={"emails": []})
    out = _add_accountant(verified_a, case, acct)
    assert out["accountants"][0]["status"] == "DECLINED"
    assert len(outbox(to=acct)) == 1  # no second request was sent
    with httpx.Client(base_url=API_URL) as anon:  # and they cannot be flipped to confirmed by an old link
        assert anon.post(f"/public/consent/{token}", json={"action": "confirm"}).status_code == 409


def test_expired_consent_request_cannot_be_confirmed(verified_a):
    from lib.outbound import make_link_token

    case, acct = make_case(verified_a), _addr("acct")
    _add_accountant(verified_a, case, acct)
    old = make_link_token({"c": case, "e": acct.lower(), "t": 1_600_000_000})  # years ago
    with httpx.Client(base_url=API_URL) as anon:
        assert anon.get(f"/public/consent/{old}").json()["expired"] is True
        assert anon.post(f"/public/consent/{old}", json={"action": "confirm"}).status_code == 410


def test_legacy_unconsented_accountant_emails_are_ignored(verified_a):
    case, legacy = make_case(verified_a), _addr("legacy")
    mongo().recovery_cases.update_one({"id": case}, {"$set": {"accountant_emails": [legacy]}})
    assert verified_a.get(f"/recovery/cases/{case}").json()["accountant_emails"] == []
    assert verified_a.post(f"/recovery/cases/{case}/statement-email", json={"email": legacy}).status_code == 403
    # old clients that still send accountant_emails to the schedule route cannot smuggle one in
    verified_a.patch(f"/recovery/cases/{case}/statement-schedule", json={"accountant_emails": [_addr("sneaky")]})
    assert verified_a.get(f"/recovery/cases/{case}").json()["accountant_emails"] == []


def test_other_org_cannot_use_the_new_routes(verified_a, verified_b):
    case = make_case(verified_a)
    for method, path, body in (
        ("GET", f"/recovery/cases/{case}/interest", None),
        ("GET", f"/recovery/cases/{case}/limitation", None),
        ("GET", f"/recovery/cases/{case}/emails", None),
        ("PATCH", f"/recovery/cases/{case}/details", {"due_date": "2025-01-01"}),
        ("PATCH", f"/recovery/cases/{case}/notice", {"notice_body": CLEAN_NOTICE}),
        ("PUT", f"/recovery/cases/{case}/accountants", {"emails": [_addr()]}),
        ("POST", f"/recovery/cases/{case}/accountants/resend", {"email": _addr()}),
        ("POST", f"/recovery/cases/{case}/email/prepare", {"debtor_email": _addr()}),
    ):
        r = verified_b.request(method, path, json=body)
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}"


# =============================================================================================
# Delivery status + suppression
# =============================================================================================
def _debtor_provider_id(c, case):
    row = next(r for r in c.get(f"/recovery/cases/{case}/emails").json() if r["kind"] == "notice-debtor")
    return mongo().email_log.find_one({"id": row["id"]})["provider_id"]


def _send_notice(c, case, to):
    p = c.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to}).json()
    assert c.post(f"/recovery/cases/{case}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True}).status_code == 200


def test_bounce_updates_status_and_blocks_future_sends_to_that_address(verified_a):
    case, to = make_case(verified_a), _addr("debtor")
    _send_notice(verified_a, case, to)
    row = next(r for r in verified_a.get(f"/recovery/cases/{case}/emails").json() if r["kind"] == "notice-debtor")
    assert row["status"] == "ACCEPTED"  # honest: accepted by the provider, not proven delivered
    pid = _debtor_provider_id(verified_a, case)

    r = post_resend_event("email.bounced", pid, bounce={"type": "Permanent", "message": "mailbox does not exist"})
    assert r.status_code == 200 and r.json()["unknown_message"] is False
    log = verified_a.get(f"/recovery/cases/{case}/emails").json()
    assert next(r for r in log if r["kind"] == "notice-debtor")["status"] == "BOUNCED"
    assert verified_a.get(f"/recovery/cases/{case}").json()["debtor_email_status"] == "BOUNCED"
    again = verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to})
    assert again.status_code == 409 and "cannot receive email" in again.json()["detail"]


def test_a_temporary_bounce_is_reported_but_does_not_blacklist_the_address(verified_a):
    case, to = make_case(verified_a), _addr("debtor")
    _send_notice(verified_a, case, to)
    pid = _debtor_provider_id(verified_a, case)
    assert post_resend_event("email.bounced", pid, bounce={"type": "Transient", "message": "mailbox full"}).status_code == 200
    assert verified_a.get(f"/recovery/cases/{case}").json()["debtor_email_status"] == "BOUNCED"
    assert verified_a.post(f"/recovery/cases/{case}/email/prepare", json={"debtor_email": to}).status_code == 200


def test_spam_complaint_suppresses_and_delivered_updates_status(verified_a):
    c1, t1 = make_case(verified_a), _addr("debtor")
    _send_notice(verified_a, c1, t1)
    post_resend_event("email.complained", _debtor_provider_id(verified_a, c1))
    assert verified_a.get(f"/recovery/cases/{c1}").json()["debtor_email_status"] == "COMPLAINED"
    assert verified_a.post(f"/recovery/cases/{c1}/email/prepare", json={"debtor_email": t1}).status_code == 409

    c2, t2 = make_case(verified_a), _addr("debtor")
    _send_notice(verified_a, c2, t2)
    post_resend_event("email.delivered", _debtor_provider_id(verified_a, c2))
    assert verified_a.get(f"/recovery/cases/{c2}").json()["debtor_email_status"] == "DELIVERED"


def test_a_bounced_accountant_is_marked_and_no_longer_copied(verified_a):
    case, acct = make_case(verified_a), _addr("acct")
    _add_accountant(verified_a, case, acct)
    req = mongo().email_log.find_one({"to": acct.lower(), "kind": "consent-request"})
    post_resend_event("email.bounced", req["provider_id"], bounce={"type": "Permanent", "message": "no such user"})
    got = verified_a.get(f"/recovery/cases/{case}").json()
    assert got["accountants"][0]["status"] == "BOUNCED" and got["accountant_emails"] == []


def test_webhook_rejects_anything_not_signed_by_resend(anon):
    ev = json.dumps({"type": "email.bounced", "data": {"email_id": "whatever"}}).encode()
    assert anon.post("/webhooks/resend", content=ev).status_code == 401  # unsigned
    assert anon.post("/webhooks/resend", content=ev, headers=resend_headers(ev, secret="whsec_" + "AAAA" * 8)).status_code == 401  # wrong secret
    good = resend_headers(ev)
    assert anon.post("/webhooks/resend", content=ev + b" ", headers=good).status_code == 401  # body tampered after signing
    stale = resend_headers(ev, ts=int(time.time()) - 3600)
    assert anon.post("/webhooks/resend", content=ev, headers=stale).status_code == 401  # replayed old message
    assert anon.post("/webhooks/email", content=ev).status_code == 404  # the old shared-secret route is gone


def test_webhook_ignores_unknown_messages_and_irrelevant_events(anon):
    assert post_resend_event("email.bounced", "not-one-of-ours").json()["unknown_message"] is True  # 200, so Resend stops retrying
    assert post_resend_event("email.opened", "anything").json()["ignored"] is True