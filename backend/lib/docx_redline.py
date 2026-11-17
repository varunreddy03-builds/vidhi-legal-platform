"""Puts the Katalyst findings into a Word file as NATIVE Word review marks: tracked changes (w:del / w:ins) and comments, so the lawyer accepts or rejects each one in Word.

The file's own look is kept: nothing is rebuilt. A paragraph is only touched where a mark is placed; the text is cut into runs at the exact characters, and every piece keeps the run properties
(font, size, bold ...) it had. Margins, tables, headers, styles and pictures are never read or changed. A paragraph that cannot be matched exactly to the text that was analysed is left alone
and listed as skipped. A tracked replacement is placed only for a finding that carries a reviewed suggestion, and only when the caller asked for replacements; everything else becomes a comment."""

import copy
import io
from datetime import datetime, timezone

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from lxml import etree

from lib.katalyst_addin import Para

AUTHOR = "VIDHI AI Checker"
INITIALS = "VAI"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


def body_paragraphs(document) -> list[Paragraph]:
    """Every paragraph of the body in reading order, table cells included."""
    return [Paragraph(p, document) for p in document.element.body.iter(qn("w:p"))]


def paras_of(document) -> list[Para]:
    return [Para(f"p{n}", p.text) for n, p in enumerate(body_paragraphs(document), 1)]


def _content(r) -> list:
    return [c for c in r if c.tag != qn("w:rPr")]


def _length(r) -> int:
    c = _content(r)
    if len(c) != 1:
        return 0
    if c[0].tag == qn("w:t"):
        return len(c[0].text or "")
    return 1 if c[0].tag in (qn("w:tab"), qn("w:br")) else 0


def _explode(p) -> None:
    """One content element per run, each piece keeping a copy of the run's properties, so a cut at any character is a cut between runs."""
    for r in list(p.iter(qn("w:r"))):
        if r.getparent() is not None and r.getparent().tag in (qn("w:del"), qn("w:ins")):
            continue
        content = _content(r)
        if len(content) <= 1:
            continue
        at = r.getparent().index(r)
        parent = r.getparent()
        rpr = r.find(qn("w:rPr"))
        parent.remove(r)
        for k, c in enumerate(content):
            piece = etree.SubElement(parent, qn("w:r"))
            parent.remove(piece)
            if rpr is not None:
                piece.append(copy.deepcopy(rpr))
            piece.append(c)
            parent.insert(at + k, piece)


def _segments(p) -> list[tuple]:
    """(run element, start, end) for every run, with the same text rule as Paragraph.text."""
    pos, out = 0, []
    for r in p.iter(qn("w:r")):
        n = _length(r)
        out.append((r, pos, pos + n))
        pos += n
    return out


def _split_at(p, k: int) -> None:
    for r, s, e in _segments(p):
        if s < k < e:
            t = _content(r)[0]
            if t.tag != qn("w:t"):
                return
            text = t.text or ""
            right = copy.deepcopy(r)
            t.text = text[: k - s]
            t.set(XML_SPACE, "preserve")
            rt = _content(right)[0]
            rt.text = text[k - s :]
            rt.set(XML_SPACE, "preserve")
            r.addnext(right)
            return


def _runs_between(p, s: int, e: int) -> list:
    return [r for r, a, b in _segments(p) if b > a and a >= s and b <= e]


