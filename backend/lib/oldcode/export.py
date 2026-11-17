"""Word and PDF copies of an old-code check. Same words as the screen; plain tables; the fixed notice first, then what 'page' means for this file, then the transitional caveat."""

import io

from lib.datelist.export import PAGE_NOTES


def mapping_text(item: dict) -> str:
    m = item.get("mapping")
    if m is None:
        return "No section number was read here, so nothing was looked up."
    if m["status"] != "reviewed":
        extra = f" {m['unreviewed_count']} unreviewed entr{'y exists' if m['unreviewed_count'] == 1 else 'ies exist'} and {'is' if m['unreviewed_count'] == 1 else 'are'} not shown as an answer." if m.get("unreviewed_count") else ""
        shown = "".join(f" UNREVIEWED, not verified ({d['relationship']}; {d['equivalence']}): {', '.join(d['new']) or 'no newer provision'}. Source: {'; '.join(d['authorities'])}. No reviewer has compared it with its source." for d in m.get("unreviewed", []))
        return m["message"] + extra + shown
    return " | ".join(f"Reviewed mapping ({r['relationship']}; {r['equivalence']}): {', '.join(r['new']) or 'no newer provision'}. Source: {'; '.join(r['authorities'])}. Reviewed by {r['reviewed_by']}." for r in m["reviewed"])


def _rows(report: dict) -> list[list[str]]:
    rows = [["#", "What", "Act", "Section", "As written", "Sentence it appears in", "Where", "What the reviewed store says"]]
    for i in report["items"]:
        rows.append([str(i["n"]), i["label"], i["act_name"], i["section"] or "-", i["raw"], i["sentence"], i["where"], mapping_text(i)])
    return rows


def _summary(report: dict) -> str:
    c = report["counts"]
    src = report.get("source_file") or "pasted text"
    if not c["total"]:
        return f"No reference to the Indian Penal Code, the Code of Criminal Procedure or the Indian Evidence Act was found. Source file: {src}. That is not a finding that the draft has none."
    return f"{c['total']} references ({c['sections']} with a section number, {c['with_reviewed_mapping']} with a reviewed mapping). Source file: {src}."


def to_docx(report: dict) -> bytes:
    from docx import Document

    d = Document()
    d.add_heading(f"Old-code to new-code checker: {report['title']}", 1)
    d.add_paragraph(report["notice"])
    d.add_paragraph(PAGE_NOTES.get(report["page_kind"], PAGE_NOTES["unknown"]))
    d.add_paragraph(_summary(report))
    d.add_paragraph(f"Made {report['created_at']}.")
    rows = _rows(report)
    t = d.add_table(rows=len(rows), cols=8)
    t.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            t.cell(r, c).text = text
    d.add_paragraph(report["caveat"])
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_pdf(report: dict) -> bytes:
    from lib.pdfsafe import Guard

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    g = Guard()
    escape = g.escape
    st = getSampleStyleSheet()
    cell = st["BodyText"]
    cell.fontSize = 7.5
    cell.leading = 9
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24, title="Old-code to new-code checker")
    rows = [[Paragraph(escape(x), cell) for x in row] for row in _rows(report)]
    table = Table(rows, colWidths=[20, 60, 70, 40, 80, 210, 80, 200], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph(escape(f"Old-code to new-code checker: {report['title']}"), st["Title"]), Paragraph(escape(report["notice"]), st["BodyText"]), Spacer(1, 4),
               Paragraph(escape(PAGE_NOTES.get(report["page_kind"], PAGE_NOTES["unknown"])), st["BodyText"]), Spacer(1, 4),
               Paragraph(escape(_summary(report)), st["BodyText"]), Paragraph(escape(f"Made {report['created_at']}."), st["BodyText"]), Spacer(1, 8), table, Spacer(1, 8),
               Paragraph(escape(report["caveat"]), st["BodyText"])]
    return _finish(doc, story, g, buf)


def _finish(doc, story, guard, buf) -> bytes:
    """Build the PDF; when text could not be drawn, say so at the top (lib/pdfsafe.py)."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Spacer

    if guard.count:
        story[1:1] = [Paragraph(guard.note(), getSampleStyleSheet()["BodyText"]), Spacer(1, 4)]
    doc.build(story)
    return buf.getvalue()
