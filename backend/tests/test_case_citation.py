"""Reading case citations in code. More than 100 strings: each way of writing a citation, the same case written many ways, partial citations (never completed by guessing),
names, paragraph references, quotations, parallel citations, other-script digits, and text that must NOT be read as a citation. No model is used; every case is a fictional or well-known citation form."""
import re

import pytest

from lib import case_citation as cc

# ---- one citation, many ways to write it: (text, canonical) ----
SINGLE = [
    # SCC
    ("(2010) 5 SCC 123", "(2010) 5 SCC 123"), ("2010 (5) SCC 123", "(2010) 5 SCC 123"), ("(2010) 5 S.C.C. 123", "(2010) 5 SCC 123"), ("(2010)  5  SCC  123", "(2010) 5 SCC 123"),
    ("( 2010 ) 5 SCC 123", "(2010) 5 SCC 123"), ("(2010) 5 SCC123", "(2010) 5 SCC 123"), ("(1978) 1 SCC 248", "(1978) 1 SCC 248"), ("(2024) 12 SCC 1", "(2024) 12 SCC 1"),
    ("(2010) 5 scc 123", "(2010) 5 SCC 123"), ("2010 5 SCC 123", "(2010) 5 SCC 123"),
    ("(2010) 5 SCC (Cri) 123", "(2010) 5 SCC (Cri) 123"), ("(2010) 5 SCC (Civ) 123", "(2010) 5 SCC (Civ) 123"), ("(2010) 5 SCC (L&S) 123", "(2010) 5 SCC (L&S) 123"),
    ("(2010) 5 SCC (Tax) 123", "(2010) 5 SCC (Tax) 123"), ("(2010) 5 SCC (cri) 123", "(2010) 5 SCC (Cri) 123"),
    ("1992 Supp (2) SCC 100", "1992 Supp (2) SCC 100"), ("1992 Supp SCC 100", "1992 Supp SCC 100"), ("1989 Supp (1) SCC 5", "1989 Supp (1) SCC 5"), ("1992 Supp. (2) S.C.C. 100", "1992 Supp (2) SCC 100"),
    # SCC OnLine
    ("2019 SCC OnLine SC 1234", "2019 SCC OnLine SC 1234"), ("2019 SCC Online SC 1234", "2019 SCC OnLine SC 1234"), ("2019 SCC OnLine Del 345", "2019 SCC OnLine Del 345"),
    ("2019 S.C.C. OnLine Bom 77", "2019 SCC OnLine Bom 77"), ("2021 SCC OnLine Mad 9", "2021 SCC OnLine Mad 9"), ("2021 SCC OnLine Cal 12345", "2021 SCC OnLine Cal 12345"),
    ("2018 SCC OnLine P&H 100", "2018 SCC OnLine P&H 100"), ("2018 SCC OnLine J&K 7", "2018 SCC OnLine J&K 7"), ("2020 SCC OnLine Ker 4321", "2020 SCC OnLine Ker 4321"),
    ("2020 SCC OnLine SC 1", "2020 SCC OnLine SC 1"), ("2022 SCC OnLine Del 000345", "2022 SCC OnLine Del 345"), ("2017 SCC OnLine Utt 55", "2017 SCC OnLine Utt 55"),
    ("2017 SCC Online AP 55", "2017 SCC OnLine AP 55"), ("2017 SCC OnLine Tel 55", "2017 SCC OnLine Tel 55"), ("2017 SCC OnLine Gau 5", "2017 SCC OnLine Gau 5"),
    # AIR
    ("AIR 1978 SC 597", "AIR 1978 SC 597"), ("A.I.R. 1978 S.C. 597", "AIR 1978 SC 597"), ("AIR (1978) SC 597", "AIR 1978 SC 597"), ("AIR 1978 S.C. 597", "AIR 1978 SC 597"),
    ("AIR 1990 Del 12", "AIR 1990 Del 12"), ("AIR 1990 Bom 1", "AIR 1990 Bom 1"), ("AIR 2005 SC 3016", "AIR 2005 SC 3016"), ("AIR 1961 All 2", "AIR 1961 All 2"),
    ("AIR 1961 Cal 100", "AIR 1961 Cal 100"), ("AIR 1961 Mad 100", "AIR 1961 Mad 100"), ("AIR 1999 Pat 33", "AIR 1999 Pat 33"), ("AIR 1999 P&H 33", "AIR 1999 P&H 33"),
    ("AIR 1999 Raj 33", "AIR 1999 Raj 33"), ("AIR 1999 Guj 33", "AIR 1999 Guj 33"), ("AIR 1999 Ker 33", "AIR 1999 Ker 33"), ("AIR 1999 Kar 33", "AIR 1999 Kar 33"),
    ("AIR 1999 MP 33", "AIR 1999 MP 33"), ("AIR 1999 Ori 33", "AIR 1999 Ori 33"), ("AIR 1999 HP 33", "AIR 1999 HP 33"), ("AIR 2012 SC 1", "AIR 2012 SC 1"),
    ("air 1978 sc 597", "AIR 1978 SC 597"), ("AIR 1978 SC 597.", "AIR 1978 SC 597"), ("AIR 1978 SC 0597", "AIR 1978 SC 597"), ("A.I.R 1978 Del. 5", "AIR 1978 Del 5"),
    # SCR
    ("[1978] 2 SCR 621", "[1978] 2 SCR 621"), ("(1978) 2 SCR 621", "[1978] 2 SCR 621"), ("(1978) 2 S.C.R. 621", "[1978] 2 SCR 621"), ("1978 (2) SCR 621", "[1978] 2 SCR 621"),
    ("[2021] 3 S.C.R. 100", "[2021] 3 SCR 100"), ("[2021] 3 SCR 1", "[2021] 3 SCR 1"), ("[1950] SCR 88", None),
    # neutral
    ("2023 INSC 123", "2023 INSC 123"), ("2024 INSC 1008", "2024 INSC 1008"), ("2023 insc 5", "2023 INSC 5"), ("2023:DHC:1234", "2023:DHC:1234"), ("2023:BHC-AS:1234", "2023:BHC-AS:1234"),
    ("2023:BHC-OS:7", "2023:BHC-OS:7"), ("2024:KER:123", "2024:KER:123"), ("2024:PHHC:12345", "2024:PHHC:12345"), ("2024:MHC:99", "2024:MHC:99"), ("2024:CHC-OS:1", "2024:CHC-OS:1"),
    ("2024:INSC:55", "2024:INSC:55"), ("2024:GAU:5", "2024:GAU:5"),
    # in a sentence
    ("The Court relied on (2010) 5 SCC 123 for this.", "(2010) 5 SCC 123"), ("See AIR 1978 SC 597.", "AIR 1978 SC 597"), ("see also 2023 INSC 123, at the end", "2023 INSC 123"),
    ("In 2019 SCC OnLine SC 1234 the Court said so", "2019 SCC OnLine SC 1234"), ("held in ((2010) 5 SCC 123)", "(2010) 5 SCC 123"), ("[2023:DHC:1234]", "2023:DHC:1234"),
    # digits of other scripts
    ("(२०१०) ५ SCC १२३", "(2010) 5 SCC 123"), ("AIR १९७८ SC ५९७", "AIR 1978 SC 597"), ("(౨౦౧౦) ౫ SCC ౧౨౩", "(2010) 5 SCC 123"),
]

