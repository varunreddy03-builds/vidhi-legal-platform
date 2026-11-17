"""A claim that says the opposite of its quote (is / is not) can never be VERIFIED: it is held at PARTIALLY_VERIFIED with the reason. The check only ever adds a caution."""

import pytest

from lib.textmatch import norm, polarity_differs
from tests.conftest import answer, new_matter, stub, upload
from tests.test_truth_engine import claim, lib_cite, research


def span(text, quote):
    t = norm(text)
    i = t.find(norm(quote))
    assert i >= 0
    return [(t, i, i + len(norm(quote)))]


FEE = "A lender shall not charge any fee for the return of a widget."


@pytest.mark.parametrize("claim_text,expected", [
    ("A lender may charge a fee for the return of a widget.", True),          # says the opposite
    ("A lender cannot charge any fee for the return of a widget.", False),    # both negative
    ("No fee may be charged by a lender for the return of a widget.", False), # both negative, different words
    ("A lender must not charge a fee on return.", False),
    ("A lender never charges a fee for returns.", False),
])
def test_opposite_polarity_is_found_in_english(claim_text, expected):
    assert polarity_differs(claim_text, span(FEE, "shall not charge any fee for the return of a widget")) is expected


PROHIBITED = "A lender is prohibited from charging any fee for the return of a widget."


@pytest.mark.parametrize("claim_text,expected", [
    ("A lender may charge a fee for the return of a widget.", True),           # the reversal the first version missed
    ("A lender shall not charge any fee for the return of a widget.", False),  # same meaning in other words: no false alarm
    ("A lender is forbidden to charge a fee for the return of a widget.", False),
])
def test_prohibition_words_count_as_a_reversal(claim_text, expected):
    assert polarity_differs(claim_text, span(PROHIBITED, "is prohibited from charging any fee for the return of a widget")) is expected


@pytest.mark.parametrize("claim_text", [
    "A lender may charge a fee unless the widget is damaged.",  # its own "unless" must not cancel the quote's "not"
    "A lender may charge a fee without limit.",
    "A lender may charge a fee except for late returns.",
])
def test_an_exception_word_in_the_claim_does_not_hide_a_reversal(claim_text):
    assert polarity_differs(claim_text, span("A lender shall not charge any fee for the return of a widget.", "shall not charge any fee for the return of a widget"))


def test_a_missing_exception_is_found():
    quote = "shall pay rent unless the premises are unusable"
    assert polarity_differs("A tenant must always pay rent.", span("A tenant shall pay rent unless the premises are unusable.", quote))
    assert not polarity_differs("A tenant must pay rent unless the premises are unusable.", span("A tenant shall pay rent unless the premises are unusable.", quote))


def test_a_positive_quote_with_a_negative_claim_is_found():
    assert polarity_differs("The borrower does not have to return it.", span("Any person who borrows a widget shall return the widget to the lender.", "shall return the widget to the lender"))


def test_case_number_abbreviations_are_not_negations():
    assert not polarity_differs("The order in Case No. 5 of 2020 was passed.", span("Order passed in Case No. 5 of 2020 by the court.", "Case No. 5 of 2020 by the court"))


def test_other_scripts_and_empty_quotes_are_left_alone():
    telugu = "చెల్లింపు 45 రోజుల్లో చేయాలి కాదు"
    assert polarity_differs(telugu, span(telugu, "45 రోజుల్లో చేయాలి")) is False
    assert polarity_differs("A claim with no quote", []) is False


def test_end_to_end_the_opposite_of_the_law_is_not_verified_and_the_right_reading_is(user_a):
    mid, title = new_matter(user_a)
    upload(user_a, mid, "01.txt", f"Ravi lent a widget. {title}")
    quote = "shall not charge any fee for the return of a widget"
    claims = [
        claim("A lender may charge a fee for the return of a widget.", "LEGAL", cites=[lib_cite("test-widget-2", quote)]),
        claim("A lender must not charge any fee for the return of a widget.", "LEGAL", cites=[lib_cite("test-widget-2", quote)]),
    ]
    stub("research", answer("Answer.", claims), contains=title)
    r = research(user_a, mid, "May a lender charge a fee when a widget is returned?").json()
    wrong, right = r["claims"]
    assert wrong["verification_status"] == "PARTIALLY_VERIFIED" and "is or is not so" in wrong["note"]
    assert right["verification_status"] == "VERIFIED"
