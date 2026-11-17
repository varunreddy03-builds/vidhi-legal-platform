"""Word and PDF copies of a pre-filing defect check. Same words as the screen; plain tables; the fixed notice first, then what 'page' means for this file."""

import io

from lib.datelist.export import PAGE_NOTES


def _rows(report: dict) -> list[list[str]]:
    rows = [["#", "What", "As written", "Sentence it appears in", "Where", "Why it may not be a slip"]]
    for i in report["items"]:
        rows.append([str(i["n"]), i["label"], i["raw"], i["sentence"], i["where"], i["note"]])
    return rows


def _summary(report: dict) -> str:
    c = report["counts"]
    if not c["total"]:
        return f"Nothing was pointed out. Source file: {report.get('source_file') or 'pasted text'}. That is not a finding that the draft is ready to file."
    return f"{c['total']} places to look at ({', '.join(f'{v} × {report_label(k)}' for k, v in sorted(c['by_kind'].items()))}). Source file: {report.get('source_file') or 'pasted text'}."


def report_label(kind: str) -> str:
    from lib.defects.report import KIND_LABELS

    return KIND_LABELS.get(kind, kind).lower()


def to_docx(report: dict) -> bytes:
    from docx import Document

    d = Document()
    d.add_heading(f"Pre-filing defect check: {report['title']}", 1)
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
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=24, rightMargin=24, topMargin=24, bottomMargin=24, title="Pre-filing defect check")
    rows = [[Paragraph(escape(x), cell) for x in row] for row in _rows(report)]
    table = Table(rows, colWidths=[22, 80, 90, 250, 110, 230], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph(escape(f"Pre-filing defect check: {report['title']}"), st["Title"]), Paragraph(escape(report["notice"]), st["BodyText"]), Spacer(1, 4),
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