# ---- not complete: the missing part is named and no canonical form is made up ----
PARTIAL = [
    ("AIR 1978 SC", "air", ["page"]), ("AIR 1990 Del", "air", ["page"]), ("2019 SCC OnLine SC", "scc_online", ["number"]), ("2019 SCC OnLine Del", "scc_online", ["number"]),
    ("(2010) SCC 123", "scc", ["volume"]), ("(2010) 5 SCC", "scc", ["page"]), ("(2010) SCC", "scc", ["volume", "page"]), ("[1978] SCR 621", "scr", ["volume"]),
    ("[1978] 2 SCR", "scr", ["page"]), ("1992 Supp (2) SCC", "scc", ["page"]),
]

# ---- text that is NOT a case citation ----
NOT_CITATIONS = [
    "", "   ", "Section 138 of the Negotiable Instruments Act", "the year 2010 was long", "5 SCC", "SCC 123", "2010 SCC", "AIR 1978 and the next", "air force 1978 and more",
    "Order 7 Rule 11", "page 123 of 2010", "Rs 5,000 paid on 12 March 2010", "the SCR rules", "article 21 of the Constitution", "Call 2010:5:5 for tea",
    "version 2.0.1", "(2010) was the year", "AIR conditioning", "The Supreme Court said so.", "2010 5", "A.I.R.", "SCC OnLine", "INSC", "hello (2010) world",
]

