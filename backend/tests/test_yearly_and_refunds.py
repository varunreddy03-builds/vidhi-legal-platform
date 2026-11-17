"""The yearly plan (offered only when its price is configured) and refunds (recorded by the operator after the money was returned at the provider)."""

import uuid
from datetime import datetime, timedelta, timezone


from routers import payments as pay
from tests.conftest import mongo, outbox, set_plan, mark_stub_paid
from tests.test_admin import admin  # noqa: F401  (fixture)


def checkout(c, package="vidhi_pro_yearly", provider=None):
    set_plan(c, "FREE")
    body = {"package_id": package, "origin_url": "http://localhost:3000", **({"provider": provider} if provider else {})}
    return c.post("/payments/checkout", json=body)


def paid(c, package="vidhi_pro_yearly", provider=None, amount_minor=1999000):
    r = checkout(c, package, provider)
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    sub = "sub_" + uuid.uuid4().hex[:10]
    mongo().subscription_stub.insert_one({"id": sub, "status": "active", "current_period_end": datetime.now(timezone.utc) + timedelta(days=365), "cancel_at_period_end": False})
    mark_stub_paid(sid, amount_total=amount_minor, currency="usd" if provider == "paypal" else "inr", user_id=c.user["id"], subscription_id=sub)
    assert c.get(f"/payments/status/{sid}").json()["payment_status"] == "paid"
    return sid


# ---- yearly ----

def test_the_yearly_plan_is_listed_with_its_own_price_and_interval(user_a):
    pkgs = {p["id"]: p for p in user_a.get("/payments/packages").json()}
    assert pkgs["vidhi_pro"]["interval"] == "month" and pkgs["vidhi_pro_yearly"]["interval"] == "year"
    assert pkgs["vidhi_pro_yearly"]["amount"] == 19990.0 and pkgs["vidhi_pro_yearly"]["prices"]["paypal"] == {"amount": 240.0, "currency": "usd"}
    assert pkgs["vidhi_pro"]["amount"] != pkgs["vidhi_pro_yearly"]["amount"]


def test_a_yearly_checkout_is_priced_by_the_server_and_recorded_as_yearly(user_a):
    r = checkout(user_a, provider="razorpay")
    assert r.status_code == 200, r.text
    row = mongo().payment_transactions.find_one({"session_id": r.json()["session_id"]})
    assert row["amount"] == 19990.0 and row["currency"] == "inr" and row["interval"] == "year" and row["package_id"] == "vidhi_pro_yearly"
    p = checkout(user_a, provider="paypal")
    prow = mongo().payment_transactions.find_one({"session_id": p.json()["session_id"]})
    assert prow["amount"] == 240.0 and prow["currency"] == "usd" and prow["interval"] == "year"
    m = checkout(user_a, package="vidhi_pro")
    assert mongo().payment_transactions.find_one({"session_id": m.json()["session_id"]})["interval"] == "month"
    assert checkout(user_a, package="vidhi_pro_forever").status_code == 400


def test_a_yearly_payment_unlocks_pro_and_the_receipt_says_it_renews_every_year(user_a):
    sid = paid(user_a, provider="razorpay")
    assert mongo().users.find_one({"id": user_a.user["id"]})["plan"] == "PRO"
    mail = outbox(to=user_a.user["email"], subject_has="Pro receipt")[-1]
    assert "renews every year" in mail["html"] and "every month" not in mail["html"]
    assert mongo().payment_transactions.find_one({"session_id": sid})["package_id"] == "vidhi_pro_yearly"


def test_a_monthly_receipt_still_says_month(user_a):
    paid(user_a, package="vidhi_pro", amount_minor=199900)
    assert "renews every month" in outbox(to=user_a.user["email"], subject_has="Pro receipt")[-1]["html"]


def test_no_yearly_price_means_no_yearly_plan_through_that_provider(monkeypatch):
    assert pay.price_for("razorpay", "vidhi_pro_yearly") == (19990.0, "inr")
    monkeypatch.delenv("PRO_PRICE_USD_YEARLY")
    assert pay.price_for("paypal", "vidhi_pro_yearly") is None  # PayPal has no yearly price set: not offered, never guessed
    assert pay.price_for("paypal", "vidhi_pro") == (24.0, "usd")
    assert pay.interval_word("vidhi_pro_yearly") == "year" and pay.interval_word("vidhi_pro") == "month" and pay.interval_word(None) == "month"


# ---- refunds ----

def refund(admin_c, sid, **over):
    body = {"reason": "Customer asked within the week", "returned_through_provider": True, **over}
    return admin_c.post(f"/admin/payments/{sid}/refund", json=body)


def test_only_the_operator_can_list_or_record_refunds(user_a, anon):
    sid = paid(user_a, provider="razorpay")
    assert user_a.get("/admin/payments").status_code == 404 and user_a.post(f"/admin/payments/{sid}/refund", json={"reason": "x" * 6, "returned_through_provider": True}).status_code == 404
    assert anon.get("/admin/payments").status_code in (401, 403)


