"""Builds the 'Pre-filing defect check' report from a draft's pages. Plain code, no AI.

It lists drafting slips (see check.py) with the sentence, where in the file each one is, and a plain note on why it may not be a slip. It knows no court's rules.
Page numbers follow the same rule as the list of dates: a PDF has real pages; a Word or text file does not, so it says "page not available" and gives the part of the file."""

import os

from lib.datelist.report import page_kind, _where  # noqa: F401  (the same page rule as the list of dates)
from lib.defects import check

NOTICE = ("This points to drafting slips that may need a look before filing: blanks, numbering, annexure labels, paragraph references and doubled words. "
          "It does not know any court's rules, so it cannot say a filing will be accepted or rejected, and it does not say a draft is defective. Each note says why it may not be a slip. A lawyer decides.")
KIND_LABELS = {
    "blank": "Blank or placeholder", "numbering_gap": "Numbering skips", "numbering_repeat": "Number repeated", "annexure_gap": "Annexure label missing",
    "dangling_reference": "Paragraph reference", "repeated_word": "Word typed twice",
}
MAX_FINDINGS = 1000
SENTENCE_MAX = 300


def enabled() -> bool:
    return os.environ.get("DEFECT_CHECK_ENABLED", "false").lower() == "true"


class TooManyFindings(Exception):
    def __init__(self, n: int):
        super().__init__(n)
        self.n = n


def build(pages: list[str], kind: str) -> dict:
    found = check.check(pages)
    if len(found) > MAX_FINDINGS:
        raise TooManyFindings(len(found))
    total = len(pages)
    items = []
    for n, f in enumerate(found, 1):
        page, where = _where(kind, f.page, total)
        items.append({"n": n, "kind": f.kind, "label": KIND_LABELS[f.kind], "raw": f.raw, "sentence": f.sentence[:SENTENCE_MAX], "note": f.note, "page": page, "where": where, "part": f.page})
    return {"items": items, "counts": counts(items), "page_kind": kind, "notice": NOTICE}


def counts(items: list[dict]) -> dict:
    by_kind: dict[str, int] = {}
    for i in items:
        by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1
    return {"total": len(items), "by_kind": by_kind}
