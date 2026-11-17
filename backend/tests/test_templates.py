"""Document templates: contents stay free of invented law, answers fill them in safely, the review gate holds, and the API creates editable drafts."""

import json
import os
import re
import shutil
import subprocess
import sys
from decimal import Decimal

import pytest

from lib import templates as tpl
from tests.conftest import mongo, new_matter

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "template_review.py")
BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED = {"in-residential-rent-agreement", "in-loan-agreement", "in-nda", "in-cheque-return-legal-notice", "in-employment-letter"}
# Anything that looks like a citation of law. The templates must leave law to the lawyer: [LAWYER TO CONFIRM: ...].
LAW_LOOKING = re.compile(r"(\bsections?\s+\d|\bsec\.\s*\d|\bu/s\b|\barticle\s+\d|\b(?:Act|Code|Rules?|Ordinance)\s*,?\s*(?:of\s+)?\d{4}\b|\bN\.?I\.?\s*Act\b|\bBNS\b|\bIPC\b|\bCrPC\b)", re.I)
NAMED_STATUTE = re.compile(r"(Negotiable Instruments|Indian Contract|Stamp Act|Registration Act|Transfer of Property|Rent Control|Companies Act|Industrial Disputes|Payment of Gratuity|Provident Fund|Employees' State)", re.I)
UNKIND = re.compile(r"\b(lied|liar|lying|dishonest|perjur\w*|cheat\w*|fraud\w*|swindl\w*|criminal)\b", re.I)


def all_text(t: dict) -> str:
    return " ".join([t["title"], t["description"], t["body"], *[c["text"] + c["label"] for c in t.get("clauses", [])], *t.get("lawyer_checks", []), *[f["label"] + f.get("help", "") for f in t["fields"]]])


def sample(t: dict) -> dict:
    out = {}
    for f in t["fields"]:
        k = f["type"]
        out[f["key"]] = {"date": "2026-11-05", "money": "125000", "int": str(f.get("min", 1) if f.get("min", 1) > 0 else 1), "decimal": "12.5", "choice": (f.get("choices") or [""])[0], "textarea": "Line one of a sample text"}.get(k, "Sample " + f["key"])
    return out


TEMPLATES = tpl.load_all()


def test_the_five_templates_exist_for_india_and_none_counts_as_reviewed():
    assert {t["id"] for t in TEMPLATES} == EXPECTED
    for t in TEMPLATES:
        assert t["jurisdiction"] == "IN" and t["language"] == "en"
        assert t["review"]["status"] == tpl.UNREVIEWED and t["review"]["reviewed"] is False and t["review"]["reviewed_by"] is None
        assert len(t["lawyer_checks"]) >= 4 and "[LAWYER TO CONFIRM:" in t["body"] + "".join(c["text"] for c in t.get("clauses", []))


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["id"])
def test_templates_contain_no_citation_of_law_and_no_unkind_wording(t):
    text = all_text(t)
    assert not LAW_LOOKING.search(text), LAW_LOOKING.search(text).group(0)
    assert not NAMED_STATUTE.search(text), NAMED_STATUTE.search(text).group(0)
    assert not UNKIND.search(text), UNKIND.search(text).group(0)


@pytest.mark.parametrize("t", TEMPLATES, ids=lambda t: t["id"])
def test_every_template_renders_from_sample_answers_with_a_clear_warning_and_open_items(t):
    out = tpl.render(t, sample(t), [c["id"] for c in t.get("clauses", [])])  # every optional clause switched on
    text = out["text"]
    assert text.startswith("DRAFT FROM A TEMPLATE - NOT REVIEWED BY A LAWYER.") and "{{" not in text and "}}" not in text and "None" not in text
    assert out["open_placeholders"] and all(p.startswith("[LAWYER TO CONFIRM:") or p.endswith("to be filled]") for p in out["open_placeholders"])
    assert "Sample" in text or "Line one" in text


def test_money_is_written_with_indian_grouping():
    assert tpl.inr(Decimal("125000")) == "Rs 1,25,000"
    assert tpl.inr(Decimal("25000")) == "Rs 25,000" and tpl.inr(Decimal("100")) == "Rs 100" and tpl.inr(Decimal("0")) == "Rs 0"
    assert tpl.inr(Decimal("123456789.5")) == "Rs 12,34,56,789.50" and tpl.inr(Decimal("1000")) == "Rs 1,000"


def test_answers_are_inserted_as_plain_text_and_never_expanded_again():
    t = tpl.get("in-residential-rent-agreement")
    v = sample(t) | {"landlord_name": "{{tenant_name}} {{clause:lock_in}} \x00\x07Owner"}
    text = tpl.render(t, v, [])["text"]
    assert "{{tenant_name}} {{clause:lock_in}} Owner" in text  # shown literally, control characters removed, not expanded
    assert "Lock-in period" not in text


