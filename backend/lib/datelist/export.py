"""Word and PDF copies of a list of dates. Same words as the screen; plain tables; the fixed notice first, then what 'page' means for this file."""

import io

PAGE_NOTES = {
    "pdf": "Page numbers are the pages of the PDF file.",
    "no_pages": "This file type (Word or text) has no fixed pages, so no page numbers are given. 'Part' shows where in the file the date sits, counting equal slices of the text; a part is not a page.",
    "unknown": "This list was made from pasted text, which has no pages.",
}


def _rows(report: dict) -> list[list[str]]:
    rows = [["#", "Date as written", "Read as", "Sentence it appears in", "Where", "Notes"]]
    for i in report["items"]:
        rows.append([str(i["n"]), i["raw"], i["date"] or "not read as one day", i["sentence"], i["where"], " ".join(i["flags"])])
    return rows


def _summary(report: dict) -> str:
    c = report["counts"]
    return (f"{c['total']} dates: {c['dated']} read as one real day, {c['no_exact_day']} not read as one day, "
            f"{c['not_read_cleanly']} with a note. Source file: {report.get('source_file') or 'pasted text'}.")


def to_docx(report: dict) -> bytes:
    from docx import Document

    d = Document()
    d.add_heading(f"List of dates: {report['title']}", 1)
    d.add_paragraph(report["notice"])
    d.add_paragraph(PAGE_NOTES.get(report["page_kind"], PAGE_NOTES["unknown"]))
    d.add_paragraph(_summary(report))
    d.add_paragraph(f"Made {report['created_at']}.")
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
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24, title="List of dates")
    rows = [[Paragraph(escape(x), cell) for x in row] for row in _rows(report)]
    table = Table(rows, colWidths=[22, 90, 70, 300, 130, 160], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph(escape(f"List of dates: {report['title']}"), st["Title"]), Paragraph(escape(report["notice"]), st["BodyText"]), Spacer(1, 4),
               Paragraph(escape(PAGE_NOTES.get(report["page_kind"], PAGE_NOTES["unknown"])), st["BodyText"]), Spacer(1, 4),
               Paragraph(escape(_summary(report)), st["BodyText"]), Paragraph(escape(f"Made {report['created_at']}."), st["BodyText"]), Spacer(1, 8), table]
    return _finish(doc, story, g, buf)


def _finish(doc, story, guard, buf) -> bytes:
    """Build the PDF; when text could not be drawn, say so at the top (lib/pdfsafe.py)."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Spacer

    if guard.count:
        story[1:1] = [Paragraph(guard.note(), getSampleStyleSheet()["BodyText"]), Spacer(1, 4)]
    doc.build(story)
    return buf.getvalue()
