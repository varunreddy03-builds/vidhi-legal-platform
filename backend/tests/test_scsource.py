"""The Supreme Court open-dataset source, tested on an INVENTED mini dataset (TEST FIXTURE ONLY: made-up cases, written as real tar files and real PDFs in the dataset's layout).

Rules under test: each judgment is one record even when it sits in two year folders; neutral and SCR citations identify a judgment; SCC and AIR are 'not verifiable from this source';
the source is never treated as complete (so never 'not found after a full search'); a citation newer than the data is 'could not check'; unreadable text offers no quote;
a party-name-only hit in a later-cited year is not reported as a mismatch; the report carries the attribution."""

import asyncio
import io
import json
import tarfile
import textwrap
from datetime import date

import pytest

from lib.refcheck import lookup, quotes, scdata
from lib.refcheck.citations import extract_page
from lib.refcheck.lookup import COULD_NOT_CHECK, DETAILS_DIFFER, FOUND_MATCHES, NOT_FOUND_FULL_SEARCH
from lib.refcheck.scsource import SupremeCourtData, judgment_blocks, readable

LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


def meta(petitioner, respondent, neutral="", scr="", year=2020, scraped="2026-10-17T10:00:00"):
    bits = ["English", "Disclaimer", "Due care and caution has been taken by the Editorial Section", petitioner, "versus", respondent, "-"]
    if scr:
        bits.append(scr)
    if neutral:
        bits.append(neutral)
    bits += ["Coram : A. TESTER", "Issue for Consideration"]
    return {"raw_html": "".join(f"<p>{b}</p>" for b in bits), "path": "x", "citation_year": year, "nc_display": neutral.replace(" ", ""), "scraped_at": scraped}


