"""Word and PDF copies of an Authority Check report. Same words as the screen; plain tables; the fixed notice first."""

import io

NOTICE = (
    "This is a citation check, not legal advice and not a finding of fact. It reads what the draft cites and compares it with a source. "
    "A reference marked 'could not check' or 'not in reviewed library' is not a wrong reference. For every case, current status: not checked "
    "(whether it is still good law was never looked at). A lawyer decides."
)
LABELS = {
    "FOUND_MATCHES": "Found, details agree", "DETAILS_DIFFER": "Found, details differ", "COULD_NOT_CHECK": "Could not check", "NOT_FOUND_FULL_SEARCH": "Not found after a full search",
    "QUOTE_NOT_FOUND": "Case found, quoted words not found", "MAY_NOT_SUPPORT": "Case found, may not support the point",
    "FOUND_REVIEWED": "In reviewed library", "FOUND_NOT_REVIEWED": "In library, not yet reviewed", "NOT_IN_REVIEWED_LIBRARY": "Not in reviewed library",
}
STATES = {"open": "Open", "fix": "Marked to fix", "accept_as_is": "Accepted as is", "reviewed": "Marked reviewed"}


def _rows(report: dict) -> list[list[str]]:
    rows = [["#", "Reference as written", "Page", "Result", "Why", "Review"]]
    for i in report["items"]:
        why = i["reason"] + ("".join(f" Difference: {d}" for d in i.get("differences", []))) + (f" {i['old_code_note']}" if i.get("old_code_note") else "")
        why += "".join(f" Quote “{q['quote'][:160]}”: {q['reason']}" for q in i.get("quotes", []))
        prop = i.get("proposition") or {}
        if prop.get("state") == "may_not_support" and prop["note"] not in why:
            why += f" {prop['note']}"
        r = i["review"]
        state = STATES.get(r.get("state", "open"), r.get("state", "open")) + (f" by {r['by']}" if r.get("by") else "") + (f": {r['note']}" if r.get("note") else "")
        rows.append([str(i["n"]), i["raw"], str(i["page"]), LABELS.get(i["label"], i["label"]), why, state])
    return rows


def _summary(report: dict) -> str:
    c = report["counts"]
    return f"{c['total']} references ({c['cases']} cases, {c['statutes']} statutes). " + "; ".join(f"{LABELS.get(k, k)}: {v}" for k, v in sorted(c["by_label"].items())) + f". Still open: {c['open']}."


def to_docx(report: dict) -> bytes:
    from docx import Document

    d = Document()
    d.add_heading(f"Authority Check: {report['title']}", 1)
    d.add_paragraph(NOTICE)
    d.add_paragraph(_summary(report))
    d.add_paragraph(f"Checked {report['created_at']} using {report.get('source') or 'no case source'}.")
    if (report.get("source_attribution") or {}).get("text"):
        d.add_paragraph(report["source_attribution"]["text"])
    rows = _rows(report)
    t = d.add_table(rows=len(rows), cols=6)
    t.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            t.cell(r, c).text = text
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_pdf(report: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from lib.pdfsafe import Guard

    g = Guard()
    escape = g.escape
    st = getSampleStyleSheet()
    cell = st["BodyText"]
    cell.fontSize = 7.5
    cell.leading = 9
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24, title="Authority Check")
    rows = [[Paragraph(escape(x), cell) for x in row] for row in _rows(report)]
    table = Table(rows, colWidths=[22, 170, 30, 90, 350, 120], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph(escape(f"Authority Check: {report['title']}"), st["Title"]), Paragraph(escape(NOTICE), st["BodyText"]), Spacer(1, 6), Paragraph(escape(_summary(report)), st["BodyText"]),
               Paragraph(escape(f"Checked {report['created_at']} using {report.get('source') or 'no case source'}."), st["BodyText"]),
               Paragraph(escape((report.get("source_attribution") or {}).get("text", "")), st["BodyText"]), Spacer(1, 8), table]
    return _finish(doc, story, g, buf)


def _finish(doc, story, guard, buf) -> bytes:
    """Build the PDF; when text could not be drawn, say so at the top (lib/pdfsafe.py)."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Spacer

    if guard.count:
        story[1:1] = [Paragraph(guard.note(), getSampleStyleSheet()["BodyText"]), Spacer(1, 4)]
    doc.build(story)
    return buf.getvalue()
