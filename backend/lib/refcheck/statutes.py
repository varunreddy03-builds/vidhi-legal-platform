"""Statute references in a draft, checked against OUR reviewed library only (Stage 2c).

What this says, and what it never says:
* FOUND_REVIEWED / FOUND_NOT_REVIEWED: a provision with that number exists in the loaded library for an Act matching the draft's wording. It does NOT say the draft
  describes it correctly, and it does NOT say the provision is in force: current status is never checked.
* NOT_IN_REVIEWED_LIBRARY: we do not hold it. That is a statement about our library, never about the law: a missing provision is not a wrong citation.
* COULD_NOT_CHECK: the library could not be read.
* old_code_note: the draft names the Indian Penal Code, Code of Criminal Procedure or Indian Evidence Act (or IPC / CrPC / Evidence Act). The note only says that
  Bharatiya Nyaya Sanhita, Bharatiya Nagarik Suraksha Sanhita and Bharatiya Sakshya Adhiniyam exist and that the lawyer must check which applies to the dates in
  the matter. No section is ever mapped from the old number to a new one here: that would be law written from memory."""

import re
from dataclasses import dataclass, field

from lib import legal_search

OLD_CODE_NOTE = (
    "This names an older code (Indian Penal Code, Code of Criminal Procedure or Indian Evidence Act). The Bharatiya Nyaya Sanhita, Bharatiya Nagarik Suraksha Sanhita "
    "and Bharatiya Sakshya Adhiniyam exist. Which law applies depends on the dates in the matter; please check it. VIDHI does not convert section numbers."
)
FOUND_REVIEWED, FOUND_NOT_REVIEWED, NOT_IN_LIBRARY, COULD_NOT_CHECK = "FOUND_REVIEWED", "FOUND_NOT_REVIEWED", "NOT_IN_REVIEWED_LIBRARY", "COULD_NOT_CHECK"
CURRENT_STATUS = "current status: not checked"


@dataclass
class StatuteResult:
    raw: str
    page: int
    label: str
    reason: str
    old_code_note: str = ""
    per_provision: list[dict] = field(default_factory=list)
    current_status: str = CURRENT_STATUS


def numbers(ref_number: str) -> list[str]:
    """'138 and 141', '34(1)', '302, 304B' -> ['138', '141'], ['34'], ['302', '304B']. Sub-sections are not looked up separately."""
    out = []
    for part in re.split(r"\s*(?:,|and|&|to)\s*", ref_number or ""):
        m = re.match(r"\d+[A-Za-z]{0,2}", part.strip())
        if m and m.group(0).upper() not in out:
            out.append(m.group(0).upper())
    return out


async def check_statute(ref, on_date: str | None = None, lookup=None) -> StatuteResult:
    lookup = lookup or legal_search.lookup
    note = OLD_CODE_NOTE if getattr(ref, "old_code", False) else ""
    nums = numbers(ref.number)
    if not nums:
        return StatuteResult(ref.raw, ref.page, COULD_NOT_CHECK, "No section or article number could be read from this reference.", note)
    rows, labels = [], []
    for n in nums:
        try:
            entries = await lookup(n, ref.act or None, on_date)
        except Exception:  # noqa: BLE001 - an unreadable library is "could not check", never "not in library"
            return StatuteResult(ref.raw, ref.page, COULD_NOT_CHECK, "The reviewed library could not be read just now. Nothing was concluded.", note)
        provs = [p for e in entries for p in e["provisions"]]
        if not provs:
            rows.append({"number": n, "label": NOT_IN_LIBRARY})
            labels.append(NOT_IN_LIBRARY)
            continue
        reviewed = all(p["review"]["status"] == "reviewed" for p in provs)
        label = FOUND_REVIEWED if reviewed else FOUND_NOT_REVIEWED
        labels.append(label)
        rows.append({"number": n, "label": label, "provisions": [{"id": p["id"], "instrument": p["instrument"], "heading": p["heading"], "version": p["version"]["note"], "review": p["review"]["statement"], "source_url": p["source"]["url"]} for p in provs]})
    if all(x == FOUND_REVIEWED for x in labels):
        label, reason = FOUND_REVIEWED, "Every cited provision is in our library and was compared with the official text by a named reviewer. This does not say the draft describes it correctly or that it is in force."
    elif NOT_IN_LIBRARY in labels:
        label, reason = NOT_IN_LIBRARY, "At least one cited provision is not in our reviewed library. That says nothing about whether it exists: please check the official text."
    else:
        label, reason = FOUND_NOT_REVIEWED, "The provision is in our library but no lawyer has compared it with the official text yet. Do not rely on it as verified."
    return StatuteResult(ref.raw, ref.page, label, reason, note, rows)
