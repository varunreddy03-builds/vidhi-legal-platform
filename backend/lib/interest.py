"""Simple-interest calculator for recovery cases. Pure arithmetic - no AI, no legal assumptions.

The RATE always comes from the user (what was agreed, or what they choose to claim). This module only
does the sums, shows its working, and states its assumptions so a lawyer can check or change them.

Method: simple interest on the outstanding principal, actual days / 365. Part-payments reduce the
principal from their payment date (they are not applied to interest first).
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")

ASSUMPTIONS = [
    "Simple interest (not compounded), counted on actual days over a 365-day year.",
    "Interest runs from the due date you entered until the 'as of' date.",
    "Each part-payment reduces the amount owed from the day it was received (it is not applied to interest first).",
    "The rate is the one you entered. It is not a statement of what a court would award.",
]


def _d(value) -> Decimal:
    return Decimal(str(value))


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _money(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def compute_simple_interest(
    principal: float,
    payments: list[tuple],
    start,
    rate_pct: float,
    as_of,
) -> dict:
    """payments: [(date_or_datetime_or_iso, amount)]. Returns a fully itemised result."""
    rate = _d(rate_pct)
    if rate < 0 or rate > 100:
        raise ValueError("Interest rate must be between 0 and 100 per cent a year.")
    principal_d = _d(principal)
    if principal_d < 0:
        raise ValueError("Amount owed cannot be negative.")
    start_d, end_d = _as_date(start), _as_date(as_of)

    pays = sorted(((_as_date(d), _d(a)) for d, a in payments), key=lambda p: p[0])
    balance = principal_d
    # Payments on/before the start date simply reduce what the interest is counted on.
    rest: list[tuple[date, Decimal]] = []
    for pd, amt in pays:
        if pd <= start_d:
            balance = max(Decimal(0), balance - amt)
        else:
            rest.append((pd, amt))

    segments: list[dict] = []
    total = Decimal(0)
    cursor = start_d

    def accrue(upto: date) -> None:
        nonlocal total, cursor
        days = (upto - cursor).days
        if days > 0 and balance > 0:
            interest = balance * rate / Decimal(100) * Decimal(days) / Decimal(365)
            total += interest
            segments.append(
                {
                    "from": cursor.isoformat(),
                    "to": upto.isoformat(),
                    "days": days,
                    "balance": float(_money(balance)),
                    "interest": float(_money(interest)),
                }
            )
        if upto > cursor:
            cursor = upto

    for pd, amt in rest:
        if pd > end_d:
            break
        accrue(pd)
        balance = max(Decimal(0), balance - amt)
    accrue(end_d)

    paid_after_start = sum((a for d, a in rest if d <= end_d), Decimal(0))
    interest = _money(total)
    remaining = _money(balance)
    return {
        "principal": float(_money(principal_d)),
        "rate_pct": float(rate),
        "start": start_d.isoformat(),
        "as_of": end_d.isoformat(),
        "days": max(0, (end_d - start_d).days),
        "interest": float(interest),
        "principal_remaining": float(remaining),
        "total_due": float(_money(remaining + interest)),
        "payments_counted": float(_money(paid_after_start)),
        "segments": segments,
        "assumptions": ASSUMPTIONS,
    }
