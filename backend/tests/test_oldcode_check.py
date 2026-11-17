"""The old-code finder reads where the older criminal codes are named and which section numbers sit next to the name. It maps nothing and judges nothing (pure code, no database)."""

from lib.oldcode.check import canonical, check


def found(text):
    return [(f.kind, f.act, f.section) for f in check([text])]


def test_the_common_ways_of_writing_a_section_and_an_act_are_read():
    assert found("The accused is charged under Section 302 of the Indian Penal Code, 1860.") == [("section", "IPC", "302")]
    assert found("FIR under Sec. 420 IPC.") == [("section", "IPC", "420")]
    assert found("Registered u/s 307 I.P.C. at the station.") == [("section", "IPC", "307")]
    assert found("A petition under Section 482 of the Cr.P.C. was filed.") == [("section", "CrPC", "482")]
    assert found("Under Section 154 of the Code of Criminal Procedure, 1973 the report was lodged.") == [("section", "CrPC", "154")]
    assert found("The certificate under Section 65B of the Indian Evidence Act was produced.") == [("section", "IEA", "65B")]
    assert found("S. 313 CrPC statement was recorded.") == [("section", "CrPC", "313")]


def test_a_list_of_sections_gives_one_finding_each_and_a_range_is_not_expanded():
    assert found("Sections 323, 324 and 34 of the IPC.") == [("section", "IPC", "323"), ("section", "IPC", "324"), ("section", "IPC", "34")]
    assert found("Sections 498-A, 304-B/34 IPC") == [("section", "IPC", "498A"), ("section", "IPC", "304B"), ("section", "IPC", "34")]
    r = check(["Sections 323 to 326 IPC were added."])
    assert [f.section for f in r] == ["323", "326"] and all("not listed here" in f.note for f in r)
    assert [f.section for f in check(["Section 34 IPC and again Section 34 IPC"])] == ["34", "34"]  # each place is its own finding
    assert [f.section for f in check(["Sections 34, 34 IPC"])] == ["34"]  # but a number repeated inside one list is shown once


def test_sub_sections_are_not_mistaken_for_sections():
    assert found("Section 482(1) of the CrPC") == [("section", "CrPC", "482")]
    assert canonical("498-A") == canonical("498 A") == canonical("498a") == "498A"


def test_an_act_named_without_a_readable_section_is_a_mention_and_other_acts_are_ignored():
    assert found("The offences under the IPC were discussed.") == [("mention", "IPC", "")]
    assert found("Section 138 of the Negotiable Instruments Act, 1881 applies.") == []
    assert found("The ipcc report was discussed.") == []  # part of another word is not the Code
    assert found("The topic of ipc codes") == [("mention", "IPC", "")]  # the short name on its own is a mention
    assert found("Section 9 of the Arbitration Act") == []
    assert found("Section 302 of the Bharatiya Nyaya Sanhita") == []  # the new codes are not the old ones


def test_each_finding_keeps_the_sentence_the_page_and_neutral_words():
    r = check(["Nothing here.", "He was charged. The charge is under Section 420 IPC. The trial began."])
    assert len(r) == 1 and r[0].page == 2 and "Section 420" in r[0].sentence
    blob = " ".join(f.note for f in check(["Section 420 IPC and the CrPC."])).lower()
    assert "outdated" not in blob and "repealed" not in blob and "wrong" not in blob and "use " not in blob
    assert check([""]) == [] and check([None]) == []


def test_hostile_text_cannot_tie_up_the_server():
    import time

    for text in ("Section 1" + " " * 200_000 + "x", "IPC " * 50_000, "Section 1, " * 20_000, "Cr. P. C. " * 20_000):
        t0 = time.perf_counter()
        check([text])
        assert time.perf_counter() - t0 < 8, text[:20]  # was minutes: two \s* side by side backtracked quadratically, and every finding re-scanned the whole page


def test_a_huge_page_still_gives_the_sentence_around_each_reference():
    page = ("filler words go here " * 3000) + "The charge is under Section 420 IPC. " + ("more filler " * 3000)
    r = check([page])
    assert len(r) == 1 and "Section 420 IPC" in r[0].sentence and len(r[0].sentence) <= 900