def _next_id(document) -> int:
    ids = [int(x) for x in document.element.xpath("//w:ins/@w:id | //w:del/@w:id") if str(x).isdigit()]
    return max(ids, default=0) + 1


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _track(document, runs: list, replacement: str) -> None:
    """The runs become a tracked deletion, followed by a tracked insertion of the replacement written in the look of the first deleted run."""
    nid = _next_id(document)
    first = runs[0]
    rpr = first.find(qn("w:rPr"))
    dele = etree.Element(qn("w:del"), {qn("w:id"): str(nid), qn("w:author"): AUTHOR, qn("w:date"): _stamp()})
    first.addprevious(dele)
    for r in runs:
        dele.append(r)  # moves the run inside the deletion
        for t in r.findall(qn("w:t")):
            t.tag = qn("w:delText")
            t.set(XML_SPACE, "preserve")
    ins = etree.Element(qn("w:ins"), {qn("w:id"): str(nid + 1), qn("w:author"): AUTHOR, qn("w:date"): _stamp()})
    new = etree.SubElement(ins, qn("w:r"))
    if rpr is not None:
        new.append(copy.deepcopy(rpr))
    t = etree.SubElement(new, qn("w:t"))
    t.text = replacement
    t.set(XML_SPACE, "preserve")
    dele.addnext(ins)


def redline(data: bytes, issues: list[dict], apply_replacements: bool) -> tuple[bytes, dict]:
    """(the marked Word file, what was done). `issues` are the findings of lib.katalyst_addin.analyze for this same file (paragraph ids p1, p2 ... in body order)."""
    document = docx.Document(io.BytesIO(data))
    paragraphs = body_paragraphs(document)
    done = {"comments": 0, "tracked_replacements": 0, "skipped": []}
    by_para: dict[str, list[dict]] = {}
    for i in issues:
        if i["group"] in ("authority", "code_replacement", "defect") and (i["group"] != "authority" or i["status_label"] != "VERIFIED"):
            by_para.setdefault(i["paragraph_id"], []).append(i)
    for pid, items in by_para.items():
        n = int(pid[1:])
        para = paragraphs[n - 1]
        if not para.text or any(i["end_index"] > len(para.text) for i in items):
            done["skipped"].append({"paragraph_id": pid, "why": "The text of this paragraph is not the text that was checked."})
            continue
        p = para._p
        _explode(p)
        if "".join(_text_of(r) for r in p.iter(qn("w:r"))) != para.text:
            done["skipped"].append({"paragraph_id": pid, "why": "This paragraph holds parts (such as fields) that could not be matched exactly, so it was left unmarked."})
            continue
        for i in items:
            _split_at(p, i["start_index"])
            _split_at(p, i["end_index"])
        placed: list[tuple[int, int]] = []
        for i in sorted(items, key=lambda x: x["start_index"]):
            runs = _runs_between(p, i["start_index"], i["end_index"])
            if not runs:
                done["skipped"].append({"paragraph_id": pid, "why": "A finding could not be anchored to text."})
                continue
            note = _comment_text(i)
            document.add_comment([Run(r, para) for r in runs], text=note, author=AUTHOR, initials=INITIALS)
            done["comments"] += 1
            overlaps = any(i["start_index"] < b and a < i["end_index"] for a, b in placed)
            if apply_replacements and i.get("suggested_replacement") and not overlaps:
                _track(document, runs, i["suggested_replacement"])
                placed.append((i["start_index"], i["end_index"]))
                done["tracked_replacements"] += 1
    out = io.BytesIO()
    document.save(out)
    return out.getvalue(), done


def _text_of(r) -> str:
    c = _content(r)
    if len(c) != 1:
        return ""
    if c[0].tag == qn("w:t"):
        return c[0].text or ""
    return "\t" if c[0].tag == qn("w:tab") else "\n" if c[0].tag == qn("w:br") else ""


def _comment_text(i: dict) -> str:
    head = {"authority": f"Citation: {i.get('status_label')}.", "code_replacement": "Older code named.", "defect": "Drafting point to look at."}[i["group"]]
    parts = [head, i["message"]]
    if i.get("suggested_replacement"):
        parts.append(f"Suggested (reviewed mapping): {i['suggested_replacement']}.")
    if i.get("reviewer_source_note"):
        parts.append(i["reviewer_source_note"])
    parts.append("A lawyer decides.")
    return " ".join(x for x in parts if x)[:1500]
