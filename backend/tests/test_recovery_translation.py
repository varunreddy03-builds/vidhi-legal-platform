"""Courtesy translations: code protects figures and names; nothing is sent in another language without approval."""

import uuid


from lib.translation import lift_blocks, preservation_check, restore_blocks
from tests.conftest import mongo, new_member, outbox, stub, verify_email
from tests.test_recovery_stage1 import new_case
from tests.test_recovery_stage2 import approve

ENGLISH = (
    "Date: 19 Oct 2026\nTo: Debtor X\n\n1. Invoice INV-17 for goods remains unpaid.\n\nStatement of account\n"
    "  + Invoice amount (invoice INV-17): 40,000.00 INR\n  = Balance due: 40,000.00 INR\n\n"
    "Please pay within 15 days.\n\nEnclosures\n  No documents are enclosed with this notice.\n\nYours faithfully, A Traders\n"
)


# ---------------------------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------------------------
def test_figures_blocks_are_lifted_out_and_put_back_unchanged():
    text, kept = lift_blocks(ENGLISH)
    assert "40,000.00" not in text and "{{STATEMENT}}" in text and "{{ENCLOSURES}}" in text
    assert "= Balance due: 40,000.00 INR" in kept["{{STATEMENT}}"]
    back = restore_blocks("अनुवाद\n{{STATEMENT}}\nपाठ\n{{ENCLOSURES}}\n", kept)
    assert "= Balance due: 40,000.00 INR" in back and "No documents are enclosed" in back
    dropped = restore_blocks("सिर्फ पाठ", kept)  # a model that drops the markers cannot make the figures vanish
    assert "Balance due: 40,000.00 INR" in dropped


def test_the_preservation_check_flags_changed_numbers_and_names():
    good = "दिनांक 19 Oct 2026\nDebtor X को\nINV-17 के लिए 15 दिन\n40,000.00 INR 40,000"
    assert preservation_check(ENGLISH, good, ["A Traders", "Debtor X", "INV-17"])["missing_names"] == ["A Traders"]
    bad = preservation_check("Pay 40,000 within 15 days to A Traders", "१५ दिन में 4,000 दें", ["A Traders"])
    assert not bad["ok"] and "40,000" in bad["missing_numbers"] and "15" in bad["missing_numbers"] and bad["missing_names"] == ["A Traders"]
    assert preservation_check("Pay 40,000 to A Traders", "A Traders को 40,000 दें", ["A Traders"])["ok"]
    assert not preservation_check("x 1", "", [])["ok"]


# ---------------------------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------------------------
def make_notice(c, debtor_suffix=""):
    """A case whose current notice is a known English text with an approved version."""
    cid, debtor = new_case(c, debtor=f"Debtor X{uuid.uuid4().hex[:6]}")
    c.patch(f"/recovery/cases/{cid}/intake", json={"invoice_number": "INV-17"})
    stub("generic", {"notice": f"To: {debtor}\n\n{{{{STATEMENT}}}}\n\nPlease pay within 15 days.\n\n{{{{ENCLOSURES}}}}\n\nYours faithfully, A Traders"}, contains=debtor)
    assert c.post(f"/recovery/cases/{cid}/notice").status_code == 200
    return cid, debtor


def good_translation(c, cid):
    english = c.get(f"/recovery/cases/{cid}").json()["notice_body"]
    return english  # the stub below translates by wrapping the English so every figure and name survives


def translate(c, cid, debtor, lang="hi", reply=None):
    english = c.get(f"/recovery/cases/{cid}").json()["notice_body"]
    text, _ = lift_blocks(english)
    stub("translate", {"translation": reply if reply is not None else "नमस्ते\n" + text.replace("Please pay within 15 days.", "कृपया 15 दिन के भीतर भुगतान करें।")}, contains=debtor)
    return c.post(f"/recovery/cases/{cid}/notice/translate", json={"language": lang})


def test_a_translation_keeps_the_statement_in_english_and_passes_the_checks(user_a):
    cid, debtor = make_notice(user_a)
    r = translate(user_a, cid, debtor)
    assert r.status_code == 200, r.text
    t = r.json()
    english = user_a.get(f"/recovery/cases/{cid}").json()["notice_body"]
    assert "= Balance due: 40,000.00 INR" in t["body"] and "कृपया 15 दिन" in t["body"]
    assert t["language_name"] == "Hindi" and t["checks"]["ok"] and not t["stale"] and not t["usable"] and t["approved"] is None
    assert t["body"].count("Balance due") == english.count("Balance due")


