"""The date finder reads dates; it never corrects them, never decides what they mean, and marks the ones it could not read cleanly (pure code, no database, no AI)."""

from lib.datelist.extract import extract, extract_page


def raws(text, **kw):
    return [(f.raw, f.iso) for f in extract_page(text, 1, **kw)]


def test_the_common_indian_shapes_are_read():
    text = ("The notice was sent on 12/03/2021. The reply came on 5th April 2021 and the plaint was filed on May 3, 2022. "
            "The order is dated 2022-07-19, and the hearing on 21.11.2022 was adjourned to 4 Jan, 2023.")
    assert raws(text) == [("12/03/2021", "2021-03-12"), ("5th April 2021", "2021-04-05"), ("May 3, 2022", "2022-05-03"),
                          ("2022-07-19", "2022-07-19"), ("21.11.2022", "2022-11-21"), ("4 Jan, 2023", "2023-01-04")]


def test_a_numeric_date_that_could_swap_day_and_month_says_so_and_a_clear_one_does_not():
    ambiguous = extract_page("Filed on 03/04/2021.", 1)[0]
    assert ambiguous.iso == "2021-04-03" and any("month/day/year" in f for f in ambiguous.flags)
    clear = extract_page("Filed on 25/04/2021.", 1)[0]
    assert clear.iso == "2021-04-25" and clear.flags == []
    same = extract_page("Filed on 05/05/2021.", 1)[0]
    assert same.flags == []  # day and month are the same number, nothing to swap


def test_a_date_that_does_not_exist_is_shown_as_written_and_never_corrected():
    f = extract_page("The cheque dated 31/02/2021 was returned.", 1)[0]
    assert f.raw == "31/02/2021" and f.iso is None and any("not a real calendar date" in x for x in f.flags)
    swapped = extract_page("Dated 03/25/2021.", 1)[0]
    assert swapped.iso is None and any("month/day/year" in x for x in swapped.flags)  # fits only the other order: say so, do not guess
    assert extract_page("On 2021-02-30 it was signed.", 1)[0].iso is None


def test_two_digit_years_are_not_guessed_and_clause_numbers_are_not_dates():
    f = extract_page("Agreement dated 12/03/21.", 1)[0]
    assert f.iso is None and any("two digits" in x for x in f.flags)
    assert extract_page("See clause 3.1.12 and 1.2.20 of the lease.", 1) == []


def test_a_month_and_year_alone_is_listed_without_a_day():
    [f] = extract_page("The lease started in March 2019.", 1)
    assert f.iso is None and f.kind == "month_year" and any("no exact day" in x for x in f.flags)
    assert [x.kind for x in extract_page("On 12 March 2019 the lease started.", 1)] == ["day_month_year"]  # not also counted as a month-and-year


def test_a_date_later_than_today_is_noted_only_when_today_is_given():
    assert extract_page("Listed for 2030-01-10.", 1)[0].flags == []
    assert any("later than today" in x for x in extract_page("Listed for 2030-01-10.", 1, today="2026-10-28")[0].flags)


def test_every_appearance_keeps_its_own_page_and_sentence():
    pages = ["The loan was advanced on 01/06/2020.", "Nothing here.", "As stated, the loan was advanced on 01/06/2020 and not later."]
    found = extract(pages)
    assert [(f.page, f.iso) for f in found] == [(1, "2020-06-01"), (3, "2020-06-01")]
    assert "loan was advanced" in found[0].sentence and "not later" in found[1].sentence


def test_ordinary_words_and_numbers_are_not_dates():
    assert extract_page("Sections 12 and 13 apply. The sum of Rs 2,50,000 was paid in 3 instalments. The Court may 2 times adjourn.", 1) == []


def test_the_day_of_wording_and_dashed_month_names_are_read():
    got = {f.raw: (f.iso, f.flags) for f in extract(["This 3rd day of May 2020 the notice was sent. Paid on 12-Mar-2021 and again on 12-Mar-21. Also 31-Feb-2021."], today="2026-10-28")}
    assert got["3rd day of May 2020"][0] == "2020-05-03"  # not read as the month only
    assert got["12-Mar-2021"][0] == "2021-03-12"
    assert got["12-Mar-21"][0] is None and "two digits" in got["12-Mar-21"][1][0]  # shown, never guessed
    assert got["31-Feb-2021"][0] is None and "not a real calendar date" in got["31-Feb-2021"][1][0]
    assert "May 2020" not in got  # no second, month-only entry for the same words


def test_hostile_text_cannot_tie_up_the_server():
    import time

    for text in ("1/1/" * 75_000, "12 Mar " * 40_000, "May" + " " * 200_000 + "x", "2021-" * 50_000):
        t0 = time.perf_counter()
        extract([text], today="2026-10-28")
        assert time.perf_counter() - t0 < 8, text[:20]