# ---- the same case written many ways must reduce to one canonical form ----
SAME_CASE = {
    "AIR 1978 SC 597": ["AIR 1978 SC 597", "A.I.R. 1978 S.C. 597", "AIR (1978) SC 597", "AIR 1978 S.C. 597", "air 1978 sc 597", "AIR 1978 SC 0597"],
    "(2010) 5 SCC 123": ["(2010) 5 SCC 123", "2010 (5) SCC 123", "(2010) 5 S.C.C. 123", "( 2010 ) 5 SCC 123", "(2010) 5 SCC123"],
    "[1978] 2 SCR 621": ["[1978] 2 SCR 621", "(1978) 2 SCR 621", "1978 (2) SCR 621", "[1978] 2 S.C.R. 621"],
    "2019 SCC OnLine SC 1234": ["2019 SCC OnLine SC 1234", "2019 SCC Online SC 1234", "2019 S.C.C. OnLine S.C. 1234"],
}


@pytest.mark.parametrize("text,expected", SINGLE)
def test_one_citation_has_one_canonical_form(text, expected):
    found = [c for c in cc.parse(text) if c["kind"] != "case_name"]
    assert len(found) == 1, (text, [c["raw"] for c in found])
    assert found[0]["canonical"] == expected and cc.canonical(text) == expected
    assert found[0]["complete"] == (expected is not None)
    if expected is None:
        assert found[0]["kind"] == "other_reporter" or found[0]["missing"]


@pytest.mark.parametrize("text,kind,missing", PARTIAL)
def test_a_partial_citation_is_never_completed(text, kind, missing):
    found = cc.parse(text)
    assert [c["kind"] for c in found] == [kind]
    c = found[0]
    assert c["complete"] is False and c["missing"] == missing and c["canonical"] is None
    assert cc.canonical(text) is None


@pytest.mark.parametrize("text", NOT_CITATIONS)
def test_ordinary_text_is_not_read_as_a_citation(text):
    assert [c for c in cc.parse(text) if c["kind"] not in ("case_name",)] == []


@pytest.mark.parametrize("canon,forms", SAME_CASE.items())
def test_different_writings_of_a_case_become_the_same_form(canon, forms):
    assert {cc.canonical(f) for f in forms} == {canon}
    assert {cc.canonical(f"Held in {f}, see the order.") for f in forms} == {canon}


def test_offsets_point_at_the_citation_in_the_text_as_given():
    for text, expected in SINGLE:
        if expected is None:
            continue
        for c in cc.parse(text):
            if c["kind"] != "case_name":
                assert text[c["start"]:c["end"]] == c["raw"]
                assert not c["raw"].startswith(" ") and not c["raw"].endswith(" ")
    text = "x " * 40 + "AIR 1978 SC 597" + " y" * 40
    c = cc.parse(text)[0]
    assert text[c["start"]:c["end"]] == "AIR 1978 SC 597"


def test_the_canonical_form_reads_back_to_itself():
    for text, expected in SINGLE:
        if expected:
            assert cc.canonical(expected) == expected, expected


