"""Interest arithmetic: pure unit tests (no server)."""

from datetime import date, datetime

import pytest

from lib.interest import compute_simple_interest as calc


def test_one_year_simple_interest():
    r = calc(100000, [], "2025-01-01", 12, "2026-01-01")
    assert r["days"] == 365
    assert r["interest"] == 12000.0
    assert r["total_due"] == 112000.0
    assert len(r["segments"]) == 1 and r["segments"][0]["balance"] == 100000.0


def test_part_payment_reduces_the_base_from_its_date():
    # 6 months at 12% on 100,000, then 50,000 is paid, then 6 months on 50,000.
    r = calc(100000, [("2025-07-02", 50000)], "2025-01-01", 12, "2026-01-01")
    first = 100000 * 0.12 * 182 / 365
    second = 50000 * 0.12 * 183 / 365
    assert r["interest"] == pytest.approx(first + second, abs=0.01)
    assert r["principal_remaining"] == 50000.0
    assert [s["balance"] for s in r["segments"]] == [100000.0, 50000.0]


def test_payment_before_start_just_lowers_the_base():
    r = calc(100000, [("2024-12-01", 40000)], "2025-01-01", 10, "2026-01-01")
    assert r["interest"] == 6000.0 and r["principal_remaining"] == 60000.0


def test_overpayment_never_goes_negative_and_stops_interest():
    r = calc(1000, [("2025-02-01", 5000)], "2025-01-01", 10, "2026-01-01")
    assert r["principal_remaining"] == 0.0
    assert r["interest"] == pytest.approx(1000 * 0.10 * 31 / 365, abs=0.01)


def test_payment_after_as_of_is_ignored():
    r = calc(1000, [("2027-01-01", 500)], "2025-01-01", 10, "2026-01-01")
    assert r["principal_remaining"] == 1000.0 and r["payments_counted"] == 0.0


def test_as_of_before_start_is_zero_interest():
    r = calc(1000, [], "2026-06-01", 10, "2026-01-01")
    assert r["interest"] == 0.0 and r["days"] == 0 and r["segments"] == []


def test_zero_rate_is_zero_interest():
    assert calc(1000, [], "2025-01-01", 0, "2026-01-01")["interest"] == 0.0


def test_accepts_dates_datetimes_and_iso_strings():
    r = calc(1000, [(datetime(2025, 6, 1, 14, 30), 100)], date(2025, 1, 1), 12, "2025-12-31T10:00:00")
    assert r["days"] == 364 and r["payments_counted"] == 100.0


def test_rounds_half_up_to_paise():
    # 1 day at 36.5% on 1,000 = 1.00 exactly; 1 day at 18.25% on 1,000 = 0.50
    assert calc(1000, [], "2025-01-01", 36.5, "2025-01-02")["interest"] == 1.0
    assert calc(1000, [], "2025-01-01", 18.25, "2025-01-02")["interest"] == 0.5


@pytest.mark.parametrize("rate", [-1, 100.01, 250])
def test_rejects_unreasonable_rates(rate):
    with pytest.raises(ValueError):
        calc(1000, [], "2025-01-01", rate, "2026-01-01")


def test_states_its_assumptions_and_makes_no_legal_claim():
    r = calc(1000, [], "2025-01-01", 12, "2026-01-01")
    text = " ".join(r["assumptions"]).lower()
    assert "simple interest" in text and "not a statement of what a court would award" in text
    assert "section" not in text and "act" not in text.replace("actual", "")
