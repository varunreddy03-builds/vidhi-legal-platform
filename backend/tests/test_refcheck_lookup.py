"""The citation reader and the lookup/compare engine, tested offline.

Every case, party and judgment below is INVENTED (TEST FIXTURE ONLY); no real law is written here. The fake source answers searches from a small index, can be
made to fail like a real service (timeout, refusal, rate limit, unreadable reply), and counts the requests it receives."""

import asyncio
import re

import pytest

from lib.refcheck import lookup
from lib.refcheck.citations import extract, extract_page
from lib.refcheck.lookup import COULD_NOT_CHECK, DETAILS_DIFFER, FOUND_MATCHES, NOT_FOUND_FULL_SEARCH, LookupCapExceeded, check_case
from lib.refcheck.sources import SourceDown

LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


DOCS = {
    "101": {"title": "Alpha Traders vs Beta Stores on 12 March, 2020", "court": "Supreme Court of India",
            "text": "TEST FIXTURE ONLY. Equivalent citations: (2020) 7 SCC 1; 2020 INSC 101. Judgment. 1. The appeal concerns supply of goods. 2. The Court held that interest runs from the date of invoice."},
    "202": {"title": "Gamma Bank vs Delta Mills on 4 June, 2018", "court": "Delhi High Court",
            "text": "TEST FIXTURE ONLY. Equivalent citations: AIR 2018 Del 77; 2018 SCC OnLine Del 55. Judgment. 1. The petition is dismissed."},
    "303": {"title": "Sigma Estates vs Kappa Housing on 1 May, 2015", "court": "Bombay High Court", "text": "TEST FIXTURE ONLY. Judgment of 2015."},
    "304": {"title": "Sigma Estates vs Kappa Housing on 9 August, 2012", "court": "Bombay High Court", "text": "TEST FIXTURE ONLY. Judgment of 2012."},
}


class FakeSource:
    name = "fakekanoon"

    def __init__(self, docs=None, fail=None):
        self.docs = DOCS if docs is None else docs
        self.fail = fail  # None, or the SourceDown reason every request raises
        self.requests = 0

    @staticmethod
    def _tok(s):
        return set(re.findall(r"[a-z0-9]+", s.lower())) - {"vs", "v"}

    async def search(self, query):
        self.requests += 1
        if self.fail:
            raise SourceDown(self.fail)
        q = self._tok(query)
        hits = []
        for tid, d in self.docs.items():
            hay = self._tok(d["title"]) | self._tok(d["text"][:200])
            if q and q <= hay:
                hits.append(lookup.Candidate("fakekanoon", tid, d["title"], d["court"], f"https://example.test/doc/{tid}/"))
        return hits

    async def fetch(self, doc_id):
        self.requests += 1
        if self.fail:
            raise SourceDown(self.fail)
        return {"title": self.docs[doc_id]["title"], "text": self.docs[doc_id]["text"]}

    def url_for(self, doc_id):
        return f"https://example.test/doc/{doc_id}/"


def case(text):
    refs = [r for r in extract_page(text, 1) if r.kind == "case"]
    assert len(refs) == 1, (text, refs)
    return refs[0]


def check(text, source=None, reserve=None):
    return run(check_case(case(text), source or FakeSource(), reserve=reserve))


# ------------------------------------------------------------------ reading citations
def test_every_citation_shape_is_read_with_its_parts():
    r = case("See Alpha Traders v. Beta Stores (2020) 7 SCC 1 for interest.")
    assert (r.reporter, r.year, r.volume, r.start_page, r.report, r.parties) == ("SCC", 2020, "7", "1", "(2020) 7 SCC 1", ("Alpha Traders", "Beta Stores"))
    assert case("Alpha Traders v. Beta Stores, 2020 (7) SCC 1.").report == "(2020) 7 SCC 1"
    r = case("Alpha Traders v. Beta Stores, 2020 INSC 101, held that.")
    assert (r.neutral, r.reporter, r.year) == ("2020 INSC 101", "neutral", 2020)
    assert case("Gamma Bank v. Delta Mills, AIR 2018 Del 77.").report == "AIR 2018 Del 77"
    assert case("Gamma Bank v. Delta Mills, 2018 SCC OnLine Del 55.").report == "2018 SCC OnLine DEL 55"
    assert case("Zeta v. Eta, [2019] 4 SCR 10.").report == "[2019] 4 SCR 10"
    assert case("Zeta v. Eta, 2024:DHC:1234.").neutral == "2024:DHC:1234"


