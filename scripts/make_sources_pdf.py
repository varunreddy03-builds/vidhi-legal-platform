"""Builds docs/INDIA_COURTS_AND_LAW_SOURCES.pdf from the repo's own legal directory (backend/data/legal_directory/curated.json) plus a guide to free sources of cases and tax law.
Reads local files only. It downloads nothing and copies no court's or publisher's text."""

import json
import html
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = "docs/INDIA_COURTS_AND_LAW_SOURCES.pdf"
D = json.loads(Path("backend/data/legal_directory/curated.json").read_text(encoding="utf-8"))
OFF = json.loads(Path("backend/data/legal_directory/official_lists.json").read_text(encoding="utf-8"))
INK, MUTED, ACCENT = colors.HexColor("#1B2430"), colors.HexColor("#5A6675"), colors.HexColor("#2F5BD3")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=16, textColor=ACCENT, spaceBefore=4, spaceAfter=7)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, textColor=INK, spaceBefore=9, spaceAfter=3)
P = ParagraphStyle("P", parent=ss["BodyText"], fontName="Helvetica", fontSize=10, leading=14, textColor=INK, spaceAfter=5)
SM = ParagraphStyle("S", parent=P, fontSize=8.6, leading=11.2, textColor=MUTED)
CELL = ParagraphStyle("C", parent=P, fontSize=8.4, leading=10.8, spaceAfter=0)
HEAD = ParagraphStyle("HD", parent=CELL, fontName="Helvetica-Bold")
TITLE = ParagraphStyle("T", parent=H1, fontSize=26, leading=30)


def esc(x):
    return html.escape(str(x or ""))


def bl(items):
    return ListFlowable([ListItem(Paragraph(i, P), leftIndent=12) for i in items], bulletType="bullet", start="•", leftIndent=12, bulletFontSize=9)


def tb(rows, widths):
    data = [[Paragraph(c, HEAD if r == 0 else CELL) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FB")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1DE")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def footer(c, d):
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, 11 * mm, "India's courts and law sources. A directory that points to official sources. Not legal advice.")
    c.drawRightString(192 * mm, 11 * mm, f"Page {d.page}")
    c.restoreState()


SECTIONS = [("courts", "Courts"), ("tribunals", "Tribunals"), ("revenue", "Revenue courts and offices"), ("portals", "Portals"), ("legislation", "Where Acts and rules are published"),
            ("rules_and_formats", "Court rules and filing formats"), ("judgments_and_reporters", "Judgments and law reports"), ("legal_aid", "Legal aid"), ("reference_works", "Reference works")]

s = []
s += [Spacer(1, 30 * mm), Paragraph("India's courts and law sources", TITLE), Paragraph("Courts from the Supreme Court to the district, tribunals, tax law, and where to find free sources", ParagraphStyle("tg", parent=P, fontSize=11.5, textColor=MUTED)), Spacer(1, 6 * mm)]
s += [Paragraph("This paper is a <b>directory</b>. It points to official sources and says what each one is for. It does <b>not</b> contain court judgments or Act text. I did not bulk-download any court's data, because the official court portals use CAPTCHAs or restrict automated access, and VIDHI does not work around that. Where a link was checked, the check date is VIDHI's own (see the notes in the repository). Everything marked <b>VERIFY</b> has not been confirmed and a person should open the link first.", P)]
s += [Paragraph("<b>Who wrote it.</b> The court list below comes from VIDHI's own directory file. Its descriptions are short general descriptions that a lawyer has NOT yet reviewed. The tax and free-source sections are from general knowledge and the repository's source notes, not from fresh downloads.", SM)]
s += [PageBreak()]