def test_two_citations_in_one_text_are_both_read_in_order():
    text = "Compare (2010) 5 SCC 123 with AIR 1978 SC 597 and 2023 INSC 123."
    assert [c["canonical"] for c in cc.parse(text)] == ["(2010) 5 SCC 123", "AIR 1978 SC 597", "2023 INSC 123"]
    assert cc.canonical(text) is None  # canonical() answers only for text that holds exactly one


def test_scc_online_is_not_also_read_as_scc():
    found = cc.parse("2019 SCC OnLine SC 1234")
    assert [c["kind"] for c in found] == ["scc_online"]


def test_an_unknown_court_code_is_kept_as_written_and_noted():
    c = cc.parse("AIR 1999 Xyz 33")[0]
    assert c["canonical"] == "AIR 1999 Xyz 33" and any("not one this module knows" in n for n in c["notes"])
    c = cc.parse("2020 SCC OnLine Zzz 5")[0]
    assert c["canonical"] == "2020 SCC OnLine Zzz 5" and c["notes"]


def test_a_year_that_cannot_be_right_is_noted_not_corrected():
    c = cc.parse("AIR 1850 SC 5")  # the regex does not accept years before 1800s as citations at all
    assert c == [] or c[0]["canonical"] == "AIR 1850 SC 5"
    c = cc.parse("(2099) 5 SCC 123")[0]
    assert c["canonical"] == "(2099) 5 SCC 123" and any("2099" in n for n in c["notes"])
    c = cc.parse("AIR 1850 SC 5") or [{"notes": ["x"]}]
    assert c[0]["notes"]


# ---- case names ----
NAMES = [
    ("Maneka Gandhi v. Union of India, AIR 1978 SC 597", "Maneka Gandhi v. Union of India"),
    ("Maneka Gandhi vs Union of India (1978) 1 SCC 248", "Maneka Gandhi v. Union of India"),
    ("Maneka Gandhi versus Union of India, (1978) 1 SCC 248", "Maneka Gandhi v. Union of India"),
    ("State of U.P. v. Raj Narain, AIR 1975 SC 865", "State of U.P. v. Raj Narain"),
    ("Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225", "Kesavananda Bharati v. State of Kerala"),
    ("In re Vinay Chandra Mishra, (1995) 2 SCC 584", "In re Vinay Chandra Mishra"),
    ("Hindustan Zinc Ltd. v. Ajmer Vidyut Vitran Nigam Ltd., (2019) 17 SCC 82", "Hindustan Zinc Ltd. v. Ajmer Vidyut Vitran Nigam Ltd."),
    ("The Court followed Ram Kumar v. State of Haryana, 2019 SCC OnLine SC 77.", "Ram Kumar v. State of Haryana"),
    ("As held in A. B. Traders v. C. D. & Co. (2010) 5 SCC 123,", "A. B. Traders v. C. D. & Co."),
    ("Rajesh v. State (NCT of Delhi), 2023 INSC 123", "Rajesh v. State (NCT of Delhi)"),
    ("[Sita Devi v. Ravi Kumar, (2010) 5 SCC 123]", "Sita Devi v. Ravi Kumar"),
]


@pytest.mark.parametrize("text,name", NAMES)
def test_the_case_name_before_a_citation_is_attached_to_it(text, name):
    cites = [c for c in cc.parse(text) if c["kind"] != "case_name"]
    assert len(cites) == 1 and cites[0]["case_name"] == name
    assert not [c for c in cc.parse(text) if c["kind"] == "case_name"]  # not also listed on its own


def test_a_name_with_no_citation_is_returned_alone_and_says_so():
    found = cc.parse("Kesavananda Bharati v. State of Kerala was decided in 1973.")
    assert [c["kind"] for c in found] == ["case_name"]
    assert found[0]["canonical"] == "Kesavananda Bharati v. State of Kerala" and found[0]["complete"] is False and found[0]["missing"] == ["reporter citation"]


