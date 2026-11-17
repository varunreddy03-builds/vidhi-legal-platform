"""The one-page "Pre-Filing Scrutiny Audit Summary" that goes with a marked-up Word file. Same neutral words as the screens; it counts and points, and says what was not run."""

import io

NOTICE = ("This summary lists places to look at. It does not say that a filing is ready, will be accepted, or is wrong. A citation is called VERIFIED only when the provision is in VIDHI's "
          "reviewed library; current status of a case or Act is not checked. A lawyer decides.")
MAX_ROWS = 18
GROUP_LABEL = {"authority": "Citation", "code_replacement": "Older code", "defect": "Drafting point"}


def _rows(analysis: dict) -> list[list[str]]:
    rows = [["Kind", "Text as written", "Result"]]
    for i in analysis["issues"][:MAX_ROWS]:
        result = i["status_label"] or ("suggestion from a reviewed mapping: " + i["suggested_replacement"] if i.get("suggested_replacement") else i["defect_type"].replace("_", " "))
        rows.append([GROUP_LABEL[i["group"]], i["text"][:90], result[:90]])
    return rows


def _lines(analysis: dict, done: dict, source_name: str) -> list[str]:
    c = analysis["counts"]
    off = [k.replace("_", " ") for k, v in analysis["checks"].items() if v != "ran"]
    by = ", ".join(f"{v} {k}" for k, v in sorted(c["by_status"].items())) or "none"
    out = [f"File: {source_name}.",
           f"Citations checked: {c['authority']} ({by}). Older-code references: {c['code_replacement']} ({c['with_suggested_replacement']} with a suggestion from a reviewed mapping). Drafting points: {c['defect']}. Dates written: {c['dates']}.",
           f"Marks placed in the Word file: {done['comments']} comments, {done['tracked_replacements']} tracked replacements."]
    if done["skipped"]:
        out.append(f"{len(done['skipped'])} paragraph(s) were left unmarked because they could not be matched exactly.")
    if off:
        out.append("Not run on this server (switched off or too large): " + ", ".join(off) + ". Nothing is claimed about them.")
    return out


def to_pdf(analysis: dict, done: dict, source_name: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from lib.pdfsafe import Guard

    g = Guard()
    esc = g.escape
    st = getSampleStyleSheet()
    cell = st["BodyText"]
    cell.fontSize = 8
    cell.leading = 10
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=34, rightMargin=34, topMargin=30, bottomMargin=30, title="Pre-Filing Scrutiny Audit Summary")
    table = Table([[Paragraph(esc(x), cell) for x in row] for row in _rows(analysis)], colWidths=[80, 220, 220], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story = [Paragraph("Pre-Filing Scrutiny Audit Summary", st["Title"]), Paragraph(esc(NOTICE), st["BodyText"]), Spacer(1, 6)]
    story += [Paragraph(esc(x), st["BodyText"]) for x in _lines(analysis, done, source_name)] + [Spacer(1, 8), table]
    more = len(analysis["issues"]) - MAX_ROWS
    if more > 0:
        story += [Spacer(1, 4), Paragraph(esc(f"{more} more finding(s) are in the comments of the Word file and in the JSON report."), st["BodyText"])]
    story += [Spacer(1, 6), Paragraph(esc(analysis["caveat"]), cell)]
    if g.count:
        story[2:2] = [Paragraph(g.note(), st["BodyText"]), Spacer(1, 4)]
    doc.build(story)
    return buf.getvalue()
