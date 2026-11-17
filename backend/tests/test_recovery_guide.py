"""Legal Recovery guided flow: the saved stage, the five answers, and the rule that 'emailed' needs our own email log."""

from tests.test_recovery_stage1 import new_case


def test_guide_starts_not_started_and_saves_answers_and_stage(verified_a):
    c = verified_a
    cid, _ = new_case(c)
    assert c.get(f"/recovery/cases/{cid}").json()["guide"] == {}
    r = c.patch(f"/recovery/cases/{cid}/guide", json={"answers": {"udyam": "yes", "buyer": "business", "has_documents": True, "overdue": "over_45", "amount": 52000}})
    assert r.status_code == 200, r.text
    g = r.json()["guide"]
    assert g["stage"] == "NOT_STARTED" and g["answers"]["udyam"] == "yes" and g["answers"]["amount"] == 52000
    # a later call adds to the answers, it does not wipe them
    r = c.patch(f"/recovery/cases/{cid}/guide", json={"stage": "PORTAL_FILED"})
    g = r.json()["guide"]
    assert g["stage"] == "PORTAL_FILED" and g["answers"]["buyer"] == "business" and g["stage_changed_at"]
    assert c.get(f"/recovery/cases/{cid}").json()["guide"]["stage"] == "PORTAL_FILED"  # saved, so the person can leave and resume


def test_guide_refuses_bad_values(verified_a):
    c = verified_a
    cid, _ = new_case(c)
    for bad in ({"stage": "DONE"}, {"answers": {"udyam": "maybe"}}, {"answers": {"amount": -1}}, {"delivery_method": "pigeon"}):
        assert c.patch(f"/recovery/cases/{cid}/guide", json=bad).status_code == 422, bad


def test_notice_sent_needs_a_delivery_method_and_emailed_needs_the_email_log(verified_a):
    c = verified_a
    cid, _ = new_case(c)
    assert c.patch(f"/recovery/cases/{cid}/guide", json={"stage": "NOTICE_SENT"}).status_code == 422
    r = c.patch(f"/recovery/cases/{cid}/guide", json={"delivery_method": "emailed"})
    assert r.status_code == 409  # nothing was emailed, so it cannot be marked as emailed
    r = c.patch(f"/recovery/cases/{cid}/guide", json={"delivery_method": "downloaded", "stage": "NOTICE_SENT"})
    assert r.status_code == 200 and r.json()["guide"]["delivery_method"] == "downloaded" and r.json()["guide"]["stage"] == "NOTICE_SENT"


def test_guide_is_private_to_the_business(verified_a, verified_b):
    cid, _ = new_case(verified_a)
    assert verified_b.patch(f"/recovery/cases/{cid}/guide", json={"stage": "PORTAL_FILED"}).status_code == 404


TEMPLATE_TEXT = (
    "Date: 30 Oct 2026\nTo: Debtor Ltd, 9 Lake View, Mumbai\nFrom: A Traders, 1 Market Road, Pune\n\n"
    "Subject: Payment due against invoice INV-7 dated 1 June 2026\n\n"
    "1. We supplied rolled steel to you and raised invoice INV-7 dated 1 June 2026.\n"
    "2. The payment fell due on 1 August 2026 and has not been received in full.\n\n{{STATEMENT}}\n\n"
    "3. Please pay the balance due within 15 days of receiving this notice, or reply in writing saying what you dispute.\n\n{{ENCLOSURES}}\n\n"
    "Yours faithfully, A Traders\nThis is a draft to be reviewed before sending."
)


