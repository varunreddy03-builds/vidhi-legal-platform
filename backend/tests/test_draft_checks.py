"""Checks before export: each kind of fault is put into a real template draft on purpose and must be flagged; a clean draft raises nothing; nothing is rewritten."""
from datetime import date

import pytest

from lib import draft_checks as dc
from lib import templates as tpl
from tests.conftest import mongo

TODAY = date(2026, 11, 7)
CHEQUE = {"notice_date": "2026-11-05", "sender_name": "Ravi Kumar", "sender_address": "12 Mill Road, Guntur", "recipient_name": "Asha Traders", "recipient_address": "4 Market Street, Vijayawada",
          "debt_description": "Goods supplied in March", "cheque_number": "004512", "cheque_date": "2026-08-01", "cheque_amount": "125000", "drawn_on_bank": "Example Bank, Guntur branch",
          "presented_on": "2026-08-10", "returned_on": "2026-08-12", "return_reason": "Funds insufficient", "payment_period_days": "15"}


@pytest.fixture(scope="module")
def cheque():
    return tpl.get("in-cheque-return-legal-notice")


def good_text(cheque, values=CHEQUE):
    return tpl.render(cheque, values)["text"]


def codes(flags):
    return [f["code"] for f in flags]


def run(cheque, text, values=CHEQUE):
    return dc.check(text, cheque, values, TODAY)


def test_a_clean_template_draft_raises_nothing_except_what_the_template_leaves_open(cheque):
    text = good_text(cheque)
    flags = run(cheque, text)
    assert set(codes(flags)) <= {"open_item"}  # the template's own [LAWYER TO CONFIRM] items and the empty advocate field
    assert all(text[f["start"]:f["end"]].startswith("[") for f in flags)


def test_open_items_are_flagged_with_where_they_are(cheque):
    text = good_text(cheque, {k: v for k, v in CHEQUE.items()})
    flags = [f for f in run(cheque, text) if f["code"] == "open_item"]
    assert len(flags) == 4 and all(f["line"] >= 1 and text[f["start"]:f["end"]].startswith(f["snippet"]) for f in flags)
    text2 = text.replace("Goods supplied in March", "[Reason - to be filled]")
    assert [f["snippet"] for f in run(cheque, text2) if "Reason" in f["snippet"]] == ["[Reason - to be filled]"]


def test_an_unfilled_marker_is_flagged(cheque):
    text = good_text(cheque) + "\nThe sum of {{amount}} is due."
    assert any(f["code"] == "open_item" and "marker" in f["message"] for f in run(cheque, text))


def test_a_party_taken_out_of_the_text_is_flagged(cheque):
    text = good_text(cheque).replace("Asha Traders", "the other side")
    flags = run(cheque, text)
    assert [f["message"] for f in flags if f["code"] == "party_missing"] and "Asha Traders" in [f["message"] for f in flags if f["code"] == "party_missing"][0]


def test_a_name_spelled_another_way_is_flagged_where_it_is_written(cheque):
    text = good_text(cheque).replace("Ravi Kumar", "Ravi Kumar", 1)
    first = text.index("Ravi Kumar")
    text = text[:first] + "Ravi Kumaar" + text[first + len("Ravi Kumar"):]
    flags = [f for f in run(cheque, text) if f["code"] == "name_differs"]
    assert flags and text[flags[0]["start"]:flags[0]["end"]] == "Ravi Kumaar" and "Ravi Kumar" in flags[0]["message"]


def test_a_changed_amount_is_flagged_and_the_missing_answer_too(cheque):
    text = good_text(cheque).replace("Rs 1,25,000", "Rs 1,52,000")
    flags = run(cheque, text)
    assert "amount_unknown" in codes(flags) and "answer_missing" in codes(flags)
    typed = good_text(cheque).replace("Rs 1,25,000", "Rs. 125000")
    assert "amount_unknown" not in codes(run(cheque, typed))  # the same amount written another way is not a fault


def test_a_changed_date_is_flagged(cheque):
    text = good_text(cheque).replace("01 August 2026", "02 August 2026")
    flags = run(cheque, text)
    assert "date_unknown" in codes(flags) and "answer_missing" in codes(flags)