def pdf(paragraphs: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for p in paragraphs:
        for line in textwrap.wrap(p, 90):  # wrap at word boundaries, as a real typeset judgment does
            c.drawString(40, y, line)
            y -= 14
        y -= 10
    c.save()
    return buf.getvalue()


PROSE = ("The appeal concerns the supply of goods under a written contract between the parties and the question is whether interest runs from the date of invoice. "
         "The Court considered the contract, the invoices and the conduct of both sides over the period in dispute and the submissions of learned counsel for the appellant and the respondent. ") * 3
JUDGMENT = [f"1. {PROSE}", f"2. The Court held that interest runs from the date of invoice and not from the date of demand. {PROSE}", f"3. The appeal is dismissed with costs. {PROSE}"]


def add(tar, name, data: bytes):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("sc")
    cases = {  # folder year -> list of (stem, metadata, paragraphs)
        2020: [("2020_7_1_20", meta("ALPHA TRADERS", "BETA STORES", "2020 INSC 101", "[2020] 7 SCR 1", 2020), JUDGMENT)],
        2021: [("2021_3_50_60", meta("GAMMA BANK", "DELTA MILLS", "2021 INSC 55", "[2021] 3 SCR 50", 2021), JUDGMENT),
               ("2020_7_1_20", meta("ALPHA TRADERS", "BETA STORES", "2020 INSC 101", "[2020] 7 SCR 1", 2020), JUDGMENT)],  # the same judgment listed again in the next year's folder
        2012: [("2012_9_9_30", meta("KAPPA HOUSING", "SIGMA ESTATES", "2012 INSC 700", "[2012] 9 SCR 9", 2012), JUDGMENT)],
        2022: [("2022_1_5_9", meta("TABLE CO", "NUMBERS LTD", "2022 INSC 9", "[2022] 1 SCR 5", 2022), ["12 34 56 78 90 11 22 33 44 55 66 77 88 99 " * 30])],  # no prose
    }
    for year, items in cases.items():
        (root / "metadata" / "tar" / f"year={year}").mkdir(parents=True)
        (root / "data" / "tar" / f"year={year}" / "english").mkdir(parents=True)
        with tarfile.open(root / "metadata" / "tar" / f"year={year}" / "metadata.tar", "w") as m, tarfile.open(root / "data" / "tar" / f"year={year}" / "english" / "english.tar", "w") as e:
            for stem, md, paras in items:
                add(m, f"{stem}.json", json.dumps(md).encode())
                add(e, f"{stem}_EN.pdf", pdf(paras))
    return SupremeCourtData(root)


def ref(text):
    r = [x for x in extract_page(text, 1) if x.kind == "case"]
    assert len(r) == 1, text
    return r[0]


def check(dataset, text):
    return run(lookup.check_case(ref(text), dataset))


def test_each_judgment_is_one_record_even_when_listed_in_two_year_folders(dataset):
    assert len(dataset.records) == 4
    r = dataset.records["2020_7_1_20"]
    assert r.folders == [2020, 2021] and r.year == 2020


def test_neutral_and_scr_citations_identify_one_judgment_and_the_attribution_is_carried(dataset):
    assert [c.doc_id for c in run(dataset.search('"2021 INSC 55"'))] == ["2021_3_50_60"]
    assert [c.doc_id for c in run(dataset.search('"[2021] 3 SCR 50"'))] == ["2021_3_50_60"]
    assert run(dataset.search('"2021 INSC 5555"')) == []
    a = dataset.attribution()
    assert a["licence"] == "CC-BY-4.0" and a["as_of"] == "2026-10-17" and "data as of 2026-10-17" in a["text"] and "Dattam Labs" in a["text"]


def test_correct_neutral_and_scr_citations_are_found_and_wrong_ones_are_caught(dataset):
    assert check(dataset, "Alpha Traders v. Beta Stores 2020 INSC 101").label == FOUND_MATCHES
    assert check(dataset, "Gamma Bank v. Delta Mills [2021] 3 SCR 50").label == FOUND_MATCHES
    assert check(dataset, "Gamma Bank v. Delta Mills [2021] 3 SCR 57").label in (DETAILS_DIFFER, COULD_NOT_CHECK)  # a changed page is never accepted
    off_by_one = check(dataset, "Gamma Bank v. Delta Mills 2021 INSC 56")  # right parties and year, wrong neutral number: must never be accepted
    assert off_by_one.label == DETAILS_DIFFER and "different neutral citation" in off_by_one.reason


def test_an_invented_case_is_never_accepted_and_never_reported_as_not_found(dataset):
    for text in ("Sharma v. Eastland Bank 2021 INSC 999", "Omega Corp v. Zeta Ltd [2021] 3 SCR 51"):
        res = check(dataset, text)
        assert res.label == COULD_NOT_CHECK and res.label != NOT_FOUND_FULL_SEARCH
    assert dataset.complete_for(2021) is False  # completeness of the dataset is unverified, so absence proves nothing


def test_scc_and_air_numbers_cannot_be_verified_from_this_source(dataset):
    res = check(dataset, "Alpha Traders v. Beta Stores (2020) 7 SCC 1")
    assert res.label == COULD_NOT_CHECK and "Report number not verifiable from this source" in res.reason
    air = check(dataset, "Alpha Traders v. Beta Stores AIR 2020 SC 1")
    assert air.label in (COULD_NOT_CHECK, DETAILS_DIFFER) and air.label != FOUND_MATCHES


def test_a_citation_newer_than_the_data_could_not_be_checked(dataset):
    res = check(dataset, "Alpha Traders v. Beta Stores (2027) 1 SCC 1")
    assert res.label == COULD_NOT_CHECK and "later than the newest judgment" in res.reason and "2026-10-17" in res.reason


def test_a_party_name_only_hit_decided_earlier_than_the_cited_year_is_not_called_a_mismatch(dataset):
    res = check(dataset, "Kappa Housing v. Sigma Estates (2014) 2 SCC 1")  # same parties, decided 2012: may be another case
    assert res.label == COULD_NOT_CHECK and "may be a different case" in res.reason
    early = check(dataset, "Alpha Traders v. Beta Stores (2019) 7 SCC 1")  # cited year EARLIER than the decision cannot be a reporting delay
    assert early.label == DETAILS_DIFFER


def test_the_text_is_read_in_paragraphs_and_a_quote_is_found_with_its_paragraph(dataset):
    doc = run(dataset.fetch("2020_7_1_20"))
    assert doc["blocks"][0].startswith("Equivalent citations: [2020] 7 SCR 1; 2020 INSC 101") and len(doc["blocks"]) >= 3
    r = quotes.check_quote("interest runs from the date of invoice and not from the date of demand", doc["blocks"])
    assert r["result"] == quotes.QUOTE_FOUND and r["paragraph"] == 2
    assert quotes.check_quote("the buyer must pay double the invoice as damages", doc["blocks"])["result"] == quotes.QUOTE_NOT_FOUND


def test_text_that_is_not_prose_offers_no_quote_so_a_quote_is_never_wrongly_missing(dataset):
    doc = run(dataset.fetch("2022_1_5_9"))
    assert doc["blocks"] == []
    assert quotes.check_all(["some words that the judgment might contain"], doc["blocks"], confirmed=True)[0]["result"] == quotes.QUOTE_NOT_CHECKED
    assert readable(["too short"]) is False and readable([PROSE]) is True and readable(["1 2 3 4 5 6 7 8 9 0 " * 100]) is False


def test_judgment_blocks_split_before_numbered_paragraphs():
    blocks = judgment_blocks(pdf(["Intro line.", "1. First numbered paragraph text here.", "2. Second numbered paragraph text here."]))
    assert any(b.startswith("1. First") for b in blocks) and any(b.startswith("2. Second") for b in blocks)


def test_an_empty_or_missing_dataset_is_a_source_problem_not_an_empty_answer(tmp_path):
    from lib.refcheck.sources import SourceDown

    with pytest.raises(SourceDown):
        SupremeCourtData(tmp_path)


def test_merge_keeps_the_neutral_citation_year_as_the_decision_year():
    a = scdata.Judgment(stem="1951_1_1_51", year=1951, neutral="1950 INSC 35")
    b = scdata.Judgment(stem="1951_1_1_51", year=1950, neutral="1950 INSC 35")
    [m] = scdata.merge_duplicates([a, b])
    assert m.year == 1950 and m.folders == [1950, 1951]
    assert date.fromisoformat("2026-10-17").year == 2026


def test_without_a_dataset_folder_every_case_reads_could_not_check(monkeypatch):
    from routers import authority

    monkeypatch.delenv("SC_DATA_DIR", raising=False)
    res = run(lookup.check_case(ref("Alpha Traders v. Beta Stores 2020 INSC 101"), authority.case_source()))
    assert res.label == COULD_NOT_CHECK and "not set up" in res.reason


def test_the_report_carries_the_source_line_and_the_not_checked_status(dataset):
    from lib.refcheck import report as rep

    built = run(rep.build(["Alpha Traders v. Beta Stores 2020 INSC 101 was decided."], dataset))
    assert built["source_attribution"]["text"].startswith("Source: ") and "data as of 2026-10-17" in built["source_attribution"]["text"]
    assert "CC-BY-4.0" in built["source_attribution"]["text"] and "not checked" in built["current_status"].lower()


def test_same_parties_in_the_other_order_found_by_names_only_is_not_a_mismatch(dataset):
    res = check(dataset, "Beta Stores v. Alpha Traders (2020) 7 SCC 1")
    assert res.label == COULD_NOT_CHECK and "other order" in res.reason


def test_the_dataset_is_loaded_once_at_start_up_and_a_missing_one_never_stops_the_server(dataset, monkeypatch, tmp_path):
    from routers import authority

    monkeypatch.setattr(authority, "_SOURCE", {})
    monkeypatch.setenv("AUTHORITY_CHECK_ENABLED", "true")
    monkeypatch.delenv("SC_DATA_DIR", raising=False)
    assert run(authority.warm_case_source()) is False  # no dataset configured: nothing to load
    monkeypatch.setenv("SC_DATA_DIR", str(dataset.root))
    assert run(authority.warm_case_source()) is True
    loaded = authority.case_source()
    assert isinstance(loaded, SupremeCourtData) and loaded is authority.case_source()  # the same copy is reused, never rebuilt per request
    monkeypatch.setenv("SC_DATA_DIR", str(tmp_path))  # a folder with no dataset in it
    assert run(authority.warm_case_source()) is False
    monkeypatch.setenv("AUTHORITY_CHECK_ENABLED", "false")
    assert run(authority.warm_case_source()) is False  # the feature is off: do not spend 12 seconds and 70 MB for nothing