def test_notice_from_template_needs_no_ai_and_runs_the_usual_checks(verified_a):
    c = verified_a
    cid, _ = new_case(c)
    r = c.post(f"/recovery/cases/{cid}/notice/template", json={"text": TEMPLATE_TEXT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "{{STATEMENT}}" not in body["notice_body"] and "40,000" in body["notice_body"]  # the statement of account was written by our code
    assert body["notice_meta"]["ai_drafted"] is False and body["notice_meta"]["from_template"] is True
    assert "TEMPLATE" in [v["origin"] for v in c.get(f"/recovery/cases/{cid}/notice/versions").json()]
    # the PDF downloads, and a notice that is not approved yet cannot be emailed
    pdf = c.get(f"/recovery/cases/{cid}/notice.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    prep = c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": "buyer@example.com"})
    assert prep.status_code == 409


def test_notice_from_template_with_a_section_in_it_cannot_be_downloaded(verified_a):
    c = verified_a
    cid, _ = new_case(c)
    bad = TEMPLATE_TEXT.replace("or reply in writing", "or reply in writing; Section 138 applies")
    assert c.post(f"/recovery/cases/{cid}/notice/template", json={"text": bad}).status_code == 200
    assert c.get(f"/recovery/cases/{cid}/notice.pdf").status_code == 409  # the legal-reference check still stops it


def test_notice_from_template_needs_addresses_and_an_amount(verified_a):
    c = verified_a
    cid = c.post("/recovery/cases", json={"creditor_name": "A", "debtor_name": "B", "amount": 100}).json()["id"]
    assert c.post(f"/recovery/cases/{cid}/notice/template", json={"text": TEMPLATE_TEXT}).status_code == 422


import uuid  # noqa: E402

from tests.conftest import outbox  # noqa: E402


def _approved_template_case(c):
    cid, _ = new_case(c)
    assert c.post(f"/recovery/cases/{cid}/notice/template", json={"text": TEMPLATE_TEXT}).status_code == 200
    assert c.post(f"/recovery/cases/{cid}/notice/approve", json={"acknowledged": True}).status_code == 200
    return cid


def test_email_uses_the_senders_subject_and_cover_message_and_shows_them_in_the_preview(verified_a):
    c = verified_a
    cid = _approved_template_case(c)
    to = f"buyer-{uuid.uuid4().hex[:8]}@example.com"
    p = c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to, "subject": "Invoice INV-7: payment reminder", "cover_message": "Hello, a reminder about invoice INV-7."})
    assert p.status_code == 200, p.text
    assert p.json()["subject"] == "Invoice INV-7: payment reminder" and p.json()["cover_message"] == "Hello, a reminder about invoice INV-7."
    sent = c.post(f"/recovery/cases/{cid}/email", json={"confirmation_id": p.json()["confirmation_id"], "acknowledged": True})
    assert sent.status_code == 200, sent.text
    mail = outbox(to=to)[0]
    assert mail["subject"] == "Invoice INV-7: payment reminder"
    assert "Hello, a reminder about invoice INV-7." in str(mail)


def test_email_defaults_stay_when_subject_and_cover_are_left_empty(verified_a):
    c = verified_a
    cid = _approved_template_case(c)
    p = c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": f"b-{uuid.uuid4().hex[:8]}@example.com"})
    assert p.status_code == 200
    assert p.json()["subject"].startswith("Demand notice regarding payment owed to") and p.json()["cover_message"] == ""


def test_a_subject_or_cover_with_threats_law_blanks_or_new_lines_is_refused(verified_a):
    c = verified_a
    cid = _approved_template_case(c)
    to = f"b-{uuid.uuid4().hex[:8]}@example.com"
    for field, text in (
        ("subject", "Pay now or face arrest"),
        ("cover_message", "We will file an FIR if you do not pay"),
        ("cover_message", "This is under Section 138 of the Act"),
        ("subject", "Reminder for [name]"),
        ("cover_message", "This notice has been duly served on you"),
        ("subject", "Line one\nBcc: someone@example.com"),
    ):
        r = c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to, field: text})
        assert r.status_code == 422, (field, text, r.text)


def test_guide_keeps_a_portal_reference_the_person_typed_and_refuses_odd_characters(verified_a):
    c = verified_a
    cid, _ = new_case(c)
    r = c.patch(f"/recovery/cases/{cid}/guide", json={"portal_reference": "MSME/2026/000123"})
    assert r.status_code == 200 and r.json()["guide"]["portal_reference"] == "MSME/2026/000123"
    assert c.patch(f"/recovery/cases/{cid}/guide", json={"portal_reference": "<script>x</script>"}).status_code == 422