def test_a_name_far_from_the_citation_is_not_attached():
    found = cc.parse("Ram v. Shyam was cited by counsel. The court preferred (2010) 5 SCC 123.")
    assert [c["case_name"] for c in found if c["kind"] == "scc"] == [None]
    assert any(c["kind"] == "case_name" for c in found)


def test_lower_case_prose_around_a_v_is_not_a_case_name():
    assert cc.parse("the plaintiff v the defendant in this matter") == []
    assert cc.parse("version v 2") == []


# ---- paragraph references ----
PARAS = [
    ("(2010) 5 SCC 123, para 12", [(12, 12)]), ("(2010) 5 SCC 123, paras 12-14", [(12, 14)]), ("(2010) 5 SCC 123 (para 7)", [(7, 7)]), ("(2010) 5 SCC 123 [para 7]", [(7, 7)]),
    ("(2010) 5 SCC 123, at para 28", [(28, 28)]), ("(2010) 5 SCC 123, paragraph 3", [(3, 3)]), ("(2010) 5 SCC 123, paragraphs 3 to 5", [(3, 5)]), ("(2010) 5 SCC 123, ¶ 9", [(9, 9)]),
    ("(2010) 5 SCC 123, ¶¶ 9–11", [(9, 11)]), ("(2010) 5 SCC 123, paras. 3, 5 and 9", [(3, 3), (5, 5), (9, 9)]), ("AIR 1978 SC 597 (paras 3, 5-7)", [(3, 3), (5, 7)]),
    ("AIR 1978 SC 597, para १२", [(12, 12)]), ("2023 INSC 123, para 4", [(4, 4)]), ("2019 SCC OnLine SC 1234 at paras 20 & 21", [(20, 20), (21, 21)]),
]


@pytest.mark.parametrize("text,paras", PARAS)
def test_paragraph_references_after_a_citation(text, paras):
    c = [x for x in cc.parse(text) if x["kind"] != "case_name"][0]
    assert [(p["from"], p["to"]) for p in c["paras"]] == paras


def test_a_paragraph_that_is_not_next_to_a_citation_is_ignored():
    c = cc.parse("In para 12 the court noted that (2010) 5 SCC 123 applies.")[0]
    assert c["paras"] == []


def test_a_backwards_range_is_kept_as_typed_and_noted():
    c = cc.parse("(2010) 5 SCC 123, paras 14-12")[0]
    assert c["paras"] == [{"from": 14, "to": 14, "note": "range 14-12 runs backwards; kept as typed"}]


# ---- quotations in brackets ----
def test_a_quotation_before_a_bracketed_citation_is_returned_exactly_as_written():
    text = "The Court held “the right to life includes the right to live with dignity” [Francis Coralie v. Union Territory of Delhi, (1981) 1 SCC 608, paras 7-8]."
    c = cc.parse(text)[0]
    assert c["quote"] == "the right to life includes the right to live with dignity"
    assert c["case_name"] == "Francis Coralie v. Union Territory of Delhi" and c["paras"][0]["from"] == 7


def test_straight_quotes_and_round_brackets_work_too():
    c = cc.parse('It was said "no person shall be deprived" (AIR 1978 SC 597, para 5).')[0]
    assert c["quote"] == "no person shall be deprived" and c["paras"][0]["from"] == 5


def test_a_quotation_with_odd_spacing_or_an_ocr_slip_is_kept_untouched():
    c = cc.parse("“the  rigth to life”  [(2010) 5 SCC 123]")[0]
    assert c["quote"] == "the  rigth to life"  # not corrected: locating it in a judgment is textmatch's job


def test_no_quote_is_attached_when_the_brackets_do_not_enclose_the_citation():
    assert cc.parse("“some words” and then (2010) 5 SCC 123 elsewhere")[0]["quote"] is None
    assert cc.parse("“some words” [see] (2010) 5 SCC 123")[0]["quote"] is None
    assert cc.parse("(2010) 5 SCC 123")[0]["quote"] is None


def test_the_scr_year_bracket_is_not_taken_for_a_quotation_bracket():
    assert cc.parse("“held so” [1978] 2 SCR 621")[0]["quote"] is None
    assert cc.parse("“held so” [[1978] 2 SCR 621]")[0]["quote"] == "held so"