def test_missing_wrong_and_unknown_answers_are_refused_in_plain_words():
    t = tpl.get("in-loan-agreement")
    good = sample(t)
    with pytest.raises(ValueError, match="Please fill in: .*Amount of the loan"):
        tpl.render(t, {k: v for k, v in good.items() if k != "principal"})
    for key, bad, msg in (("disbursed_on", "5 Nov", "date"), ("principal", "lots", "amount"), ("principal", "-5", "range"), ("cure_days", "0", "between"), ("cure_days", "x", "whole number"),
                          ("repayment_mode", "whenever", "one of"), ("interest_rate", "1.234", "two decimals"), ("lender_name", "x" * 201, "too long")):
        with pytest.raises(ValueError, match=msg):
            tpl.render(t, good | {key: bad})
    with pytest.raises(ValueError, match="Unknown answer"):
        tpl.render(t, good | {"surprise": "x"})
    with pytest.raises(ValueError, match="Unknown clause"):
        tpl.render(t, good, ["no_such_clause"])


def test_optional_clauses_follow_defaults_or_the_choice_and_flag_missing_values():
    t = tpl.get("in-residential-rent-agreement")
    v = {k: x for k, x in sample(t).items() if k not in ("lock_in_months", "escalation_percent", "property_description")}
    default = tpl.render(t, v)
    assert "sub-let" in default["text"] and "Lock-in period" not in default["text"] and set(default["clauses_used"]) == {"no_subletting", "utilities_tenant", "entry_inspection"}
    none = tpl.render(t, v, [])
    assert "sub-let" not in none["text"] and none["clauses_used"] == []
    on = tpl.render(t, v, ["lock_in"])
    assert "Lock-in period" in on["text"] and "[Lock-in period (months) - to be filled]" in on["open_placeholders"]
    assert "  (the" not in default["text"]  # an empty optional answer leaves no double space


def test_a_listing_for_a_country_that_is_not_covered_says_so_and_offers_nothing():
    uae = tpl.listing("AE")
    assert uae["items"] == [] and "does not cover United Arab Emirates law" in uae["note"]
    assert len(tpl.listing("IN")["items"]) == 5 and tpl.listing("IN")["note"] is None


# ---- the review gate ----

@pytest.fixture
def copy_dir(tmp_path, monkeypatch):
    dest = tmp_path / "templates"
    shutil.copytree(tpl.templates_dir(), dest)
    monkeypatch.setenv("TEMPLATES_DIR", str(dest))
    return dest


def approve(tid, reviewer="Adv Test Reviewer", on="2026-11-20"):
    return subprocess.run([sys.executable, "-I", SCRIPT, "approve", "--id", tid, "--reviewer", reviewer, "--on", on], capture_output=True, text=True, cwd=BACKEND, env=os.environ.copy())


def test_a_lawyer_approval_moves_the_template_and_it_then_reads_as_reviewed(copy_dir):
    r = approve("in-nda")
    assert r.returncode == 0, r.stderr
    assert not (copy_dir / "pending" / "in-nda.json").exists() and (copy_dir / "IN" / "in-nda.json").exists()
    t = tpl.get("in-nda")
    assert t["review"] == {"status": tpl.REVIEWED, "reviewed": True, "reviewed_by": "Adv Test Reviewer", "reviewed_on": "2026-11-20", "note": None}
    text = tpl.render(t, sample(t))["text"]
    assert text.startswith("DRAFT FROM A TEMPLATE. The template text was reviewed by Adv Test Reviewer on 2026-11-20") and "NOT REVIEWED" not in text
    assert tpl.get("in-loan-agreement")["review"]["reviewed"] is False  # the others are untouched


def test_editing_after_review_sends_the_template_back_to_unreviewed(copy_dir):
    assert approve("in-nda").returncode == 0
    path = copy_dir / "IN" / "in-nda.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["body"] = data["body"].replace("secret", "very secret")
    path.write_text(json.dumps(data), encoding="utf-8")
    t = tpl.get("in-nda")
    assert t["review"]["reviewed"] is False and t["review"]["reviewed_by"] is None and "changed after its review" in t["review"]["note"]
    assert tpl.render(t, sample(t))["text"].startswith("DRAFT FROM A TEMPLATE - NOT REVIEWED")


