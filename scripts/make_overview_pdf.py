"""Builds docs/VIDHI_OVERVIEW.pdf: problem, solution, how the app works, target customers. Plain text only, no network."""

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = "docs/VIDHI_OVERVIEW.pdf"
INK, MUTED, ACCENT = colors.HexColor("#1B2430"), colors.HexColor("#5A6675"), colors.HexColor("#2F5BD3")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=18, textColor=ACCENT, spaceBefore=6, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=INK, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("P", parent=ss["BodyText"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=INK, alignment=TA_LEFT, spaceAfter=6)
SMALL = ParagraphStyle("S", parent=P, fontSize=9, leading=12, textColor=MUTED)
TITLE = ParagraphStyle("T", parent=H1, fontSize=30, leading=34, spaceAfter=4)
TAG = ParagraphStyle("TG", parent=P, fontSize=12, textColor=MUTED)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(i, P), leftIndent=12) for i in items], bulletType="bullet", start="•", leftIndent=12, bulletFontSize=9)


def table(rows, widths):
    data = [[Paragraph(c, SMALL if r else ParagraphStyle("th", parent=SMALL, fontName="Helvetica-Bold", textColor=INK)) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FB")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1DE")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, "VIDHI overview. AI assists. Sources support. Logic verifies. Lawyers decide.")
    canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


s = []
s += [Spacer(1, 40 * mm), Paragraph("VIDHI", TITLE), Paragraph("A careful checker for Indian legal work", TAG), Spacer(1, 6 * mm)]
s += [Paragraph("This paper covers four things: the problem, our solution, how the app works, and who it is for. It is written in plain words for people who are not technical.", P)]
s += [Paragraph("<b>Where we are:</b> the app is built and tested with a scripted stand-in for the AI. It has not yet been tried by real lawyers, and its law library is still empty until an advocate reviews and enters sources. Statements about the market below are our working beliefs, not proven facts.", SMALL)]
s += [PageBreak()]

s += [Paragraph("1. The problem", H1)]
s += [Paragraph("Lawyers in India work under heavy time pressure, and a small slip in a filing can cost a client's case or the lawyer's reputation. Three slips are common and hard to catch by eye in a long draft:", P)]
s += [bullets([
    "<b>Wrong or invented citations.</b> A case or section is quoted that does not exist, or the quote does not match the source. Courts have begun to take this seriously.",
    "<b>Wrong dates.</b> Counting limitation and filing days by hand is slow and easy to get wrong.",
    "<b>Old-law references.</b> Since the new criminal codes replaced the IPC, CrPC and Evidence Act, drafts still mix old and new section numbers.",
])]
s += [Paragraph("Generic \"AI legal research\" tools make this worse for a careful lawyer: they answer confidently, and the lawyer cannot tell which parts are backed by a real source.", P)]
s += [Paragraph("A second, separate problem: small businesses are often not paid on time. The law gives micro and small enterprises a free government route, but most owners do not know it or how to write a proper demand notice.", P)]

s += [Paragraph("2. Our solution", H1)]
s += [Paragraph("VIDHI does not try to be an AI that answers everything. It is the careful checker that sits next to the lawyer's own work. It says what it could confirm, what it could not, and why.", P)]
s += [bullets([
    "<b>Honest labels.</b> Every legal point is shown as Verified, Partly verified or Not supported. \"Verified\" is allowed only when the exact source text is in our reviewed library. The AI's own opinion never counts.",
    "<b>Tools with one right answer use no AI.</b> Dates, old-to-new section mapping and defect checks run from rules that a named person entered and reviewed.",
    "<b>AI only for reading and drafting</b>, and always with sources shown next to each point.",
    "<b>Neutral wording.</b> The app flags inconsistencies. It never says anyone lied. The lawyer decides.",
])]

s += [PageBreak(), Paragraph("3. How the app works", H1)]
s += [Paragraph("VIDHI has two main parts and one small extra.", P)]
s += [Paragraph("Legal Intelligence", H2)]
s += [bullets([
    "<b>Ask:</b> type a question in plain language (including regional languages). The answer is split into numbered points. Each point shows its source, the quoted passage and whether the quote was found exactly.",
    "<b>Research:</b> a deeper version of Ask, optionally using all the documents in one matter.",
    "<b>Matters:</b> a case file for documents, facts, a timeline and evidence.",
    "<b>Drafts:</b> help with first drafts, with sources shown.",
])]
s += [Paragraph("Legal Katalyst (five checks, no AI inside)", H2)]
s += [table([
    ["Tool", "What it does"],
    ["Authority Check", "Do the cited judgments and sections exist, and does each quote match the source?"],
    ["Deadline engine", "Works out due dates from rules a person entered and a named reviewer approved."],
    ["Old-code to new-code checker", "Finds IPC, CrPC and Evidence Act references and shows the matching new section from a reviewed table."],
    ["Pre-filing defect check", "Finds slips such as blanks, inconsistent dates and bad references."],
    ["List of dates", "Builds a list of dates with page references from the papers."],
], [48 * mm, 122 * mm])]
s += [Spacer(1, 3 * mm), Paragraph("Legal Recovery (under More)", H2)]
s += [Paragraph("A small free helper for unpaid dues. It checks whether the free government portal for micro and small enterprises fits, helps write a payment notice that the user downloads and sends, and tracks three dates. It is a guide, not legal advice.", P)]
s += [Paragraph("How a question becomes an answer", H2)]
s += [bullets([
    "The question (and the matter's documents, if chosen) is searched against the reviewed library only.",
    "The AI proposes numbered points with exact quotes from those sources.",
    "Our code, not the AI, checks that each quote exists, that figures match and that the passage bears on the point, and sets the label.",
    "If nothing in the library supports a point, it is shown as Not supported and the app says it could not check.",
])]
s += [Paragraph("Privacy and safety: client papers are treated as private, text from documents is never treated as instructions to the AI, and spending on AI has daily caps.", SMALL)]

s += [PageBreak(), Paragraph("4. Who it is for", H1)]
s += [Paragraph("These are our target groups. They are working beliefs to be tested in conversations with lawyers.", SMALL)]
s += [table([
    ["Customer", "Why they need it", "What they use"],
    ["Solo advocates and small firms", "No team to double-check drafts; one wrong citation is costly.", "Authority Check, Deadline engine, Ask"],
    ["Junior associates and clerks", "Do the first draft and the checking under time pressure.", "Pre-filing defect check, Old-code checker, List of dates"],
    ["In-house legal teams", "Need dates and references right across many matters.", "Matters, Deadline engine, Research"],
    ["Micro and small business owners", "Unpaid dues and no idea how to write a notice.", "Legal Recovery (free)"],
], [45 * mm, 70 * mm, 55 * mm])]
s += [Paragraph("How adoption is expected to happen", H2)]
s += [bullets([
    "Lawyers adopt by word of mouth, and only after seeing it work on their own papers in a few minutes, on a phone, in English or a regional language.",
    "The first product to prove is Authority Check, because it fits a clear need and needs no AI.",
    "A pilot with 5 to 10 lawyers comes before any price is set.",
])]
s += [Paragraph("What is not yet true", H2)]
s += [bullets([
    "No lawyer has used it yet; the interviews that would test the problem have not been done.",
    "The law library and rule tables are empty until an advocate reviews and enters them with official sources.",
    "Live AI answers have not been run on the current version.",
    "The business is not yet registered, so payments and app stores are not yet open.",
])]
s += [Spacer(1, 4 * mm), Paragraph("VIDHI gives information and checks, not legal advice. Lawyers decide.", SMALL)]

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm, title="VIDHI overview", author="VIDHI")
doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