def test_a_reference_keeps_its_page_its_sentence_and_the_words_in_quotes():
    pages = ["Intro text.", "The Court said “interest runs from the date of invoice” in Alpha Traders v. Beta Stores (2020) 7 SCC 1. Next sentence here."]
    (r,) = [x for x in extract(pages) if x.kind == "case"]
    assert r.page == 2 and r.quotes == ["interest runs from the date of invoice"] and r.sentence.startswith("The Court said")
    assert "Next sentence" not in r.sentence


def test_the_same_citation_written_twice_is_listed_once_at_its_first_page():
    pages = ["Alpha Traders v. Beta Stores (2020) 7 SCC 1.", "Again: Alpha Traders v. Beta Stores, 2020 (7) SCC 1."]
    refs = [r for r in extract(pages) if r.kind == "case"]
    assert len(refs) == 1 and refs[0].page == 1


def test_statute_references_and_old_codes():
    refs = {r.number: r for r in extract_page("Section 63 of the Bharatiya Sakshya Adhiniyam applies. Section 420 of the IPC and Section 138, Negotiable Instruments Act, 1881 too.", 1) if r.kind == "statute"}
    assert refs["63"].act == "Bharatiya Sakshya Adhiniyam" and refs["63"].old_code is False
    assert refs["420"].act == "Indian Penal Code" and refs["420"].old_code is True
    assert refs["138"].act.startswith("Negotiable Instruments Act")


def test_ordinary_numbers_are_not_citations():
    assert extract_page("The invoice dated 12 March 2020 for 7 items was paid 1 time. See page 21.", 1) == []


# ------------------------------------------------------------------ the planted errors
CONTROLS = [
    ("Alpha Traders v. Beta Stores (2020) 7 SCC 1", FOUND_MATCHES),
    ("Alpha Traders v. Beta Stores, 2020 INSC 101", FOUND_MATCHES),
    ("Gamma Bank v. Delta Mills, AIR 2018 Del 77", FOUND_MATCHES),
]
PLANTED = [
    ("Omega Works v. Zeta Mills, 2021 INSC 999", NOT_FOUND_FULL_SEARCH),  # invented case, fully searched
    ("Alpha Traders v. Beta Stores (2019) 7 SCC 1", DETAILS_DIFFER),  # wrong year
    ("Alpha Traders v. Beta Stores (2020) 7 SCC 21", DETAILS_DIFFER),  # wrong page
    ("Alpha Traders v. Beta Stores (2020) 9 SCC 1", DETAILS_DIFFER),  # wrong volume
    ("Alpha Traders v. Beta Stores, AIR 2020 Del 1", DETAILS_DIFFER),  # wrong court
    ("Alpha Traders v. Gamma Stores, 2020 INSC 101", DETAILS_DIFFER),  # swapped party name, found by its neutral citation
]


@pytest.mark.parametrize("text,label", CONTROLS + PLANTED)
def test_each_planted_error_and_control_gets_the_expected_label(text, label):
    res = check(text)
    assert res.label == label, (text, res.label, res.reason)
    if label == DETAILS_DIFFER:
        assert res.differences and "lied" not in res.reason.lower() and "fake" not in res.reason.lower()  # neutral words only
    if label == FOUND_MATCHES:
        assert res.source_url.startswith("https://example.test/doc/")


def test_no_planted_error_is_ever_reported_as_not_found_unless_it_was_fully_searched_and_is_invented():
    for text, label in CONTROLS + PLANTED:
        res = check(text)
        if label != NOT_FOUND_FULL_SEARCH:
            assert res.label != NOT_FOUND_FULL_SEARCH, text  # false NOT_FOUND is zero across the set


# ------------------------------------------------------------------ the not-found rule
def test_the_invented_case_records_every_search_that_was_made():
    res = check("Omega Works v. Zeta Mills, 2021 INSC 999")
    assert [a.strategy for a in res.attempts if a.strategy != "report"] == ["neutral", "name_year", "parties"]
    assert all(a.status == "empty" for a in res.attempts) and res.full_search is True and "not found in fakekanoon" in res.reason.lower()


