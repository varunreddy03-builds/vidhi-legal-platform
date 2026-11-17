"""The Katalyst checks for a word processor's side panel (Word, Google Docs): one call, paragraph by paragraph, with exact character positions.

Plain code, no AI: it reuses the same readers as the five Legal Katalyst tools (Authority Check, old-code checker, defect check, list of dates). Text in the document is data to read and is
never an instruction to anything. Nothing here invents law:
- a "suggested replacement" exists ONLY when a named reviewer has marked a one-to-one, exact mapping in the reviewed store (lib/code_mappings.py) and the text names exactly one section;
- a citation is VERIFIED only when the provision is in the reviewed library; a case found in the open dataset is at most PARTLY_VERIFIED, because that dataset is not reviewed here;
- every old-code finding carries the fixed caveat that VIDHI has not decided which text applies to a matter.
Positions are Python string offsets into the paragraph text that was sent (start_index inclusive, end_index exclusive); the panel converts them for its own editor."""

import re
from dataclasses import dataclass

from lib import code_mappings
from lib.datelist import extract as date_extract
from lib.defects import check as defect_check
from lib.oldcode import check as old_check
from lib.refcheck import lookup, propositions, quotes, report as authority_report, statutes
from lib.refcheck.lookup import LookupCapExceeded

VERIFIED, PARTLY_VERIFIED, NOT_SUPPORTED = "VERIFIED", "PARTLY_VERIFIED", "NOT_SUPPORTED"
STATUS_LABELS = (VERIFIED, PARTLY_VERIFIED, NOT_SUPPORTED)
MAX_PARAGRAPHS = 5000
MAX_TOTAL_CHARS = 300_000
MAX_PARAGRAPH_CHARS = 20_000
NEUTRAL = "This only points to a place to look. It does not say that anything is wrong, and a lawyer decides."
NEW_ACT = {"Bharatiya Nyaya Sanhita": "BNS", "Bharatiya Nagarik Suraksha Sanhita": "BNSS", "Bharatiya Sakshya Adhiniyam": "BSA"}  # how a reviewed new text's title is shortened in the document


@dataclass
class Para:
    id: str
    text: str


def split_text(text: str) -> list[Para]:
    """Raw text with no paragraph ids: one paragraph per non-empty line, numbered p1, p2, ..."""
    lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    return [Para(f"p{i}", ln) for i, ln in enumerate(lines, 1)]


def span_of(text: str, start: int, raw: str) -> tuple[int, int]:
    """Where `raw` (whitespace folded by the readers) really ends in the text, starting the search at `start`."""
    words = raw.split()
    if not words:
        return start, start
    m = re.compile(r"\s+".join(re.escape(w) for w in words)).search(text, max(0, start))
    return (m.start(), m.end()) if m else (start, min(len(text), start + len(raw)))


def _issue(group: str, p: Para, start: int, end: int, defect_type: str, message: str, **more) -> dict:
    return {"group": group, "paragraph_id": p.id, "start_index": start, "end_index": end, "text": p.text[start:end], "defect_type": defect_type, "status_label": None,
            "suggested_replacement": None, "reviewer_source_note": "", "message": message, **more}


def citation_status(item: dict) -> str:
    """The three honest labels. Only a provision in the reviewed library can be VERIFIED; a case from the open dataset never goes beyond PARTLY_VERIFIED."""
    label = item["label"]
    if item["kind"] == "statute":
        return VERIFIED if label == statutes.FOUND_REVIEWED else PARTLY_VERIFIED if label == statutes.FOUND_NOT_REVIEWED else NOT_SUPPORTED
    if label in (lookup.FOUND_MATCHES, lookup.DETAILS_DIFFER, quotes.QUOTE_NOT_FOUND, propositions.MAY_NOT_SUPPORT):
        return PARTLY_VERIFIED
    return NOT_SUPPORTED


def _source_note(item: dict) -> str:
    if item["kind"] == "statute":
        rows = [p for row in item.get("per_provision", []) for p in row.get("provisions", [])]
        return "; ".join(f"{p['instrument']}: {p.get('review', '')}" for p in rows[:3])[:400]
    parts = [item.get("matched_title") or "", item.get("source_url") or ""]
    return " ".join(x for x in parts if x)[:400]


async def _authority(paras: list[Para], source, reserve=None) -> list[dict]:
    built = await authority_report.build([p.text for p in paras], source, reserve=reserve)
    out = []
    for it in built["items"]:
        p = paras[it["page"] - 1]
        s, e = span_of(p.text, 0, it["raw"])
        status = citation_status(it)
        out.append(_issue("authority", p, s, e, "citation_" + it["kind"], it["reason"], status_label=status, reviewer_source_note=_source_note(it), label=it["label"],
                          current_status=it.get("current_status", "")))
    return out


async def _suggestion(act: str, section: str) -> tuple[str | None, str, dict]:
    """(replacement text, source note, mapping facts) - the replacement only for a reviewed, exact, one-to-one mapping with a single newer provision."""
    res = await code_mappings.lookup(section, old_check.ACT_NAME[act])
    ok = [m for m in res.get("verified_mappings", []) if m.get("relationship") == "one-to-one" and m.get("equivalence") == "exact" and len(m.get("new", [])) == 1]
    facts = {"reviewed_mappings": len(res.get("verified_mappings", [])), "unreviewed_mappings": len(res.get("mappings", [])) - len(res.get("verified_mappings", []))}
    if not ok:
        return None, "" if res.get("verified_mappings") else code_mappings.NO_MAPPING, facts
    m, new = ok[0], ok[0]["new"][0]
    short = next((v for k, v in NEW_ACT.items() if k.lower() in new["instrument"].lower()), None)
    if not short or not new.get("number"):
        return None, "A reviewed mapping exists, but its newer text could not be written in the document's style.", facts
    note = f"Reviewed by {m.get('reviewed_by') or 'a named reviewer'}. Source: {'; '.join(m.get('authorities') or []) or 'none recorded'}. {code_mappings.CAVEAT}"
    return f"{new['number']} {short}", note, facts