def test_dates_that_do_not_exist_or_are_far_off_are_flagged(cheque):
    text = good_text(cheque) + "\nSigned on 31 February 2026 and again on 05 November 2062 and 3 May 1990."
    by = {f["snippet"]: f["code"] for f in run(cheque, text) if f["code"].startswith("date_")}
    assert by["31 February 2026"] == "date_impossible" and by["05 November 2062"] == "date_year" and by["3 May 1990"] == "date_year"


def test_two_dates_out_of_order_are_flagged_by_the_template_own_order(cheque):
    values = CHEQUE | {"returned_on": "2026-08-05"}  # returned before it was presented
    flags = run(cheque, good_text(cheque, values), values)
    assert [f["message"] for f in flags if f["code"] == "date_order"] and "returned" in flags[0]["message"].lower() + " ".join(f["message"] for f in flags).lower()
    assert "date_order" not in codes(run(cheque, good_text(cheque)))


def test_the_banner_is_skipped_and_other_drafts_get_only_the_checks_that_need_no_answers():
    text = "Agreement dated 31 February 2026, between [Party two - to be filled] and Ravi.\nAmount Rs 5."
    flags = dc.check(text, None, None, TODAY)
    assert sorted(codes(flags)) == ["date_impossible", "open_item"]
    banner = tpl.BANNER_REVIEWED.format(name="A. Advocate", on="2026-01-01")
    assert dc.check(banner + "Plain text.", None, None, TODAY) == []


def test_the_check_never_changes_the_text(cheque):
    text = good_text(cheque).replace("Asha Traders", "x")
    before = text
    run(cheque, text)
    assert text == before
    assert all(set(f) == {"code", "severity", "message", "start", "end", "line", "snippet"} for f in run(cheque, text))


def test_every_template_builds_a_draft_with_no_fault_besides_open_items():
    for t in tpl.load_all():
        values = {}
        for f in t["fields"]:
            values[f["key"]] = {"date": "2026-11-05", "money": "125000", "int": str(max(f.get("min", 1), 1)), "decimal": "12.5", "choice": (f.get("choices") or [""])[0], "textarea": "A sample line"}.get(f["type"], "Sample " + f["key"])
        # a name must look like a name; dates on one day never run backwards
        for f in t["fields"]:
            if f["key"].endswith("_name"):
                values[f["key"]] = "Sample Person" + f["key"].split("_")[0].capitalize()
        flags = dc.check(tpl.render(t, values)["text"], t, values, date(2026, 11, 7))
        assert set(codes(flags)) <= {"open_item"}, (t["id"], flags)


# ---- through the API ----

def make(c, values=None):
    r = c.post("/templates/in-cheque-return-legal-notice/draft", json={"values": values or CHEQUE})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_draft_keeps_its_answers_and_the_check_runs_on_the_text_on_screen(user_a):
    d = make(user_a)
    assert d["template_values"]["sender_name"] == "Ravi Kumar"
    saved = user_a.post(f"/drafts/{d['id']}/check", json={}).json()
    assert saved["from_template"] and saved["counts"]["fix"] == len(saved["flags"]) == 4 and all(f["code"] == "open_item" for f in saved["flags"]) and "legal opinion" in saved["note"]
    on_screen = user_a.post(f"/drafts/{d['id']}/check", json={"body": d["body"].replace("Asha Traders", "someone")}).json()
    assert any(f["code"] == "party_missing" for f in on_screen["flags"]) and on_screen["counts"]["fix"] >= 1
    assert user_a.get(f"/drafts/{d['id']}").json()["body"] == d["body"]  # checking changed nothing
    assert mongo().audit_events.count_documents({"operation": {"$regex": "CHECK"}, "user_id": user_a.user["id"]}) == 0


def test_a_plain_draft_can_be_checked_and_another_organisation_cannot(user_a, user_b, anon):
    plain = user_a.post("/drafts", json={"title": "Plain", "body": "Dated 31 February 2026."}).json()
    assert [f["code"] for f in user_a.post(f"/drafts/{plain['id']}/check", json={}).json()["flags"]] == ["date_impossible"]
    assert user_b.post(f"/drafts/{plain['id']}/check", json={}).status_code == 404
    assert user_b.post(f"/drafts/{make(user_a)['id']}/check", json={"body": "x"}).status_code == 404
    assert anon.post(f"/drafts/{plain['id']}/check", json={}).status_code in (401, 403)
