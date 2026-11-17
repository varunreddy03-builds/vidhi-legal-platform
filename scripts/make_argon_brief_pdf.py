"""Builds docs/VIDHI_APP_STATUS_AND_ARGON_BRIEF.pdf: what VIDHI is, what has been built, what it still needs, and docs/ARGON_BRIEF.md as the brief for Argon (Gemini).

Run:  C:\\vidhi-tools\\venv2\\Scripts\\python.exe scripts\\make_argon_brief_pdf.py
Plain reportlab with its built-in fonts, like the other exports (lib/pdfsafe.py says what it cannot draw: Indian scripts). The text of Part 4 is read from docs/ARGON_BRIEF.md, so
the PDF and the markdown cannot drift apart; Parts 1 to 3 are written below and must be kept current by hand (the numbers are as of the date printed on the cover)."""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.platypus import PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

from lib.pdfsafe import Guard  # noqa: E402

AS_OF = "2026-11-12"
OUT = os.path.join(ROOT, "docs", "VIDHI_APP_STATUS_AND_ARGON_BRIEF.pdf")

PARTS_1_TO_3 = f"""
# VIDHI: the app, what has been built, what it still needs, and the brief for Argon

As of {AS_OF}. Written from the code, the tests and the project's own records. Where something was not tested or not measured, this document says so.

## Part 1. What the app is

**VIDHI is an AI legal workflow platform for India.** Tagline: *AI assists. Sources support. Graphs connect. Logic verifies. Lawyers decide.*

It exists because advocates lose hours on checks that a program can do exactly (does every cited case exist, are the dates right, did the draft cite the old IPC for an offence after 1 July 2024) and because general chatbots sometimes invent citations. VIDHI keeps the plain checks in plain code, uses AI only to read and propose, and then checks every quote against a stored source in code. Every legal statement is shown with a label and its proof.

| Part | For | What it does |
|---|---|---|
| **Legal Intelligence** | advocates and chambers | Ask, Research (four modes), Matters with documents, facts, timeline, evidence, Drafts, document tools, law and judgment search. |
| **Legal Katalyst** | advocates | Five checks on plain code, no AI: Authority Check, Deadline engine, Old-code to new-code checker, Pre-filing defect check, List of dates with page references. |
| **Legal Recovery** | small businesses | A small free helper: eligibility questions, the free MSME portal first, a payment notice to download or copy, three typed dates. |

**Labels.** `VERIFIED` only when the exact source text is in the reviewed library and the quote matches. `PARTIALLY_VERIFIED` when a source exists but the quote or reviewer is missing. `UNSUPPORTED` otherwise. A model's own opinion never counts as verification.

## Part 2. What has been built up to now

**Size.** 389 commits from 2026-09-20 to {AS_OF}. Backend (FastAPI + MongoDB): 48 route modules, 117 library modules, about 29,700 lines of code and 25,300 lines of tests in 171 test files. Front end (React + TypeScript): 47 screens, 90 components, about 26,700 lines, plus 41 browser test files. An Android app wraps the same front end.

**How it grew**

| When | What was built |
|---|---|
| 20 Sep to 6 Oct | Moved from the earlier platform; the two-division split (Legal Intelligence and Legal Recovery); first Recovery features (statements, reminders, logo). |
| 19 Oct onward | Audit phases: safety net, security, correctness, the verified-law library with its review gate, leaving the earlier vendors for Gemini, Stripe and Resend, roles and permissions, backups. Automatic model routing between Gemini, Claude Haiku and Claude Sonnet. |
| Late October | The redesign (look, menus, phone screens); the Legal Katalyst name and its five tools; Authority Check, List of dates, Defect check, Old-code checker, Deadline engine; the guided Legal Recovery flow. |
| Early November | Spending caps, claim-check hardening, privacy fixes, a free staging path prepared; the RAG work (ranking by exact citation and rare words, a rule against weak matches, a citation side panel); a mock test of 130,000 requests with 0 disagreements; official court holiday lists staged (not yet reviewed). |
| 9 to 12 November | Workspace features: Word, Excel, PowerPoint, email and zip files; OCR in ten Indian languages; an in-page PDF reader with notes and selectable text; document comparison; client records; a malware-scan hook; a Word-text editor; Legal Recovery made a small free helper behind one switch; Word and Google Docs add-ins for four Katalyst checks; stronger reading-engine prompt; removal of 21 unused packages and some dead code. |

**How it was checked (honest numbers).** Last full backend run (2026-11-11): 11,552 tests passed, 0 failed. Front end: 193 unit tests. Browser: 101 tests passed on the cleaned code, including accessibility scans. The last complete release stamp (all suites on a clean tree) is for commit `22294a1`; commits after it were checked by their own test runs and a new full check was running when this was written.

## Part 3. What the app still needs

**A. Only the owner can unblock**

| Need | Why it matters |
|---|---|
| **A named reviewing advocate** | The reviewed law library has 0 VERIFIED entries, so legal questions honestly answer "could not check". The same person unlocks a lawyer-checked question set, real answer-quality measurement, the court calendars and the Limitation Act table. |
| **Decide embeddings** | Keep keyword search plus translation, host a multilingual model, or use Gemini's embedding API (section 4 of Part 4). |
| **A staging server** | Needed to test the Android app and to try the add-ins against a real address. There is no public link to the app yet. |
| **Page headers for `/addin/`** | Word's panel needs a relaxed header on that path only; the rest of the site stays strict. |
| **Install ClamAV on the server** | Only a stand-in scanner has been tested. Then set `MALWARE_SCAN=required`. |
| **Lawyer review of the text** | Privacy and Terms drafts, the Legal Recovery notice wording and the portal facts are all marked unverified. |
| **Trade mark and logo** | Check that "VIDHI" is free as a name and on the social accounts; choose the final logo. |

**B. Built but not tested for real**
- Answer quality from a real model (no paid call has been made), and Hindi, Telugu and Tamil answer quality.
- The Word panel inside real Word and the Google Docs add-on inside real Google Docs (only syntax-checked there).
- The Android app against a staging server; the malware scan with real ClamAV.
- The full browser suite and a release stamp on the very latest commits.

**C. Not built yet**
- Detection of overruled or reversed judgments and statute currency (needs reviewed data).
- Meaning-based search and a re-ranker; court, language and matter filters on retrieval.
- Clause extraction, due-diligence review, the firm playbook tier and research-to-draft (Part 4, section 8).
- A background job queue (Redis or Celery); search servers such as OpenSearch were skipped on purpose.

# Part 4. Brief for Argon (Gemini)
"""

