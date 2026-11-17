"""A notice's wording may not carry a sum of money that is not one of the figures VIDHI put in the statement of account."""

import pytest

from lib.notice_checks import find_stray_amounts, notice_blockers

STATEMENT = "\nStatement of account\n  + Invoice amount: 45,509.01 INR\n  - Payment received: 5,000.00 INR\n  = Balance due: 40,509.01 INR\n"


def notice(prose="The invoice remains unpaid."):
    return f"To: customer\n\n1. {prose}\n{STATEMENT}\nPlease pay within 15 days."


def test_a_notice_whose_wording_matches_the_statement_is_not_blocked():
    assert notice_blockers(notice("The balance of Rs 40,509.01 is unpaid."))["blocked"] is False


@pytest.mark.parametrize("prose", ["You owe Rs 99,99,999.", "You owe INR 1,00,000.", "You owe ₹ 45,000", "You owe Rs. 45509.00 today", "Pay 7,000 INR now"])
def test_a_figure_that_is_not_in_the_statement_blocks_the_notice(prose):
    out = notice_blockers(notice(prose))
    assert out["blocked"] and out["amount_mismatches"]


@pytest.mark.parametrize("prose", ["The balance is Rs 40,509.01.", "The balance is Rs 40509.01.", "You paid Rs 5,000 already.", "The invoice was for INR 45,509.01"])
def test_the_same_figure_written_differently_is_still_a_match(prose):
    assert find_stray_amounts(notice(prose)) == []


def test_days_dates_and_invoice_numbers_are_not_money():
    assert find_stray_amounts(notice("Invoice 1180 dated 12 March 2021 fell due 30 days later.")) == []


def test_every_stray_figure_is_listed_once():
    assert find_stray_amounts(notice("Rs 99,999 plus Rs 99,999 and Rs 12,345.")) == ["Rs 99,999", "Rs 12,345"]


def test_the_other_blockers_are_unchanged():
    out = notice_blockers(notice("Under Section 138 you must pay or we will call the police. [date]"))
    assert out["legal_references"] and out["risky_language"] and out["placeholders"] and out["amount_mismatches"] == [] and out["blocked"]


def test_a_notice_written_by_hand_without_a_statement_has_nothing_to_be_compared_with():
    assert find_stray_amounts('To: customer\n\nYou owe Rs 40,000 for goods delivered. Please pay within 15 days.') == []


def test_a_street_address_next_to_a_company_name_is_not_read_as_a_rupee_amount():
    """Found by the feature walk: 'Acme Traders 12 MG Road' contains 'rs 12' inside a word and blocked a clean notice."""
    from lib.notice_checks import _MONEY_RE

    def found(text):
        return [m.group(0).strip() for m in _MONEY_RE.finditer(text)]

    for text in ("Acme Traders 12 MG Road, Pune owes you.", "Mr Sharma of Roberts 40 Park Street.", "Partners 25 Lake Road.", "Flat 7 Gears 9 Lane."):
        assert found(text) == [], text
    assert found("Please pay Rs 5,000 now.") == ["Rs 5,000"]
    assert found("The sum is 1,200.00 INR in total.") == ["1,200.00 INR"]
    assert found("Pay Rs. 3,00,000/- within the time.")[0].startswith("Rs. 3,00,000")
    assert found("He owes 5000 rupees.") == ["5000 rupees"]
    assert found("Amount \u20b9 300 due") == ["\u20b9 300"]


def test_random_hex_text_can_look_like_an_amount_so_scenario_tests_must_not_use_it():
    """Root cause of the rare RS07 flake (found 2026-10-23): a test appended 'Note 3 aed1f2.' to a notice and 'aed1' was read as 'AED 1', so approval was refused.
    The checker is right to read a currency code next to a number as an amount; test text must be letters only."""
    from lib.notice_checks import _MONEY_RE

    def found(text):
        return [m.group(0) for m in _MONEY_RE.finditer(text)]

    assert found("Note 3 aed1f2.") == ["3 aed"]
    assert found("Note 3: ref aed1f2.") == ["aed1"]
    assert found("Note 3: ref hjkmnp.") == []


@pytest.mark.parametrize("prose", ["You owe Rs 10 lakh.", "You owe ₹5 crore", "You owe INR 1.5 lakh", "You owe 2 lakh rupees", "You owe Rs 40 thousand"])
def test_lakh_crore_thousand_are_read_as_their_full_value(prose):
    out = find_stray_amounts(notice(prose))
    assert out, prose  # none of these equals the 40,509.01 balance, and "Rs 10 lakh" must not pass as "10"


def test_a_scaled_figure_that_equals_a_statement_figure_matches():
    statement = "\nStatement of account\n  + Invoice amount: 1,000,000.00 INR\n  = Balance due: 1,000,000.00 INR\n"
    text = f"To: customer\n\n1. You owe Rs 10 lakh.\n{statement}\nPay soon."
    assert find_stray_amounts(text) == []
    assert find_stray_amounts(text.replace("10 lakh", "1 crore")) == ["Rs 1 crore"]


def test_a_sum_in_words_is_compared_and_an_unreadable_one_is_flagged():
    assert find_stray_amounts(notice("You owe Rupees six thousand.")) == ["Rupees six thousand"]
    assert find_stray_amounts(notice("You paid Rupees Five Thousand only.")) == []  # 5,000 is a statement figure
    assert find_stray_amounts(notice("You owe Rs. seven lakh twenty thousand.")) == ["Rs. seven lakh twenty thousand"]
    assert find_stray_amounts(notice("Rupees only")) == []
