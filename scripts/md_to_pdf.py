"""Turn one of VIDHI's markdown guides into a PDF (headings, paragraphs, bullet and numbered lists, tables, **bold**, `code`, links shown as text plus address).

  C:\\vidhi-tools\\venv2\\Scripts\\python.exe scripts\\md_to_pdf.py docs\\WHERE_TO_GET_LAW.md [docs\\WHERE_TO_GET_LAW.pdf]

Uses reportlab (already a backend dependency) and the built-in PDF fonts, so the text must be plain Latin: write "Rs", not the rupee sign (the same rule as the notice PDFs)."""

import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13.2, spaceAfter=5)
H1 = ParagraphStyle("h1", parent=BASE, fontName="Helvetica-Bold", fontSize=17, leading=21, spaceAfter=8, textColor=colors.HexColor("#0F172A"))
H2 = ParagraphStyle("h2", parent=BASE, fontName="Helvetica-Bold", fontSize=12.5, leading=16, spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#1E3A8A"))
H3 = ParagraphStyle("h3", parent=BASE, fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=6, spaceAfter=3)
CELL = ParagraphStyle("cell", parent=BASE, fontSize=8, leading=10.4, spaceAfter=0)
CELL_HEAD = ParagraphStyle("cellh", parent=CELL, fontName="Helvetica-Bold", textColor=colors.white)


def inline(text: str) -> str:
    """Markdown inline marks to reportlab's small tag set. Everything else is escaped."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f"{m.group(1)} ({m.group(2)})", text)
    out, pos = [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*|`([^`]+)`", text):
        out.append(escape(text[pos:m.start()]))
        out.append(f"<b>{escape(m.group(1))}</b>" if m.group(1) is not None else f'<font name="Courier" size="8.2">{escape(m.group(2))}</font>')
        pos = m.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def table(rows: list[list[str]], width: float):
    head, body = rows[0], rows[1:]
    n = len(head)
    weights = [max(8, min(60, max(len(r[i]) if i < len(r) else 0 for r in rows))) for i in range(n)]
    total = sum(weights)
    widths = [width * w / total for w in weights]
    data = [[Paragraph(inline(c), CELL_HEAD) for c in head]] + [[Paragraph(inline(c), CELL) for c in (r + [""] * n)[:n]] for r in body]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build(md: str, width: float) -> list:
    flow, para, bullets, nums, rows = [], [], [], [], []

    def flush():
        nonlocal para, bullets, nums, rows
        if para:
            flow.append(Paragraph(inline(" ".join(para)), BASE))
            para = []
        if bullets:
            flow.append(ListFlowable([ListItem(Paragraph(inline(b), BASE), leftIndent=14) for b in bullets], bulletType="bullet", start="-", leftIndent=14, bulletFontSize=9))
            bullets = []
        if nums:
            flow.append(ListFlowable([ListItem(Paragraph(inline(b), BASE), leftIndent=16) for b in nums], bulletType="1", leftIndent=16, bulletFontSize=9))
            nums = []
        if rows:
            flow.extend([table(rows, width), Spacer(1, 6)])
            rows = []

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
        elif line.startswith("<!--"):
            continue
        elif line.startswith("### "):
            flush(); flow.append(Paragraph(inline(line[4:]), H3))
        elif line.startswith("## "):
            flush(); flow.append(Paragraph(inline(line[3:]), H2))
        elif line.startswith("# "):
            flush(); flow.append(Paragraph(inline(line[2:]), H1))
        elif line.startswith("|"):
            if para or bullets or nums:
                flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            rows.append(cells)
        elif re.match(r"^\s*[-*] ", line):
            if para or nums or rows:
                flush()
            bullets.append(re.sub(r"^\s*[-*] ", "", line))
        elif re.match(r"^\s*\d+\. ", line):
            if para or bullets or rows:
                flush()
            nums.append(re.sub(r"^\s*\d+\. ", "", line))
        else:
            if bullets or nums or rows:
                flush()
            para.append(line.strip())
    flush()
    return flow


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    md = src.read_text(encoding="utf-8")
    bad = sorted({c for c in md if ord(c) > 255})
    if bad:
        print("These characters are not in the built-in PDF fonts; replace them first:", bad)
        return 1
    doc = SimpleDocTemplate(str(dst), pagesize=A4, title=src.stem.replace("_", " "), author="VIDHI", leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.7 * cm, bottomMargin=1.7 * cm)

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(1.8 * cm, 1.0 * cm, f"VIDHI - {src.name}")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.0 * cm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(build(md, A4[0] - 3.6 * cm), onFirstPage=footer, onLaterPages=footer)
    print("wrote", dst, dst.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