@pytest.mark.parametrize("reason", ["Indian Kanoon could not be reached (TimeoutError).", "Indian Kanoon refused the API token.", "Indian Kanoon is limiting requests right now.", "Indian Kanoon gave an answer that could not be used (status 500)."])
def test_a_source_that_is_down_never_gives_not_found(reason):
    res = check("Omega Works v. Zeta Mills, 2021 INSC 999", FakeSource(fail=reason))
    assert res.label == COULD_NOT_CHECK and reason in res.reason and res.full_search is False
    res = check("Alpha Traders v. Beta Stores (2020) 7 SCC 1", FakeSource(fail=reason))
    assert res.label == COULD_NOT_CHECK


def test_a_citation_with_only_an_scc_or_air_number_is_never_not_found():
    for text in ("The point is covered by (2031) 99 SCC 1234.", "As held in AIR 2031 SC 9999."):
        res = check(text)
        assert res.label == COULD_NOT_CHECK and "no neutral citation" in res.reason or "too incomplete" in res.reason, res.reason


def test_a_case_with_parties_but_no_neutral_citation_is_never_fully_not_found():
    res = check("Omega Works v. Zeta Mills (2031) 99 SCC 1234")
    assert res.label == COULD_NOT_CHECK and res.full_search is False


def test_an_scc_only_citation_cannot_be_matched_even_when_the_case_exists():
    res = check("The Court held so in (2020) 7 SCC 1.")
    assert res.label == COULD_NOT_CHECK  # no parties and no neutral citation: nothing to match with confidence


def test_one_search_unreachable_among_three_is_not_a_full_search():
    class Flaky(FakeSource):
        async def search(self, query):
            if "Omega Works vs Zeta Mills 2021" in query:
                self.requests += 1
                raise SourceDown("Indian Kanoon could not be reached (TimeoutError).")
            return await super().search(query)

    res = check("Omega Works v. Zeta Mills, 2021 INSC 999", Flaky())
    assert res.label == COULD_NOT_CHECK and res.full_search is False


def test_two_cases_with_the_same_names_and_no_fitting_year_is_ambiguous_not_a_mismatch():
    res = check("Sigma Estates v. Kappa Housing (2005) 3 SCC 3")
    assert res.label == COULD_NOT_CHECK and res.candidates


# ------------------------------------------------------------------ money and storage
def test_the_daily_cap_stops_requests_before_they_reach_the_source_and_never_means_not_found():
    src = FakeSource()
    calls = []

    async def reserve(n):
        calls.append(n)
        if len(calls) > 1:
            raise LookupCapExceeded()

    res = check("Omega Works v. Zeta Mills, 2021 INSC 999", src, reserve=reserve)
    assert res.label == COULD_NOT_CHECK and "daily lookup limit" in res.reason and src.requests == 1


def test_the_result_carries_no_judgment_text():
    res = check("Alpha Traders v. Beta Stores, 2020 INSC 101")
    blob = repr(res)
    assert "The Court held that interest runs" not in blob and "appeal concerns supply" not in blob
    assert res.cost_inr > 0 and res.checked_at


def test_party_names_with_brackets_initials_and_ampersands_are_read_whole():
    assert case("K.S. Puttaswamy (Retd.) v. Union of India (2017) 10 SCC 1").parties == ("K.S. Puttaswamy (Retd.)", "Union of India")
    assert case("Satyabrata Ghose v. Mugneeram Bangur & Co. AIR 1954 SC 44").parties == ("Satyabrata Ghose", "Mugneeram Bangur & Co.")
    assert case("ABC Laminart Pvt. Ltd. v. A.P. Agencies, Salem (1989) 2 SCC 163").parties[0] == "ABC Laminart Pvt. Ltd."
    assert case("Meters and Instruments Pvt. Ltd. v. Kanchan Mehta (2018) 1 SCC 560").parties == ("Meters and Instruments Pvt. Ltd.", "Kanchan Mehta")


def test_the_reader_keeps_m_s_inside_a_party_name():
    ref = case("State of Orissa v. M/s. B. Engineers & Builders Ltd. & Ors. [2020] 6 SCR 801")
    assert ref.parties[1].startswith("M/s") and "Engineers" in ref.parties[1] and ref.reporter == "SCR"