s += [Paragraph("1. How the courts are organised (general picture)", H1)]
s += [Paragraph("Names, money limits and powers of the lower courts differ from State to State. This is the common pattern only.", SM)]
s += [tb([
    ["Level", "What it is", "Where to look"],
    ["Supreme Court of India", "Highest court. Appeals from High Courts and tribunals, and some cases directly.", "sci.gov.in"],
    ["High Courts (25)", "One for each State or group of States. Hear appeals from the district level and some cases directly. Supervise the courts below them.", "Each court's own website; list on ecourts.gov.in"],
    ["District and Sessions Courts", "The main trial court of a district. The District Judge hears civil matters and the Sessions Judge hears serious criminal cases. Run by the High Court.", "services.ecourts.gov.in; each district's page (VERIFY the address pattern for your district)"],
    ["Subordinate civil courts", "Civil Judge (Senior and Junior Division), Munsif and similar. Names vary by State.", "The district's page; the State's civil courts Act"],
    ["Subordinate criminal courts", "Chief Judicial Magistrate, Judicial Magistrates, Metropolitan Magistrates.", "The district's page; the Code of Criminal Procedure (now the BNSS)"],
    ["Special courts", "Small Causes, Family, Commercial, Consumer and others, set up by their own Acts.", "The Act that created each court"],
    ["Revenue courts and offices", "Tehsildar, Sub-Collector, Collector and revenue tribunals. They decide land and revenue matters. Differ by State.", "The State's revenue department; the State's land revenue Act"],
    ["Tribunals", "Specialised bodies, for example for tax, company law, administrative and armed forces matters.", "Each tribunal's own site (see section 3)"],
    ["Lok Adalat and legal aid", "Settlement forums and free legal help run by legal services authorities.", "nalsa.gov.in and each State legal services authority"],
], [34 * mm, 82 * mm, 58 * mm])]
s += [Paragraph("Why there is no single downloadable list of every court", H2)]
s += [bl([
    "There are several hundred districts and thousands of court complexes. Each has its own page, and the lower courts' data is reached through the eCourts portal, which uses CAPTCHAs for most searches.",
    "Bulk data from the eCourts system is held by the e-Committee of the Supreme Court. A written request is the lawful route; one was sent on this project and a reply is pending.",
    "Public datasets exist for High Court and Supreme Court judgments (section 4), but the district-court data available publicly is limited and some of it carries a non-commercial licence. Check the licence before using it in a product.",
])]
s += [PageBreak()]

s += [Paragraph("2. VIDHI's directory of official sources", H1)]
s += [Paragraph(esc(D["about"]), SM)]
for key, title in SECTIONS:
    rows = [e for e in D["entries"] if e.get("section") == key]
    if not rows:
        continue
    s += [Paragraph(title, H2)]
    table = [["Name", "What it is", "Law or basis", "Link"]]
    for e in sorted(rows, key=lambda x: x.get("order", 0)):
        link = e.get("url") or e.get("search_url") or "see the name above"
        table.append([esc(e.get("name")) + (" (official)" if e.get("official") else ""), esc(e.get("what")), esc(e.get("law")), esc(link)])
    s += [tb(table, [38 * mm, 66 * mm, 32 * mm, 38 * mm])]
s += [PageBreak()]