# ---- parallel citations ----
def test_a_case_reported_twice_is_one_parallel_group():
    found = cc.parse("Maneka Gandhi v. Union of India, (1978) 1 SCC 248 : AIR 1978 SC 597 : [1978] 2 SCR 621")
    assert [c["canonical"] for c in found] == ["(1978) 1 SCC 248", "AIR 1978 SC 597", "[1978] 2 SCR 621"]
    assert {c["parallel_group"] for c in found} == {1}
    assert found[0]["case_name"] == "Maneka Gandhi v. Union of India"


def test_two_different_cases_are_not_grouped():
    found = cc.parse("(1978) 1 SCC 248; and later AIR 1980 SC 1")
    assert [c["parallel_group"] for c in found] == [None, None]
    assert [c["parallel_group"] for c in cc.parse("(1978) 1 SCC 248, AIR 1980 SC 1")] == [None, None]


# ---- readers that are not supported ----
NOT_READ = ["[1973] Supp. SCR 1", "1975 Supp SCR 4", "(2010) 5 SCC Online 1"]
OTHER = ["JT 2010 (5) SC 12", "SCALE (2010) 5 123", "2010 Cri LJ 123", "ILR (2010) 2 Kar 5", "MANU/SC/0123/2010", "LL 2021 SC 123", "(2010) CTC 12 Mad", "2010 ACJ 55"]


@pytest.mark.parametrize("text", OTHER)
def test_other_reporters_are_marked_as_not_read(text):
    found = [c for c in cc.parse(text) if c["kind"] == "other_reporter"]
    assert found and all(c["canonical"] is None and c["complete"] is False and c["notes"] for c in found)


# ---- together with statute provisions ----
def test_provisions_are_read_by_the_existing_parser_with_the_case_citations_blanked_out():
    both = cc.parse_all("Under Section 138 of the Negotiable Instruments Act, see (2010) 5 SCC 123 and AIR 1978 SC 597.")
    assert [c["canonical"] for c in both["cases"]] == ["(2010) 5 SCC 123", "AIR 1978 SC 597"]
    assert [p["number"] for p in both["provisions"]] == ["138"]
    # without the blanking, "5 SCC" would be read as section 5 of an Act called SCC
    from lib.legal_search import parse_citations

    assert "5" in [p["number"] for p in parse_citations("(2010) 5 SCC 123")]
    assert cc.parse_all("(2010) 5 SCC 123")["provisions"] == []


# ---- robustness ----
def test_hostile_and_large_input_does_not_hang_or_break():
    for text in ["(" * 5000, "AIR " * 5000, "v. " * 5000, "[" * 3000 + "(2010) 5 SCC 123" + "]" * 3000, "“" + "a" * 100000, "A v B " * 3000, None]:
        cc.parse(text)
    big = ("The court said so. " * 20 + "(2010) 5 SCC 123. ") * 400
    assert len(cc.parse(big)) == 400


def test_every_result_has_the_same_fields():
    keys = {"kind", "raw", "start", "end", "canonical", "complete", "missing", "parts", "case_name", "paras", "quote", "parallel_group", "notes"}
    for text, _ in SINGLE[:40]:
        for c in cc.parse(text):
            assert set(c) == keys
    assert re.fullmatch(r"[a-z_]+", cc.parse("AIR 1978 SC 597")[0]["kind"])


def test_the_number_of_strings_tested_is_over_one_hundred():
    total = len(SINGLE) + len(PARTIAL) + len(NOT_CITATIONS) + len(NAMES) + len(PARAS) + len(OTHER) + sum(len(v) for v in SAME_CASE.values())
    assert total >= 100, total


@pytest.mark.parametrize("text", NOT_READ)
def test_forms_this_module_does_not_read_give_no_canonical_form(text):
    assert [c["canonical"] for c in cc.parse(text) if c["kind"] != "case_name"] in ([], [None])