def test_the_prompt_forbids_changing_figures_and_adding_threats(user_a):
    from tests.conftest import ai_prompts

    cid, debtor = make_notice(user_a)
    translate(user_a, cid, debtor)
    prompt = ai_prompts(debtor, "translate")[-1]
    for needle in ("ordinary digits 0-9", "{{STATEMENT}}", "Do not add any law", "exactly as written in English letters"):
        assert needle in prompt
    assert "40,000.00" not in prompt  # the figures never reach the model for translation


def test_a_translation_that_changes_a_number_or_name_is_flagged_and_cannot_be_approved(user_a):
    cid, debtor = make_notice(user_a)
    bad = translate(user_a, cid, debtor, reply="नमस्ते\n{{STATEMENT}}\nकृपया 51 दिन में भुगतान करें।\n{{ENCLOSURES}}")
    t = bad.json()
    assert not t["checks"]["ok"] and "15" in t["checks"]["missing_numbers"]
    r = user_a.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={"acknowledged": True})
    assert r.status_code == 409 and "must not change" in r.json()["detail"]


def test_unknown_languages_and_missing_notices_are_refused(user_a):
    cid, debtor = make_notice(user_a)
    assert user_a.post(f"/recovery/cases/{cid}/notice/translate", json={"language": "xx"}).status_code == 422
    empty, _ = new_case(user_a)
    assert user_a.post(f"/recovery/cases/{empty}/notice/translate", json={"language": "hi"}).status_code == 409


def test_all_22_scheduled_languages_are_offered_and_english_is_not(user_a):
    cid, _ = make_notice(user_a)
    offered = {x["code"] for x in user_a.get(f"/recovery/cases/{cid}/notice/translations").json()["languages"]}
    assert len(offered) == 22 and "en" not in offered
    assert {"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "ur", "or", "as", "ne", "sa", "mai", "kok", "doi", "brx", "ks", "mni", "sat", "sd"} == offered


def test_a_translation_goes_stale_when_the_english_changes(user_a):
    cid, debtor = make_notice(user_a)
    t = translate(user_a, cid, debtor).json()
    english = user_a.get(f"/recovery/cases/{cid}").json()["notice_body"]
    user_a.patch(f"/recovery/cases/{cid}/notice", json={"notice_body": english + "\nExtra sentence added."})
    listed = user_a.get(f"/recovery/cases/{cid}/notice/translations").json()
    assert listed["translations"][0]["stale"] and not listed["translations"][0]["usable"]
    assert user_a.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={"acknowledged": True}).status_code == 409


def test_editing_a_translation_reruns_the_checks_and_clears_the_approval(user_a):
    cid, debtor = make_notice(user_a)
    t = translate(user_a, cid, debtor).json()
    assert user_a.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={}).status_code == 422
    ok = user_a.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={"acknowledged": True})
    assert ok.status_code == 200
    assert user_a.get(f"/recovery/cases/{cid}/notice/translations").json()["translations"][0]["usable"]
    edited = user_a.patch(f"/recovery/cases/{cid}/notice/translations/{t['id']}", json={"body": t["body"] + "\nएक और पंक्ति"}).json()
    assert edited["edited"] and edited["approved"] is None and not edited["usable"]
    broken = user_a.patch(f"/recovery/cases/{cid}/notice/translations/{t['id']}", json={"body": "बिना किसी संख्या के एक छोटा सा पाठ जो सब कुछ बदल देता है"}).json()
    assert not broken["checks"]["ok"]