def test_a_file_that_claims_a_review_inside_pending_or_without_a_matching_hash_is_not_trusted(copy_dir):
    p = copy_dir / "pending" / "in-nda.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d.update({"reviewed_by": "Someone Senior", "reviewed_on": "2026-01-01", "content_sha256": tpl.content_hash(d)})
    p.write_text(json.dumps(d), encoding="utf-8")
    assert tpl.get("in-nda")["review"]["reviewed"] is False  # pending/ is never reviewed, whatever the file says
    (copy_dir / "IN").mkdir(exist_ok=True)
    shutil.move(str(p), str(copy_dir / "IN" / "in-nda.json"))
    d["content_sha256"] = "0" * 64
    (copy_dir / "IN" / "in-nda.json").write_text(json.dumps(d), encoding="utf-8")
    assert tpl.get("in-nda")["review"]["reviewed"] is False


def test_broken_duplicate_and_unsupported_templates_are_skipped_or_refused(copy_dir):
    (copy_dir / "pending" / "broken.json").write_text("{not json", encoding="utf-8")
    d = json.loads((copy_dir / "pending" / "in-nda.json").read_text(encoding="utf-8"))
    (copy_dir / "pending" / "typo.json").write_text(json.dumps(d | {"id": "typo", "body": d["body"] + " {{no_such_field}}"}), encoding="utf-8")
    (copy_dir / "pending" / "copy.json").write_text(json.dumps(d), encoding="utf-8")  # same id as in-nda
    assert {t["id"] for t in tpl.load_all()} == EXPECTED
    (copy_dir / "pending" / "ae-nda.json").write_text(json.dumps(d | {"id": "ae-nda", "jurisdiction": "AE"}), encoding="utf-8")
    r = approve("ae-nda")
    assert r.returncode == 1 and "not a supported country" in r.stderr
    assert approve("in-nda", reviewer="X").returncode == 1 and approve("in-nda", on="soon").returncode == 1 and approve("nope").returncode == 1


# ---- the API ----

def answers(template_id: str, c) -> dict:
    return sample(c.get(f"/templates/{template_id}").json())


def test_templates_are_listed_and_readable_with_their_status(user_a):
    listing = user_a.get("/templates?jurisdiction=IN").json()
    assert {x["id"] for x in listing["items"]} == EXPECTED and all(x["review"]["status"] == tpl.UNREVIEWED for x in listing["items"])
    assert user_a.get("/templates?jurisdiction=AE").json()["items"] == [] and user_a.get("/templates?jurisdiction=ZZ").status_code == 422
    one = user_a.get("/templates/in-nda").json()
    assert one["fields"] and one["clauses"] and one["lawyer_checks"] and "No lawyer has reviewed this template yet" in one["notice"]
    assert user_a.get("/templates/nope").status_code == 404


def test_a_draft_is_created_from_answers_and_stays_editable(user_a):
    r = user_a.post("/templates/in-loan-agreement/draft", json={"values": answers("in-loan-agreement", user_a)})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["template_id"] == "in-loan-agreement" and d["template_review"]["reviewed"] is False
    assert d["body"].startswith("DRAFT FROM A TEMPLATE - NOT REVIEWED BY A LAWYER.") and "LOAN AGREEMENT" in d["body"]
    edited = user_a.patch(f"/drafts/{d['id']}", json={"body": d["body"] + "\nExtra line"}).json()
    assert edited["version"] == 2 and edited["body"].endswith("Extra line") and edited["template_id"] == "in-loan-agreement"
    assert d["id"] in [x["id"] for x in user_a.get("/drafts").json()]
    ops = [e["detail"] for e in mongo().audit_events.find({"operation": "TEMPLATE_DRAFT_CREATED", "user_id": user_a.user["id"]})]
    assert any(o.startswith("in-loan-agreement v1 (UNVERIFIED") for o in ops)


def test_bad_answers_unknown_templates_and_other_organisations_matters_are_refused(user_a, user_b):
    ok = answers("in-nda", user_a)
    assert user_a.post("/templates/in-nda/draft", json={"values": {}}).status_code == 422
    assert "Please fill in" in user_a.post("/templates/in-nda/draft", json={"values": {}}).json()["detail"]
    assert user_a.post("/templates/in-nda/draft", json={"values": ok | {"agreement_date": "yesterday"}}).status_code == 422
    assert user_a.post("/templates/nope/draft", json={"values": ok}).status_code == 404
    mid, _ = new_matter(user_a)
    assert user_b.post("/templates/in-nda/draft", json={"values": ok, "matter_id": mid}).status_code == 404
    assert user_a.post("/templates/in-nda/draft", json={"values": ok, "matter_id": mid}).json()["matter_id"] == mid
    mongo().matters.update_one({"id": mid}, {"$set": {"jurisdiction_id": "UK"}})
    wrong = user_a.post("/templates/in-nda/draft", json={"values": ok, "matter_id": mid})
    assert wrong.status_code == 422 and "different country" in wrong.json()["detail"]


def test_templates_need_a_signed_in_user(anon):
    assert anon.get("/templates").status_code == 401 and anon.post("/templates/in-nda/draft", json={"values": {}}).status_code == 401