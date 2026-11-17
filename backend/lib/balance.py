"""The outstanding balance of a recovery case: plain arithmetic in code, never asked of an AI.

    balance = invoice amount + charges (each with a written basis) - payments received - credits

* The invoice amount is the figure the OWNER entered. An amount an AI "found" in a document is only ever a
  suggestion the owner can accept; it never replaces the owner's figure.
* A charge (late fee, agreed interest, delivery cost...) counts only if it has a documented basis typed next
  to it ("clause 4 of the agreement dated ..."). Without one it is listed as ignored, not silently added.
* Interest, penalties and advocate fees are NOT added here at all. Interest is a separate, optional,
  clearly labelled calculation (lib/interest.py) that the owner switches on by entering a rate.
* Money is handled as Decimal and rounded to paise only at the end.
"""

from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")


def _d(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception:  # noqa: BLE001
        return Decimal(0)


def _money(x: Decimal) -> float:
    return float(x.quantize(TWO, rounding=ROUND_HALF_UP))


def credits_of(case: dict) -> list[dict]:
    return [c for c in case.get("credits", []) or [] if _d(c.get("amount")) > 0]


def interest_principal(case: dict) -> float:
    """What interest (if the owner asks for it) is counted on: the invoice amount the OWNER entered, less credits. Never charges, never an amount an AI found."""
    base = _d(case.get("amount"))
    return _money(max(Decimal(0), base - sum((_d(c.get("amount")) for c in credits_of(case)), Decimal(0))))


def owed_amount(case: dict) -> float:
    """Invoice amount (as the owner entered it) + charges that have a written basis - credits: what was owed before payments. One calculation only: see `position`."""
    return position(case)["owed"]


def fmt_money(x, currency: str = "INR", symbol: str | None = None) -> str:
    """12,345.60 INR, or with a symbol ("Rs 12,345.60"): always two decimals, so the paise are never lost."""
    value = _money(_d(x))
    if symbol:
        return f"{symbol}{value:,.2f}" if len(symbol) == 1 else f"{symbol} {value:,.2f}"  # ₹1,500.75 but Rs 1,500.75
    return f"{value:,.2f} {currency}"


def position(case: dict) -> dict:
    """Owed, received and remaining as exact two-decimal numbers from ONE calculation (so the three always add up): remaining = owed - received, never below 0."""
    bal = compute_balance(case)
    owed = _d(bal["invoice_amount"]) + _d(bal["charges_total"]) - _d(bal["credits_total"])
    received = _d(bal["payments_total"])
    return {"owed": _money(max(Decimal(0), owed)), "received": _money(received), "remaining": bal["balance"], "currency": bal["currency"], "overpaid": bal["overpaid"]}


def compute_balance(case: dict) -> dict:
    """An itemised, checkable working. `lines` is what the owner (and the notice) shows, in order."""
    currency = case.get("currency") or "INR"
    invoice = _d(case.get("amount"))
    detected = case.get("detected_amount")
    warnings: list[str] = []
    ignored: list[dict] = []
    lines: list[dict] = []

    if invoice <= 0:
        warnings.append(
            "Enter the invoice amount yourself to see the balance."
            + (f" Your documents seem to show {detected:,.2f} {currency}; use it only if it is right." if detected else "")
        )
    elif detected and _d(detected) != invoice:
        warnings.append(
            f"The amount read from your documents ({float(_d(detected)):,.2f} {currency}) is different from the "
            f"invoice amount you entered ({_money(invoice):,.2f}). The balance uses the amount YOU entered - check which is right."
        )
    inv_no = ((case.get("intake") or {}).get("invoice_number") or "").strip()
    lines.append({"kind": "INVOICE", "label": "Invoice amount" + (f" (invoice {inv_no})" if inv_no else ""), "amount": _money(invoice), "sign": 1})

    total = invoice
    for c in case.get("charges", []) or []:
        amt = _d(c.get("amount"))
        if amt <= 0:
            continue
        if not str(c.get("basis") or "").strip():
            ignored.append({"label": c.get("label", "Charge"), "amount": _money(amt), "reason": "no written basis was given, so it is not counted"})
            continue
        total += amt
        lines.append({"kind": "CHARGE", "label": c.get("label") or "Charge", "amount": _money(amt), "sign": 1, "basis": c["basis"]})

    credit_total = Decimal(0)
    for c in credits_of(case):
        amt = _d(c.get("amount"))
        total -= amt
        credit_total += amt
        lines.append({"kind": "CREDIT", "label": c.get("label") or "Credit", "amount": _money(amt), "sign": -1, "reason": c.get("reason", "")})

    paid = Decimal(0)
    for p in case.get("payments", []) or []:
        amt = _d(p.get("amount"))
        paid += amt
        lines.append({"kind": "PAYMENT", "label": "Payment received", "date": str(p.get("date", ""))[:10], "amount": _money(amt), "sign": -1})
    total -= paid

    overpaid = total < 0
    if overpaid:
        warnings.append("Payments and credits are more than the amount owed. No balance is due; check the figures.")
    return {
        "currency": currency,
        "lines": lines,
        "ignored_charges": ignored,
        "invoice_amount": _money(invoice),
        "charges_total": _money(sum((_d(l["amount"]) for l in lines if l["kind"] == "CHARGE"), Decimal(0))),
        "credits_total": _money(credit_total),
        "payments_total": _money(paid),
        "balance": _money(max(Decimal(0), total)),
        "overpaid": overpaid,
        "suggested_amount": float(_d(detected)) if detected and invoice <= 0 else None,
        "warnings": warnings,
        "formula": "Balance = invoice amount + charges that have a written basis - payments received - credits. "
        "Interest, penalties and advocate fees are not included unless you add them with a documented basis.",
    }


def statement_text(bal: dict, interest: dict | None = None, start_text: str = "", end_text: str = "") -> str:
    """The calculation as plain text for the notice, generated here so the AI never types a figure.

    With `interest` (an optional, owner-requested simple-interest working) two more lines follow: the interest, and the TOTAL INCLUDING INTEREST, which is the balance
    (charges included) plus the interest. `start_text` and `end_text` are the dates as the notice prints them."""
    cur = bal["currency"]
    rows = []
    for l in bal["lines"]:
        sign = "+" if l["sign"] > 0 else "-"
        extra = f" ({l['basis']})" if l.get("basis") else (f" ({l['date']})" if l.get("date") else "")
        rows.append(f"  {sign} {l['label']}{extra}: {l['amount']:,.2f} {cur}")
    rows.append(f"  = Balance due: {bal['balance']:,.2f} {cur}")
    if interest is not None:
        total = _money(_d(bal["balance"]) + _d(interest["interest"]))
        rows.append(f"  Interest claimed separately: {interest['interest']:,.2f} {cur} (simple interest at {interest['rate_pct']:g}% a year from {start_text} to {end_text}, on the amount outstanding)")
        rows.append(f"  Total including interest: {total:,.2f} {cur}")
    return "Statement of account\n" + "\n".join(rows)