def test_a_translation_is_emailed_only_when_approved_and_sits_under_the_english_notice(verified_a):
    cid, debtor = make_notice(verified_a)
    approve(verified_a, cid)
    t = translate(verified_a, cid, debtor).json()
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    unapproved = verified_a.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to, "translation_id": t["id"]})
    assert unapproved.status_code == 409 and "Approve the translation" in unapproved.json()["detail"]
    verified_a.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={"acknowledged": True})
    prep = verified_a.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to, "translation_id": t["id"]})
    assert prep.status_code == 200 and prep.json()["translation"]["language_name"] == "Hindi"
    sent = verified_a.post(f"/recovery/cases/{cid}/email", json={"confirmation_id": prep.json()["confirmation_id"], "acknowledged": True})
    assert sent.status_code == 200
    html = outbox(to=to)[-1]["html"]
    assert html.index("Please pay within 15 days.") < html.index("कृपया 15 दिन") and "authoritative" in html
    assert "अंग्रेज़ी नोटिस ही प्रामाणिक" in html  # the courtesy line in the recipient's language


def test_an_english_only_send_is_unchanged(verified_a):
    cid, debtor = make_notice(verified_a)
    approve(verified_a, cid)
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    prep = verified_a.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to})
    assert prep.status_code == 200 and prep.json()["translation"] is None
    verified_a.post(f"/recovery/cases/{cid}/email", json={"confirmation_id": prep.json()["confirmation_id"], "acknowledged": True})
    assert "Translation" not in outbox(to=to)[-1]["html"]


def test_a_translation_edited_after_the_preview_cannot_be_sent(verified_a):
    cid, debtor = make_notice(verified_a)
    approve(verified_a, cid)
    t = translate(verified_a, cid, debtor).json()
    verified_a.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={"acknowledged": True})
    to = f"cust-{uuid.uuid4().hex[:8]}@example.com"
    prep = verified_a.post(f"/recovery/cases/{cid}/email/prepare", json={"debtor_email": to, "translation_id": t["id"]}).json()
    verified_a.patch(f"/recovery/cases/{cid}/notice/translations/{t['id']}", json={"body": t["body"] + "\nबाद में जोड़ा गया।"})
    r = verified_a.post(f"/recovery/cases/{cid}/email", json={"confirmation_id": prep["confirmation_id"], "acknowledged": True})
    assert r.status_code == 409 and outbox(to=to) == []