hc = OFF.get("high_courts", {})
s += [Paragraph("3. Tax law and tax tribunals", H1)]
s += [Paragraph("Tax has its own Acts, departments and appeal route. The addresses below come from general knowledge and should be opened and checked before use. <b>VERIFY</b> each one.", SM)]
s += [tb([
    ["Area", "Main law (central)", "Where the official text and notices are published", "Appeal route (general picture)"],
    ["Income tax", "Income-tax Act and rules; a new Act has been enacted, check which one applies to your year", "Income Tax Department (incometaxindia.gov.in); Central Board of Direct Taxes circulars and notifications", "Commissioner (Appeals), then the Income Tax Appellate Tribunal, then the High Court, then the Supreme Court"],
    ["GST", "Central GST, Integrated GST and State GST Acts, with rules", "GST portal (gst.gov.in); GST Council; Central Board of Indirect Taxes and Customs (cbic.gov.in)", "Appellate Authority, then the GST Appellate Tribunal where set up, then the High Court"],
    ["Customs and central excise", "Customs Act, Customs Tariff Act", "cbic.gov.in", "Commissioner (Appeals), then CESTAT, then the High Court or Supreme Court as the law provides"],
    ["State taxes and stamp duty", "Each State's own Acts (VAT legacy, stamp duty, professional tax)", "The State's commercial taxes or revenue department site", "Differ by State"],
    ["Company and other regulation", "Companies Act and related", "Ministry of Corporate Affairs (mca.gov.in); NCLT and NCLAT sites", "NCLT, then NCLAT, then the Supreme Court"],
], [24 * mm, 46 * mm, 56 * mm, 48 * mm])]
s += [Paragraph("Tax judgments", H2)]
s += [bl([
    "High Court and Supreme Court judgments on tax are inside the public judgment datasets (section 4); tribunal orders are on each tribunal's own site and are not in those datasets.",
    "Commercial tax libraries (for example Taxmann or TaxGuru-style services) are privately owned. Reproducing their text needs a licence. Do not copy it.",
    "For any figure, rate or due date, use the official notification and its date. Tax rates change often and an old copy can be wrong.",
])]
s += [PageBreak()]

s += [Paragraph("4. Free and low-cost sources of cases, and what each allows", H1)]
s += [Paragraph("From the repository's source notes (docs/WHERE_TO_GET_LAW.md and docs/legal-sources-terms.md). Terms change, so read the current terms before relying on any row.", SM)]
s += [tb([
    ["Source", "What it has", "Use and licence (as noted in the repo)", "Status here"],
    ["Supreme Court judgments, open dataset (AWS Open Data, \"indian-supreme-court-judgments\")", "Supreme Court judgments with metadata", "Published under CC BY 4.0; credit must be given", "Already used in VIDHI's Authority Check"],
    ["Indian High Court judgments, open dataset (AWS Open Data, \"indian-high-court-judgments\")", "Judgments from 25 High Courts with metadata and PDFs", "Licence terms to be re-read before reuse (VERIFY)", "Metadata indexed in VIDHI: about 17.9 million records; full text only for about 22,800"],
    ["Indian Kanoon website and API", "Search across courts and tribunals", "The API is prepaid, pay per call, needs a visible credit and a signed key; scraping the website is not allowed. A free allowance may exist (VERIFY on their pricing page)", "No key in use; the earlier token was revoked. Nothing downloaded from it"],
    ["India Code (indiacode.nic.in)", "Central Acts with amendments", "Personal, non-commercial use only; automated access and commercial reuse need written permission", "Permission emails sent; reply pending; nothing loaded"],
    ["Official gazettes and ministry sites", "Notifications, rules, circulars", "Download by hand; check each site's terms", "Case by case"],
    ["SCC Online, Manupatra, AIR and similar", "Reported judgments and annotated Acts", "Private; licence required; cannot be copied", "Not used"],
], [48 * mm, 36 * mm, 56 * mm, 34 * mm])]
s += [Paragraph("What I did and did not do for this paper", H2)]
s += [bl([
    "I <b>did not</b> download district-court data, Indian Kanoon content, or any tax library. The official portals block automated access, Indian Kanoon's terms forbid scraping, and VIDHI has no active key.",
    "I <b>did</b> assemble the court and source directory VIDHI already holds, and added the tax and free-source guides from the repository's notes and general knowledge.",
    "A person can open each link above and download an official PDF by hand. VIDHI's rule is that law enters only as official text with its source and date, reviewed by a named advocate.",
])]
s += [Paragraph("Next steps for the owner", H2)]
s += [bl([
    "Wait for the e-Committee and High Court replies; they are the lawful route to bulk lower-court data.",
    "Choose which Acts an advocate will review first (tax Acts can be on that list).",
    "Decide whether to buy an Indian Kanoon API allowance or a commercial licence, and read the terms first.",
    "Ask an advocate to confirm every point marked VERIFY.",
])]

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="India's courts and law sources", author="VIDHI")
doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