STYLES = getSampleStyleSheet()
BODY = ParagraphStyle("b", parent=STYLES["BodyText"], fontSize=9, leading=12, spaceAfter=3)
CELL = ParagraphStyle("c", parent=BODY, fontSize=7.4, leading=9, spaceAfter=0)
CELLH = ParagraphStyle("ch", parent=CELL, fontName="Helvetica-Bold")
H1 = ParagraphStyle("h1", parent=STYLES["Heading1"], fontSize=16, leading=19, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#102a56"))
H2 = ParagraphStyle("h2", parent=STYLES["Heading2"], fontSize=12.5, leading=15, spaceBefore=10, spaceAfter=4, textColor=colors.HexColor("#102a56"))
H3 = ParagraphStyle("h3", parent=STYLES["Heading3"], fontSize=10.5, leading=13, spaceBefore=6, spaceAfter=3)
BUL = ParagraphStyle("bu", parent=BODY, leftIndent=14, bulletIndent=3)
CODE = ParagraphStyle("code", fontName="Courier", fontSize=6.8, leading=8.4, leftIndent=6, backColor=colors.HexColor("#f2f4f8"), borderPadding=4, spaceAfter=6)

SUBS = [("→", "->"), ("←", "<-"), ("↓", "v"), ("≥", ">="), ("≤", "<="), ("“", '"'), ("”", '"'), ("’", "'"), ("‘", "'")]


def clean(text: str) -> str:
    for a, b in SUBS:
        text = text.replace(a, b)
    return text


def inline(text: str, guard: Guard) -> str:
    t = guard.escape(clean(text))
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8">\1</font>', t)
    return t


def table(rows: list[list[str]], guard: Guard, width: float):
    n = len(rows[0])
    weights = []
    for c in range(n):
        longest = max(len(r[c]) if c < len(r) else 0 for r in rows)
        weights.append(min(max(longest, 10), 70) ** 0.8)
    total = sum(weights)
    widths = [width * w / total for w in weights]
    data = []
    for i, r in enumerate(rows):
        r = (r + [""] * n)[:n]
        data.append([Paragraph(inline(x, guard), CELLH if i == 0 else CELL) for x in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9aa3b2")), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3e8f1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def story_from_markdown(md: str, guard: Guard, width: float, first_h1_page_break: bool = False) -> list:
    story: list = []
    lines = md.replace("\r\n", "\n").split("\n")
    i = 0
    para: list[str] = []

    def flush():
        if para:
            story.append(Paragraph(inline(" ".join(para), guard), BODY))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.strip().startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(clean(lines[i]))
                i += 1
            story.append(Preformatted("\n".join(block), CODE))
        elif ln.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            story += [table(rows, guard, width), Spacer(1, 6)]
            continue
        elif ln.startswith("# "):
            flush()
            if first_h1_page_break:
                story.append(PageBreak())
            story.append(Paragraph(inline(ln[2:], guard), H1))
        elif ln.startswith("## "):
            flush()
            story.append(Paragraph(inline(ln[3:], guard), H2))
        elif ln.startswith("### "):
            flush()
            story.append(Paragraph(inline(ln[4:], guard), H3))
        elif re.match(r"^\s*([-*]|\d+\.)\s+", ln):
            flush()
            m = re.match(r"^\s*([-*]|\d+\.)\s+(.*)$", ln)
            bullet = "•" if m.group(1) in "-*" else m.group(1)
            story.append(Paragraph(inline(m.group(2), guard), BUL, bulletText=bullet))
        elif ln.strip() in ("---", "***"):
            flush()
            story.append(Spacer(1, 4))
        elif not ln.strip():
            flush()
        else:
            para.append(ln.strip())
        i += 1
    flush()
    return story


def build() -> int:
    guard = Guard()
    width = A4[0] - 2 * 40
    brief = open(os.path.join(ROOT, "docs", "ARGON_BRIEF.md"), encoding="utf-8").read()
    brief = brief.split("\n", 1)[1]  # its own title is replaced by Part 4's heading
    brief = re.sub(r"^## (\d+)\. ", r"## 4.\1 ", brief, flags=re.M)  # section numbers inside Part 4
    brief = re.sub(r"^### (\d+)\.(\d+) ", r"### 4.\1.\2 ", brief, flags=re.M)  # and their sub-sections
    story = story_from_markdown(PARTS_1_TO_3, guard, width)
    story += story_from_markdown(brief, guard, width)
    if guard.count:
        story.insert(1, Paragraph(guard.note(), BODY))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(40, 22, f"VIDHI: the app, what is built, what it needs, brief for Argon. As of {AS_OF}.")
        canvas.drawRightString(A4[0] - 40, 22, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=36, title="VIDHI: the app, what is built, what it needs, brief for Argon", author="VIDHI")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    with open(OUT, "wb") as f:
        f.write(buf.getvalue())
    print(f"wrote {OUT} ({len(buf.getvalue()) // 1024} KB, {doc.page} pages, {guard.count} characters not drawable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