# ---- the guided flow's email path: the existing email service, a copy to the seller, the existing rate limits, and the saved status ----
def test_emailing_the_notice_sends_to_the_buyer_with_a_copy_to_the_seller_and_saves_the_status(verified_a):
    c = verified_a
    cid = _approved_template_case(c)
    buyer = f"buyer-{uuid.uuid4().hex[:8]}@example.com"
    seller = c.user["email"]
    p = c.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": buyer}).json()
    assert p["to"] == buyer.lower() and p["sender_copy_to"] == seller.lower()  # the preview says who gets what before anything is sent
    assert c.patch(f"/recovery/cases/{cid}/guide", json={"delivery_method": "emailed"}).status_code == 409  # nothing was sent yet, so it cannot be marked as emailed
    assert c.post(f"/recovery/cases/{cid}/email", json={"confirmation_id": p["confirmation_id"], "acknowledged": True}).status_code == 200
    assert outbox(to=buyer) and any(m["subject"].startswith("Copy:") for m in outbox(to=seller))  # the buyer got the notice; the seller got a copy
    kinds = {e["kind"]: e["status"] for e in c.get(f"/recovery/cases/{cid}/emails").json()}
    assert kinds.get("notice-debtor") != "FAILED" and "notice-copy" in kinds  # both went through the logged email service
    # the status is saved: the guide can mark it emailed now, and a fresh read of the case (what a returning person gets) shows it
    assert c.patch(f"/recovery/cases/{cid}/guide", json={"delivery_method": "emailed"}).status_code == 200
    saved = c.patch(f"/recovery/cases/{cid}/guide", json={"stage": "NOTICE_SENT"}).json()["guide"]
    again = c.get(f"/recovery/cases/{cid}").json()["guide"]
    assert saved["stage"] == again["stage"] == "NOTICE_SENT" and again["delivery_method"] == "emailed" and again["stage_changed_at"]


def test_the_daily_limit_on_mail_to_other_people_really_stops_the_21st_call():
    """The test server lifts this limit so that other tests can send freely, so the real limit is checked here in a child process on its own scratch database."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from pymongo import MongoClient

    backend = Path(__file__).resolve().parent.parent
    scratch = f"vidhi_rate_{uuid.uuid4().hex[:8]}"
    code = """
import asyncio, sys
sys.path.insert(0, sys.argv[1])
from fastapi import HTTPException
from lib.ratelimit import EMAIL_LIMIT

async def go():
    out = []
    for _ in range(22):
        try:
            await EMAIL_LIMIT(user={"id": "u-rate-check"})
            out.append(200)
        except HTTPException as e:
            out.append(e.status_code)
    print(out)

asyncio.run(go())
"""
    env = {k: v for k, v in os.environ.items() if k != "RATE_LIMIT_EMAIL"} | {"DB_NAME": scratch}
    client = MongoClient(os.environ["MONGO_URL"])
    try:
        r = subprocess.run([sys.executable, "-I", "-c", code, str(backend)], capture_output=True, text=True, env=env, cwd=str(backend))
        assert r.returncode == 0, r.stderr
        statuses = eval(r.stdout.strip().splitlines()[-1])  # a list of ints printed by the child
        assert statuses[:20] == [200] * 20 and statuses[20:] == [429, 429], statuses
    finally:
        client.drop_database(scratch)
        client.close()


def test_the_email_path_uses_the_one_email_service_and_the_one_rate_limit_and_the_guide_route_sends_nothing():
    import ast
    from pathlib import Path

    from lib.ratelimit import EMAIL_LIMIT
    from routers.recovery_mail import router as mail_router

    backend = Path(__file__).resolve().parent.parent
    send_routes = [r for r in mail_router.routes if getattr(r, "path", "").endswith("/cases/{case_id}/email") and "POST" in getattr(r, "methods", set())]
    assert len(send_routes) == 1 and any(d.dependency is EMAIL_LIMIT for d in send_routes[0].dependencies)  # the existing daily limit on mail to other people
    mail = ast.parse((backend / "routers" / "recovery_mail.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(mail) if isinstance(n, ast.AsyncFunctionDef) and n.name == "email_notice")
    called = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "send_logged" in called and "send_email" not in called  # every message goes through the logged service (suppression list, email log), never around it
    guide = ast.parse((backend / "routers" / "recovery.py").read_text(encoding="utf-8"))
    set_guide = next(n for n in ast.walk(guide) if isinstance(n, ast.AsyncFunctionDef) and n.name == "set_guide")
    assert not {c.func.id for c in ast.walk(set_guide) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)} & {"send_logged", "send_email", "simple_email"}
