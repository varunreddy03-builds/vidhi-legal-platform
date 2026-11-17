"""The date arithmetic of the 'Deadline engine'. Pure code: no database, no AI, no law.

Every choice that could be a legal choice is a field on the rule, set by the person who entered it and checked by the reviewer: whether the first day is counted (`count_from`), what happens when a
month is shorter than the starting day (`month_end`), and whether a non-working day moves the date (`when_not_working`). This file has no default for any of them: a rule that leaves one out is refused.
It returns the due date and every step of the working, so a lawyer can check it by hand."""

import calendar
from datetime import date, timedelta

UNITS = ("days", "weeks", "months", "years")
COUNT_FROM = ("day_after_start", "start_day_included")
MONTH_END = ("last_day_of_month", "first_day_of_next_month")
WHEN_NOT_WORKING = ("move_to_next_working_day", "leave_as_is")
MIN_YEAR, MAX_YEAR = 1900, 2100
MAX_AMOUNT = {"days": 36600, "weeks": 5200, "months": 1200, "years": 100}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class RuleError(ValueError):
    """The rule or the date cannot be used. The message is in plain words."""


def parse_day(value: str, what: str = "date") -> date:
    try:
        d = date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise RuleError(f"The {what} must be a real date written as YYYY-MM-DD.") from exc
    if not MIN_YEAR <= d.year <= MAX_YEAR:
        raise RuleError(f"The {what} must be between the years {MIN_YEAR} and {MAX_YEAR}.")
    return d


def check_rule(rule: dict) -> None:
    """Refuses a rule that leaves out a choice. Nothing is filled in for the person."""
    period = rule.get("period") or {}
    if period.get("unit") not in UNITS:
        raise RuleError(f"The period unit must be one of: {', '.join(UNITS)}.")
    amount = period.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= MAX_AMOUNT[period["unit"]]:
        raise RuleError(f"The period amount must be a whole number from 1 to {MAX_AMOUNT.get(period.get('unit'), 0)} {period.get('unit', '')}.")
    if rule.get("count_from") not in COUNT_FROM:
        raise RuleError(f"The rule must say how to count: {', '.join(COUNT_FROM)}.")
    if period["unit"] in ("months", "years") and rule.get("month_end") not in MONTH_END:
        raise RuleError(f"A period in months or years must say what happens when the month is shorter: {', '.join(MONTH_END)}.")
    if rule.get("when_not_working") not in WHEN_NOT_WORKING:
        raise RuleError(f"The rule must say what happens on a non-working day: {', '.join(WHEN_NOT_WORKING)}.")


def _add_months(d: date, months: int, month_end: str) -> tuple[date, str | None]:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise RuleError(f"The result would fall outside the years {MIN_YEAR} to {MAX_YEAR}.")
    last = calendar.monthrange(year, month)[1]
    if d.day <= last:
        return date(year, month, d.day), None
    if month_end == "last_day_of_month":
        return date(year, month, last), f"{d.day} does not exist in {calendar.month_name[month]} {year}, so the last day of that month was used, as the rule says."
    nxt = date(year, month, last) + timedelta(days=1)
    return nxt, f"{d.day} does not exist in {calendar.month_name[month]} {year}, so the first day of the next month was used, as the rule says."


def _is_off(d: date, weekend: set[int], holidays: dict[str, str]) -> str | None:
    if d.weekday() in weekend:
        return f"{WEEKDAYS[d.weekday()]} is a non-working weekday in the calendar"
    name = holidays.get(d.isoformat())
    return f"{d.isoformat()} is listed as a non-working day ({name}) in the calendar" if name is not None else None


def calculate(rule: dict, start: str, cal: dict | None = None) -> dict:
    """Due date for `start` under `rule`. `cal` is the rule's calendar: {"weekend_days": [0-6], "holidays": [{"date": "YYYY-MM-DD", "name": "..."}]}.
    Returns {"due": "YYYY-MM-DD", "weekday": name, "steps": [plain sentences], "moved": bool}."""
    check_rule(rule)
    d0 = parse_day(start, "start date")
    amount, unit = rule["period"]["amount"], rule["period"]["unit"]
    steps = [f"Start date: {d0.isoformat()} ({WEEKDAYS[d0.weekday()]})."]
    try:
        if unit in ("days", "weeks"):
            days = amount * (7 if unit == "weeks" else 1)
            due = d0 + timedelta(days=days)
            steps.append(f"Added {amount} {unit}" + (f" ({days} days)" if unit == "weeks" else "") + f": {due.isoformat()}.")
        else:
            months = amount * (12 if unit == "years" else 1)
            due, note = _add_months(d0, months, rule.get("month_end", ""))
            steps.append(f"Added {amount} {unit}" + (f" ({months} months)" if unit == "years" else "") + f": {due.isoformat()}.")
            if note:
                steps.append(note)
        if rule["count_from"] == "start_day_included":
            due -= timedelta(days=1)
            steps.append(f"The rule counts the start day itself as the first day, so one day was taken back: {due.isoformat()}.")
        else:
            steps.append("The rule counts from the day after the start day, so nothing was taken back.")
    except OverflowError as exc:
        raise RuleError(f"The result would fall outside the years {MIN_YEAR} to {MAX_YEAR}.") from exc

    moved = False
    if rule["when_not_working"] == "move_to_next_working_day":
        if not cal:
            raise RuleError("This rule moves a date off a non-working day, but no calendar was given.")
        weekend = {int(x) for x in cal.get("weekend_days", [])}
        holidays = {h["date"]: h.get("name", "") for h in cal.get("holidays", [])}
        for _ in range(400):
            why = _is_off(due, weekend, holidays)
            if why is None:
                break
            nxt = due + timedelta(days=1)
            steps.append(f"{due.isoformat()}: {why}, so the date moved to {nxt.isoformat()}, as the rule says.")
            due, moved = nxt, True
        else:
            raise RuleError("The calendar has no working day within 400 days of the due date, so no date was given.")
        if not moved:
            steps.append(f"{due.isoformat()} is a working day in the calendar, so it did not move.")
    else:
        steps.append("The rule leaves the date as it is on a non-working day, so no calendar was used.")
    if not MIN_YEAR <= due.year <= MAX_YEAR:
        raise RuleError(f"The result would fall outside the years {MIN_YEAR} to {MAX_YEAR}.")
    steps.append(f"Due date: {due.isoformat()} ({WEEKDAYS[due.weekday()]}).")
    return {"due": due.isoformat(), "weekday": WEEKDAYS[due.weekday()], "steps": steps, "moved": moved}
