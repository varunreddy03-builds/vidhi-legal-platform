"""Builds the 'Old-code to new-code checker' report from a draft's pages. Plain code, no AI.

It lists every place the draft names the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act (see check.py). For each section it asks VIDHI's own store of
old-to-new mappings (lib/code_mappings.py) and shows ONLY mappings a named reviewer has marked reviewed. Nothing is mapped from memory, and nothing says which code applies to a matter.
Page numbers follow the same rule as the list of dates: a PDF has real pages; a Word or text file does not, so it says "page not available" and gives the part of the file."""

import os

from lib import code_mappings
from lib.datelist.report import page_kind, _where  # noqa: F401  (the same page rule as the list of dates)
from lib.oldcode import check

NOTICE = ("This lists where the draft names the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act, and the section numbers written there. "
          "A newer section is shown only if a named reviewer has marked a mapping as reviewed. Where none is recorded, that does not mean none exists. "
          "It does not say which code applies to a matter: that depends on dates and transitional rules, and a lawyer decides.")
KIND_LABELS = {"section": "Section reference", "mention": "Act named"}
MAX_FINDINGS = 1000
MAX_DISTINCT = 300
SENTENCE_MAX = 300


def enabled() -> bool:
    return os.environ.get("OLD_CODE_CHECK_ENABLED", "false").lower() == "true"


class TooManyFindings(Exception):
    def __init__(self, n: int):
        super().__init__(n)
        self.n = n


async def _mapping_for(act: str, section: str) -> dict:
    """What the reviewed store says about one older section. Unreviewed entries are counted, never shown as an answer."""
    res = await code_mappings.lookup(section, check.ACT_NAME[act])
    reviewed = [{"relationship": m["relationship"], "equivalence": m["equivalence_label"], "new": [r["citation"] for r in m["new"]], "authorities": m["authorities"], "reviewed_by": m.get("reviewed_by")}
                for m in res["verified_mappings"]]
    unreviewed = len(res["mappings"]) - len(reviewed)
    # What an official table says but no named reviewer has checked: shown, plainly labelled, and never counted as an answer (status stays "none").
    draft = [{"relationship": m["relationship"], "equivalence": m["equivalence_label"], "new": [r["citation"] for r in m["new"]], "authorities": m["authorities"]}
             for m in res["mappings"] if not m.get("verified")][:5]
    out = {"status": "reviewed" if reviewed else "none", "reviewed": reviewed, "unreviewed_count": unreviewed, "unreviewed": draft}
    if not reviewed:
        out["message"] = code_mappings.NO_MAPPING
    return out


async def build(pages: list[str], kind: str) -> dict:
    found = check.check(pages)
    if len(found) > MAX_FINDINGS:
        raise TooManyFindings(len(found))
    distinct = sorted({(f.act, f.section) for f in found if f.kind == "section"})
    if len(distinct) > MAX_DISTINCT:
        raise TooManyFindings(len(found))
    mapped = {key: await _mapping_for(*key) for key in distinct}
    total = len(pages)
    items = []
    for n, f in enumerate(found, 1):
        page, where = _where(kind, f.page, total)
        item = {"n": n, "kind": f.kind, "label": KIND_LABELS[f.kind], "act": f.act, "act_name": check.ACT_NAME[f.act], "section": f.section, "raw": f.raw,
                "sentence": f.sentence[:SENTENCE_MAX], "note": f.note, "page": page, "where": where, "part": f.page, "mapping": mapped.get((f.act, f.section))}
        items.append(item)
    return {"items": items, "counts": counts(items), "page_kind": kind, "notice": NOTICE, "caveat": code_mappings.CAVEAT}


def counts(items: list[dict]) -> dict:
    by_act: dict[str, int] = {}
    for i in items:
        by_act[i["act"]] = by_act.get(i["act"], 0) + 1
    sections = [i for i in items if i["kind"] == "section"]
    return {"total": len(items), "by_act": by_act, "sections": len(sections), "with_reviewed_mapping": sum(1 for i in sections if i["mapping"]["status"] == "reviewed")}
