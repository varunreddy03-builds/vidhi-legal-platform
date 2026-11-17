"""Deadline engine arithmetic, on INVENTED rules only (no real period, court rule or holiday appears here). The engine has no legal defaults: a rule that leaves a choice out is refused (pure code, no database)."""

from pathlib import Path

import pytest

from lib.deadlinerules import compute
from lib.deadlinerules.compute import RuleError, calculate

ROOT = Path(__file__).resolve().parent.parent


def rule(amount=30, unit="days", count_from="day_after_start", month_end=None, when_not_working="leave_as_is"):
    r = {"period": {"amount": amount, "unit": unit}, "count_from": count_from, "when_not_working": when_not_working}
    if month_end:
        r["month_end"] = month_end
    return r


def test_days_and_weeks_are_added_and_the_start_day_is_counted_only_if_the_rule_says_so():
    assert calculate(rule(30), "2030-01-10")["due"] == "2030-02-09"
    assert calculate(rule(30, count_from="start_day_included"), "2030-01-10")["due"] == "2030-02-08"
    assert calculate(rule(2, "weeks"), "2030-01-10")["due"] == "2030-01-24"


def test_months_and_years_use_the_month_end_choice_written_on_the_rule():
    assert calculate(rule(1, "months", month_end="last_day_of_month"), "2030-01-31")["due"] == "2030-02-28"
    assert calculate(rule(1, "months", month_end="first_day_of_next_month"), "2030-01-31")["due"] == "2030-03-01"
    assert calculate(rule(1, "months", month_end="last_day_of_month"), "2032-01-31")["due"] == "2032-02-29"  # a leap year
    assert calculate(rule(1, "years", month_end="last_day_of_month"), "2032-02-29")["due"] == "2033-02-28"
    assert calculate(rule(3, "months", month_end="last_day_of_month"), "2030-11-15")["due"] == "2031-02-15"  # crosses a year end
    steps = " ".join(calculate(rule(1, "months", month_end="last_day_of_month"), "2030-01-31")["steps"])
    assert "does not exist" in steps and "as the rule says" in steps  # the working says what it did and why


def test_a_date_on_a_non_working_day_moves_only_if_the_rule_says_so_and_each_move_is_shown():
    cal = {"weekend_days": [5, 6], "holidays": [{"date": "2030-01-14", "name": "Invented Day"}]}
    r = rule(2, when_not_working="move_to_next_working_day")  # 2030-01-10 is a Thursday; +2 days is Saturday the 12th
    got = calculate(r, "2030-01-10", cal)
    assert got["due"] == "2030-01-15" and got["moved"] is True and got["weekday"] == "Tuesday"
    text = " ".join(got["steps"])
    assert "Saturday is a non-working weekday" in text and "Sunday is a non-working weekday" in text and "Invented Day" in text
    stay = calculate(rule(2), "2030-01-10")  # the same dates, but this rule leaves the date alone
    assert stay["due"] == "2030-01-12" and stay["moved"] is False and "leaves the date as it is" in " ".join(stay["steps"])
    easy = calculate(rule(1, when_not_working="move_to_next_working_day"), "2030-01-10", cal)
    assert easy["due"] == "2030-01-11" and easy["moved"] is False and "did not move" in " ".join(easy["steps"])


@pytest.mark.parametrize("bad", [
    {},
    {"period": {"amount": 30, "unit": "days"}, "when_not_working": "leave_as_is"},  # no count_from
    {"period": {"amount": 30, "unit": "days"}, "count_from": "day_after_start"},  # no when_not_working
    {"period": {"amount": 1, "unit": "months"}, "count_from": "day_after_start", "when_not_working": "leave_as_is"},  # months without month_end
    {"period": {"amount": 0, "unit": "days"}, "count_from": "day_after_start", "when_not_working": "leave_as_is"},
    {"period": {"amount": True, "unit": "days"}, "count_from": "day_after_start", "when_not_working": "leave_as_is"},
    {"period": {"amount": 30, "unit": "fortnights"}, "count_from": "day_after_start", "when_not_working": "leave_as_is"},
    {"period": {"amount": 99999, "unit": "years"}, "count_from": "day_after_start", "when_not_working": "leave_as_is"},
    {"period": {"amount": 30, "unit": "days"}, "count_from": "maybe", "when_not_working": "leave_as_is"},
    {"period": {"amount": 30, "unit": "days"}, "count_from": "day_after_start", "when_not_working": "sometimes"},
])
def test_a_rule_that_leaves_a_choice_out_or_gives_nonsense_is_refused_never_filled_in(bad):
    with pytest.raises(RuleError):
        calculate(bad, "2030-01-10")


def test_bad_dates_and_missing_calendars_are_refused_in_plain_words():
    for start in ("", "2030-02-30", "10/01/2030", "1800-01-01", "2200-01-01", "not a date"):
        with pytest.raises(RuleError, match="start date"):
            calculate(rule(), start)
    with pytest.raises(RuleError, match="no calendar was given"):
        calculate(rule(2, when_not_working="move_to_next_working_day"), "2030-01-10")
    with pytest.raises(RuleError, match="no working day within 400 days"):
        calculate(rule(2, when_not_working="move_to_next_working_day"), "2030-01-10", {"weekend_days": [0, 1, 2, 3, 4, 5, 6], "holidays": []})
    with pytest.raises(RuleError, match="outside the years"):
        calculate(rule(5, "years", month_end="last_day_of_month"), "2099-06-01")


def test_the_engine_names_no_act_court_or_period_of_its_own():
    source = (ROOT / "lib" / "deadlinerules" / "compute.py").read_text(encoding="utf-8").lower()
    for word in ("limitation act", "civil procedure", "high court", "supreme court", "section 12", "appeal", "negotiable", "holiday list"):
        assert word not in source, word
    assert compute.UNITS == ("days", "weeks", "months", "years")  # only units of time are known