async def _old_code(paras: list[Para]) -> list[dict]:
    out = []
    seen: dict[tuple[int, int, int], dict] = {}
    cache: dict[tuple[str, str], tuple] = {}
    for f in old_check.check([p.text for p in paras]):
        p = paras[f.page - 1]
        if f.kind == "mention":
            s, e = span_of(p.text, f.start, f.raw)
            out.append(_issue("code_replacement", p, s, e, "old_code_named", f.note, act=f.act, section="", caveat=code_mappings.CAVEAT))
            continue
        m = next((x for x in old_check.SECTIONS.finditer(p.text) if x.start() == f.start), None)
        s, e = (m.start("list"), m.end()) if m else span_of(p.text, f.start, f.raw)
        key_span = (f.page, s, e)
        if key_span in seen:  # a list such as "Sections 302 and 307 IPC" is ONE place in the document: one finding, naming every section
            seen[key_span]["sections"].append(f.section)
            continue
        if m and p.text[e - 1 : e] == "." and p.text[m.start("list") : e].rsplit(" ", 1)[-1].count(".") == 1:
            e -= 1  # "IPC." at the end of a sentence: the full stop belongs to the sentence, not to the Act's name
        numbers = {old_check.canonical(n.group(0)) for n in old_check.ONE_NUM.finditer(re.sub(r"\([^)]*\)", "", m["list"]))} if m else {f.section}
        key = (f.act, f.section)
        if key not in cache:
            cache[key] = await _suggestion(f.act, f.section)
        replacement, note, facts = cache[key]
        if len(numbers) != 1:
            replacement = None  # several sections named together: a person writes the replacement
        issue = _issue("code_replacement", p, s, e, "old_code_section", f.note, act=f.act, section=f.section, sections=[f.section], suggested_replacement=replacement,
                       reviewer_source_note=note, caveat=code_mappings.CAVEAT, **facts)
        seen[key_span] = issue
        out.append(issue)
    return out


def _defects(paras: list[Para]) -> list[dict]:
    out = []
    for f in defect_check.check([p.text for p in paras]):
        p = paras[f.page - 1]
        s, e = span_of(p.text, f.start, f.raw)
        out.append(_issue("defect", p, s, e, f.kind, f.note))
    return out


def _dates(paras: list[Para]) -> list[dict]:
    """Every date written, in reading order, with where it is. Dates the reader could not read as a real day are listed with its plain-words flag."""
    out = []
    for f in date_extract.extract([p.text for p in paras]):
        p = paras[f.page - 1]
        s, e = span_of(p.text, f.start, f.raw)
        out.append({"group": "date", "paragraph_id": p.id, "start_index": s, "end_index": e, "text": p.text[s:e], "date": f.iso, "kind": f.kind, "flags": f.flags,
                    "message": " ".join(f.flags) or "A date written in the text."})
    return out


def counts(issues: list[dict], dates: list[dict]) -> dict:
    by_status: dict[str, int] = {}
    for i in issues:
        if i["status_label"]:
            by_status[i["status_label"]] = by_status.get(i["status_label"], 0) + 1
    return {"authority": sum(1 for i in issues if i["group"] == "authority"), "code_replacement": sum(1 for i in issues if i["group"] == "code_replacement"),
            "defect": sum(1 for i in issues if i["group"] == "defect"), "dates": len(dates), "by_status": by_status,
            "with_suggested_replacement": sum(1 for i in issues if i["suggested_replacement"])}


async def analyze(paras: list[Para], source=None, reserve=None) -> dict:
    """All checks over the paragraphs. A check that is switched off on this server is reported as off, never as clean."""
    issues: list[dict] = []
    checks: dict[str, str] = {}
    if authority_report.enabled() and source is not None:
        try:
            issues += await _authority(paras, source, reserve)
            checks["authority"] = "ran"
        except authority_report.TooManyReferences:
            checks["authority"] = "too_many_citations"
        except LookupCapExceeded:
            checks["authority"] = "daily_limit"
    else:
        checks["authority"] = "off"
    from lib.oldcode import report as old_report

    if old_report.enabled():
        issues += await _old_code(paras)
        checks["old_code"] = "ran"
    else:
        checks["old_code"] = "off"
    from lib.defects import report as defect_report

    if defect_report.enabled():
        issues += _defects(paras)
        checks["defects"] = "ran"
    else:
        checks["defects"] = "off"
    from lib.datelist import report as date_report

    dates = _dates(paras) if date_report.enabled() else []
    checks["dates"] = "ran" if date_report.enabled() else "off"
    order = {p.id: n for n, p in enumerate(paras)}
    issues.sort(key=lambda i: (order[i["paragraph_id"]], i["start_index"]))
    for n, i in enumerate(issues, 1):
        i["id"] = f"i{n}"
    return {"issues": issues, "dates": dates, "checks": checks, "counts": counts(issues, dates), "neutral_note": NEUTRAL, "caveat": code_mappings.CAVEAT,
            "status_labels": list(STATUS_LABELS)}