def test_the_operator_finds_a_payment_and_records_a_partial_then_the_remaining_refund(user_a, admin):  # noqa: F811
    sid = paid(user_a, provider="razorpay")
    found = admin.get("/admin/payments", params={"q": user_a.user["email"]}).json()
    assert [r["session_id"] for r in found] == [sid] and found[0]["email"] == user_a.user["email"] and found[0]["refunded_amount"] == 0
    first = refund(admin, sid, amount=5000)
    assert first.status_code == 200 and first.json()["refunded_total"] == 5000.0 and first.json()["fully_refunded"] is False and first.json()["customer_told"] is True
    assert "cancel it there too" in first.json()["reminder"]
    assert refund(admin, sid, amount=15000).status_code == 409  # more than is left (19990 - 5000 = 14990)
    rest = refund(admin, sid)  # everything not yet refunded
    assert rest.status_code == 200 and rest.json()["refunded_total"] == 19990.0 and rest.json()["fully_refunded"] is True
    assert refund(admin, sid, amount=1).status_code == 409
    row = mongo().payment_transactions.find_one({"session_id": sid})
    assert row["refunded_amount"] == 19990.0 and row["refund_status"] == "full"
    assert [r["amount"] for r in mongo().refunds.find({"session_id": sid}).sort("created_at", 1)] == [5000.0, 14990.0]
    assert mongo().users.find_one({"id": user_a.user["id"]})["plan"] == "PRO"  # a refund alone does not change the plan
    assert any(e["operation"] == "ADMIN_REFUND_RECORDED" for e in mongo().audit_events.find({"user_email": admin.user["email"]}))


def test_the_customer_is_told_in_plain_words_without_any_tax_talk(user_a, admin):  # noqa: F811
    sid = paid(user_a, provider="razorpay")
    refund(admin, sid, amount=2500)
    mail = outbox(to=user_a.user["email"], subject_has="Your VIDHI refund")[-1]
    assert "Rs 2,500.00" in mail["html"] and sid[-8:] in mail["html"] and "several working days" in mail["html"]
    assert not any(w in mail["html"].lower() for w in ("gst", "tax", "invoice number"))
    before = len(outbox(to=user_a.user["email"], subject_has="Your VIDHI refund"))
    refund(admin, sid, amount=100, tell_customer=False)
    assert len(outbox(to=user_a.user["email"], subject_has="Your VIDHI refund")) == before


def test_a_refund_needs_the_confirmation_a_paid_payment_and_a_reason(user_a, admin):  # noqa: F811
    sid = paid(user_a, provider="razorpay")
    assert refund(admin, sid, returned_through_provider=False).status_code == 422  # VIDHI does not move money: confirm it was returned first
    assert refund(admin, sid, reason="no").status_code == 422
    assert refund(admin, sid, amount=0).status_code == 422 and refund(admin, sid, amount=-5).status_code == 422
    assert refund(admin, "no-such-payment").status_code == 404
    unpaid = checkout(user_a).json()["session_id"]
    assert refund(admin, unpaid).status_code == 409  # never paid
    assert mongo().refunds.count_documents({"session_id": {"$in": [sid, unpaid]}}) == 0


def test_ending_pro_now_moves_the_organisation_to_free(user_a, admin):  # noqa: F811
    sid = paid(user_a, provider="razorpay")
    r = refund(admin, sid, end_pro_now=True)
    assert r.status_code == 200 and r.json()["pro_ended"] is True
    row = mongo().users.find_one({"id": user_a.user["id"]})
    assert row["plan"] == "FREE" and row["subscription_status"] == "refunded"
    assert user_a.get("/auth/entitlement").json()["tier"] == "free"


def test_two_refunds_at_once_cannot_both_take_the_same_money(user_a, admin):  # noqa: F811
    import concurrent.futures

    sid = paid(user_a, provider="razorpay")
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(refund, admin, sid, amount=19990) for _ in range(4)])
    assert codes.count(200) == 1 and codes.count(409) == 3
    assert mongo().payment_transactions.find_one({"session_id": sid})["refunded_amount"] == 19990.0

# ---- regional price structure ----

def test_the_price_table_shows_what_is_configured_and_which_countries_are_open(admin):  # noqa: F811
    r = admin.get("/admin/pricing").json()
    rows = {x["country"]: x for x in r["rows"]}
    assert set(rows) == {"IN", "AE", "UK", "US", "SG"} and "No tax or GST" in r["tax"]
    assert rows["IN"]["open_for_sale"] is True and rows["IN"]["currency"] == "INR" and rows["IN"]["yearly_set"] is True
    for code, ccy in (("AE", "AED"), ("UK", "GBP"), ("US", "USD"), ("SG", "SGD")):
        assert rows[code]["currency"] == ccy and rows[code]["open_for_sale"] is False and rows[code]["country_status"] == "planned" and "Not live" in rows[code]["note"]
    assert rows["AE"]["payment_code_reads_these"] is False and rows["US"]["payment_code_reads_these"] is True


def test_no_price_is_hardcoded_for_a_country_that_is_not_live():
    import re
    from pathlib import Path

    from lib import pricing

    assert all(ccy in pricing.PRICE_ENV for ccy in ("INR", "USD", "AED", "GBP", "SGD"))
    text = (Path(pricing.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"(?<![A-Z_])\d{3,}(?:\.\d+)?", text.split('"""', 2)[2])  # no price-looking number in the module's code