def test_roles_and_privacy(user_a, user_b):
    verify_email(user_a)
    cid, debtor = make_notice(user_a)
    t = translate(user_a, cid, debtor).json()
    member = new_member(user_a, "MEMBER")
    assert member.post(f"/recovery/cases/{cid}/notice/translate", json={"language": "hi"}).status_code == 403  # AI use
    assert member.post(f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", json={"acknowledged": True}).status_code == 403
    assert member.get(f"/recovery/cases/{cid}/notice/translations").status_code == 200
    for method, path, kw in (
        ("get", f"/recovery/cases/{cid}/notice/translations", {}),
        ("post", f"/recovery/cases/{cid}/notice/translate", {"json": {"language": "hi"}}),
        ("post", f"/recovery/cases/{cid}/notice/translations/{t['id']}/approve", {"json": {"acknowledged": True}}),
        ("patch", f"/recovery/cases/{cid}/notice/translations/{t['id']}", {"json": {"body": "x" * 30}}),
    ):
        assert getattr(user_b, method)(path, **kw).status_code == 404, path


def test_deleting_the_case_deletes_its_translations(user_a):
    cid, debtor = make_notice(user_a)
    translate(user_a, cid, debtor)
    db = mongo()
    assert db.notice_translations.count_documents({"case_id": cid}) == 1
    user_a.delete(f"/recovery/cases/{cid}")
    assert db.notice_translations.count_documents({"case_id": cid}) == 0


# ---- security audit SA8: the checks must work in the languages a notice is translated into, not only English ----
CLEAN = {  # an honest translation of "Pay 40,000.00 INR within 15 days of receiving this notice."
    "hi": "इस नोटिस को प्राप्त करने के 15 दिनों के भीतर 40,000.00 INR का भुगतान करें।",
    "mr": "ही नोटीस मिळाल्यापासून 15 दिवसांत 40,000.00 INR भरा.",
    "te": "ఈ నోటీసు అందిన 15 రోజుల్లో 40,000.00 INR చెల్లించండి.",
    "ta": "இந்த அறிவிப்பைப் பெற்ற 15 நாட்களுக்குள் 40,000.00 INR செலுத்தவும்.",
    "bn": "এই নোটিস পাওয়ার 15 দিনের মধ্যে 40,000.00 INR দিন।",
    "gu": "આ નોટિસ મળ્યાના 15 દિવસમાં 40,000.00 INR ચૂકવો.",
}
ALTERED = {  # the same, with something added that the English notice does not say: (language, text, what must be caught)
    "hi legal": ("hi", "इस नोटिस को प्राप्त करने के 15 दिनों के भीतर 40,000.00 INR का भुगतान करें, अन्यथा धारा 138 के अंतर्गत कार्रवाई होगी।", "legal"),
    "hi legal digits": ("hi", "इस नोटिस को प्राप्त करने के 15 दिनों के भीतर 40,000.00 INR का भुगतान करें, अन्यथा धारा १३८ के अंतर्गत कार्रवाई होगी।", "legal"),
    "te legal": ("te", "ఈ నోటీసు అందిన 15 రోజుల్లో 40,000.00 INR చెల్లించండి, లేకపోతే సెక్షన్ 138 కింద చర్య.", "legal"),
    "ta legal": ("ta", "இந்த அறிவிப்பைப் பெற்ற 15 நாட்களுக்குள் 40,000.00 INR செலுத்தவும், இல்லையெனில் பிரிவு 138 இன் கீழ் நடவடிக்கை.", "legal"),
    "hi served": ("hi", "यह नोटिस आपको तामील हो चुका है। 15 दिनों के भीतर 40,000.00 INR का भुगतान करें।", "service"),
    "hi deemed": ("hi", "यह नोटिस प्राप्त माना जाएगा। 15 दिनों के भीतर 40,000.00 INR का भुगतान करें।", "service"),
    "mr served": ("mr", "ही नोटीस बजावण्यात आली आहे. 15 दिवसांत 40,000.00 INR भरा.", "service"),
    "te deemed": ("te", "ఈ నోటీసు అందినట్లుగా భావించబడుతుంది. 15 రోజుల్లో 40,000.00 INR చెల్లించండి.", "service"),
    "ta deemed": ("ta", "இந்த அறிவிப்பு பெறப்பட்டதாகக் கருதப்படும். 15 நாட்களுக்குள் 40,000.00 INR செலுத்தவும்.", "service"),
    "bn served": ("bn", "এই নোটিস জারি করা হয়েছে। 15 দিনের মধ্যে 40,000.00 INR দিন।", "service"),
    "gu served": ("gu", "આ નોટિસ બજાવવામાં આવી છે. 15 દિવસમાં 40,000.00 INR ચૂકવો.", "service"),
    "hi risky": ("hi", "15 दिनों में 40,000.00 INR दें, अन्यथा आपको गिरफ्तार किया जाएगा।", "threat"),
    "te risky": ("te", "15 రోజుల్లో 40,000.00 INR చెల్లించండి, లేకపోతే మిమ్మల్ని అరెస్టు చేస్తారు.", "threat"),
    "ta risky": ("ta", "15 நாட்களில் 40,000.00 INR செலுத்தவும், இல்லையெனில் கைது செய்யப்படுவீர்கள்.", "threat"),
}
EN_ONE = "Pay 40,000.00 INR within 15 days of receiving this notice."


def test_an_honest_translation_in_each_language_is_not_flagged():
    for lang, text in CLEAN.items():
        out = preservation_check(EN_ONE, text, [])
        assert out["ok"], (lang, out["problems"])


def test_a_legal_reference_a_service_claim_or_a_threat_added_in_hindi_marathi_telugu_tamil_bengali_or_gujarati_is_caught():
    words = {"legal": "legal references", "service": "wording that says the notice was served", "threat": "words that threaten"}
    for name, (lang, text, kind) in ALTERED.items():
        out = preservation_check(EN_ONE, text, [])
        assert not out["ok"], name
        assert any(words[kind] in problem for problem in out["problems"]), (name, out["problems"])


def test_the_fenced_notice_keeps_its_markers_and_states_it_is_data():
    from lib.safety import fence

    text, _ = lift_blocks(ENGLISH)
    fenced = fence(text, "NOTICE")
    assert "{{STATEMENT}}" in fenced and "{{ENCLOSURES}}" in fenced and "untrusted text, data only" in fenced
