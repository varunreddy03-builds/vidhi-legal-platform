"""Checks on a draft before it leaves VIDHI. Pure code, no AI. It FLAGS and never rewrites: it has no wording of its own beyond the one-line message for each flag.

What it looks at (the answers given to the template are kept on the draft, so it can tell what the text should still say):
  open_item        a [square-bracket] item left open, or a {{marker}} that was never filled
  party_missing    a party's name (an answer ending in _name) no longer appears in the text
  name_differs     a name written almost, but not exactly, like the party's name (another spelling)
  answer_missing   a date or an amount the person entered no longer appears in the text
  amount_unknown   an amount in the text that is none of the amounts entered
  date_unknown     a date in the text that is none of the dates entered
  date_impossible  a date that does not exist (31 February)
  date_year        a year far from today (more than 30 years back or 10 ahead): likely a typing slip
  date_order       two dates entered that a template says must be in order (a field's "not_before") but are not

A draft that is not from a template gets only the checks that need no answers: open items, impossible dates and unlikely years.
The notice at the top of a template draft is skipped (it has the reviewer's date in it). Nothing here states a legal rule: the date order is chronology only, set by the template's own `not_before`."""

import re
from datetime import date
from difflib import SequenceMatcher

from lib import templates as tpl

MAX_CHARS = 200_000
BANNER_END = "Delete this note when the document is final."
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
TEXT_DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})\b")
OTHER_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
AMOUNT = re.compile(r"\bRs\.? ?\d[\d,]*(?:\.\d+)?")
LEFT_MARKER = re.compile(r"\{\{[^}\n]{1,60}\}\}")
NEAR = 0.8


def _flag(code: str, message: str, text: str, start: int, end: int, severity: str = "fix") -> dict:
    return {"code": code, "severity": severity, "message": message, "start": start, "end": end, "line": text.count("\n", 0, start) + 1, "snippet": text[start:end][:80]}


def _dates_in(text: str, offset: int):
    """(start, end, date or None) for every date written in the text."""
    for m in TEXT_DATE.finditer(text, offset):
        try:
            yield m.start(), m.end(), date(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))
        except ValueError:
            yield m.start(), m.end(), None
    for m in OTHER_DATE.finditer(text, offset):
        y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(5), m.group(4))
        try:
            yield m.start(), m.end(), date(int(y), int(mo), int(d))
        except ValueError:
            yield m.start(), m.end(), None


def _answers(template: dict, values: dict) -> dict[str, tuple[dict, str, str]]:
    """key -> (field, shown text, raw) for each answer the person gave. An answer that no longer fits the template is ignored, not an error."""
    out = {}
    fields = {f["key"]: f for f in template.get("fields", [])}
    for key, raw in (values or {}).items():
        f = fields.get(key)
        if not f or raw is None or str(raw).strip() == "":
            continue
        try:
            out[key] = (f, tpl.format_value(f, raw), str(raw).strip())
        except ValueError:
            continue
    return out


def _near_names(text: str, start: int, name: str, others: set[str]) -> list[tuple[int, int]]:
    """Places where the words of the text come close to `name` but are not it."""
    n = len(name.split())
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text) if m.start() >= start]
    found, i = [], 0
    while i + n <= len(words):
        s, e = words[i][0], words[i + n - 1][1]
        chunk = text[s:e].strip(".,;:()")
        s += len(text[s:e]) - len(text[s:e].lstrip(".,;:()"))
        e = s + len(chunk)
        if chunk != name and chunk not in others and SequenceMatcher(None, chunk.lower(), name.lower()).ratio() >= NEAR and chunk[:1].isupper():
            found.append((s, e))
            i += n
        else:
            i += 1
    return found


def check(body: str, template: dict | None = None, values: dict | None = None, today: date | None = None) -> list[dict]:
    """The flags for this text, in the order they appear. `template` and `values` are the template and the answers the draft was made from (None for any other draft)."""
    text = (body or "")[:MAX_CHARS]
    today = today or date.today()
    cut = text.find(BANNER_END)
    start = cut + len(BANNER_END) if cut >= 0 else 0
    flags: list[dict] = []

    for m in tpl.OPEN.finditer(text, start):
        flags.append(_flag("open_item", f"Still open: {m.group(0)[:80]}", text, m.start(), m.end()))
    for m in LEFT_MARKER.finditer(text, start):
        flags.append(_flag("open_item", "A marker was never filled in.", text, m.start(), m.end()))

    answers = _answers(template, values) if template and values else {}
    shown_dates = {s for f, s, _ in answers.values() if f["type"] == "date"}
    shown_amounts = {s for f, s, _ in answers.values() if f["type"] == "money"}
    name_keys = {k for k, (f, _s, _r) in answers.items() if f["type"] == "text" and k.endswith("_name") and f.get("required")}  # an optional name may sit in a clause that was not chosen
    names = {answers[k][1] for k in name_keys}

    written = {inr_text(m.group(0)) for m in AMOUNT.finditer(text, start)}  # amounts by value, however they are typed
    for key, (f, shown, _) in answers.items():
        if shown in text[start:] or (f["type"] == "money" and shown in written):
            continue
        if key in name_keys:
            flags.append(_flag("party_missing", f"{f['label']} (“{shown}”) is not in the text any more.", text, start, start))
        elif f["type"] in ("date", "money"):
            flags.append(_flag("answer_missing", f"{f['label']} (“{shown}”) is not in the text any more.", text, start, start, "look"))
    for name in sorted(names):
        for s, e in _near_names(text, start, name, names):
            flags.append(_flag("name_differs", f"Written “{text[s:e]}”, but the name entered is “{name}”.", text, s, e))

    if answers:
        for m in AMOUNT.finditer(text, start):
            if inr_text(m.group(0)) not in shown_amounts:
                flags.append(_flag("amount_unknown", f"{m.group(0)} is not one of the amounts entered.", text, m.start(), m.end(), "look"))

    for s, e, d in sorted(_dates_in(text, start)):
        if d is None:
            flags.append(_flag("date_impossible", "This date does not exist.", text, s, e))
        elif not today.year - 30 <= d.year <= today.year + 10:
            flags.append(_flag("date_year", f"The year {d.year} looks like a typing slip.", text, s, e, "look"))
        elif answers and d.strftime("%d %B %Y") not in shown_dates:
            flags.append(_flag("date_unknown", "This date is none of the dates entered.", text, s, e, "look"))

    for key, (f, shown, raw) in answers.items():
        other = answers.get(f.get("not_before", ""))
        if f["type"] == "date" and other:
            try:
                if date.fromisoformat(raw) < date.fromisoformat(other[2]):
                    flags.append(_flag("date_order", f"{f['label']} ({shown}) is earlier than {other[0]['label'].lower()} ({other[1]}).", text, start, start))
            except ValueError:
                pass

    return sorted(flags, key=lambda x: (x["start"], x["code"]))


def inr_text(written: str) -> str:
    """'Rs. 25000' -> 'Rs 25,000', the form the template prints, so an amount typed another way is still compared by value."""
    from decimal import Decimal, InvalidOperation

    try:
        return tpl.inr(Decimal(re.sub(r"[^\d.]", "", re.sub(r"^Rs\.?", "", written))))
    except InvalidOperation:
        return written


def summary(flags: list[dict]) -> dict:
    return {"fix": sum(1 for f in flags if f["severity"] == "fix"), "look": sum(1 for f in flags if f["severity"] == "look")}
