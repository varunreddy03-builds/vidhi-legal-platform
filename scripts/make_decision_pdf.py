"""Builds docs/VIDHI_BUILD_DECISION.pdf: continue VIDHI or rebuild from scratch, in plain and technical terms. No network."""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

OUT = "docs/VIDHI_BUILD_DECISION.pdf"
INK, MUTED, ACCENT = colors.HexColor("#1B2430"), colors.HexColor("#5A6675"), colors.HexColor("#2F5BD3")
ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=17, textColor=ACCENT, spaceBefore=4, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12, textColor=INK, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("P", parent=ss["BodyText"], fontName="Helvetica", fontSize=10.3, leading=14.5, textColor=INK, spaceAfter=5)
SM = ParagraphStyle("S", parent=P, fontSize=8.8, leading=11.5, textColor=MUTED)
CELL = ParagraphStyle("C", parent=P, fontSize=8.8, leading=11.5, spaceAfter=0)
HEAD = ParagraphStyle("HD", parent=CELL, fontName="Helvetica-Bold")
TITLE = ParagraphStyle("T", parent=H1, fontSize=28, leading=32)


def bl(items):
    return ListFlowable([ListItem(Paragraph(i, P), leftIndent=12) for i in items], bulletType="bullet", start="•", leftIndent=12, bulletFontSize=9)


def tb(rows, widths):
    data = [[Paragraph(c, HEAD if r == 0 else CELL) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FB")), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D1DE")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def footer(c, d):
    c.saveState()
    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    c.drawString(18 * mm, 11 * mm, "VIDHI: continue or rebuild. Working paper, not legal advice.")
    c.drawRightString(192 * mm, 11 * mm, f"Page {d.page}")
    c.restoreState()


W = 174 * mm
s = []
s += [Spacer(1, 35 * mm), Paragraph("Continue VIDHI or build from scratch", TITLE), Paragraph("A balanced comparison, in plain and technical terms", ParagraphStyle("tg", parent=P, fontSize=12, textColor=MUTED)), Spacer(1, 8 * mm)]
s += [Paragraph("The goal is a complete software system for Indian lawyers and law firms, in the way tools such as Harvey serve firms elsewhere. The question is whether to keep building on VIDHI or to start again.", P)]
s += [Paragraph("<b>How to read this paper.</b> Part 1 is for non-technical readers. Part 2 is for engineers. Part 3 is the comparison and the decision rules. Facts about VIDHI come from its own project notes. Things I have not checked are marked <b>NOT CHECKED</b>. Time and cost figures are rough estimates, not measurements. Statements about other companies' products are from general knowledge and are not verified.", SM)]
s += [Spacer(1, 4 * mm), Paragraph("<b>Short answer.</b> Nothing found so far shows that VIDHI must be thrown away. Nothing found so far proves it can carry a firm-grade product either. A one to two day audit of five specific points (Part 3) would settle it. Until then the lower-risk path is to continue, and to clean as you go.", P)]
s += [PageBreak()]

s += [Paragraph("Part 1. For non-technical readers", H1)]
s += [Paragraph("What VIDHI is today", H2)]
s += [bl([
    "A working web and phone application with two parts (Legal Recovery, a small third option, was switched off by the owner on 2026-11-15 and is hidden, not deleted): <b>Legal Intelligence</b> (ask a question, research, case files called matters, drafting) and <b>Legal Katalyst</b> (five checking tools, none of which use AI).",
    "A strict rule that a legal point is shown as <b>Verified</b> only when the exact source text is in a reviewed library. The AI's own opinion never counts.",
    "A very large set of automated checks (about 11,459 backend tests at the last full run) that protect those rules every time code changes.",
    "What is still missing: reviewed law in the library, live AI answers tested on real questions, any real lawyer using it, and hosting for the public.",
])]
s += [Paragraph("What a firm product needs beyond that", H2)]
s += [bl([
    "A shared workspace for each case, where each person sees only what they should.",
    "Sign-in through the firm's own system, and a record of who opened what.",
    "A promise about where client papers are stored and which AI company sees them.",
    "Repeatable jobs (for example, check this draft before filing) that anyone in the firm can run.",
    "A real server, backups, and someone on call when it breaks.",
])]
s += [Paragraph("The two choices in plain words", H2)]
s += [tb([
    ["", "Continue VIDHI", "Start from scratch"],
    ["Picture it as", "Renovating a house that stands and passes inspection, but has rooms you do not need.", "Building a new house on the same plot. The design can be better, but nothing stands until it is finished."],
    ["When lawyers can first test it", "Weeks (estimate).", "Many months (estimate)."],
    ["What you keep", "Rules, tests, security work, the screens.", "Only what you decide to copy over."],
    ["Main risk", "Hidden limits in the old design that block firm features.", "Months spent rebuilding what already works, while lawyer feedback waits."],
    ["Main reward", "Speed and a safety net.", "A structure made for firms from day one."],
], [30 * mm, 72 * mm, 72 * mm])]
s += [Paragraph("What neither choice fixes", H2)]
s += [Paragraph("Three things decide whether the product succeeds, and a rewrite touches none of them:", P)]
s += [bl([
    "<b>The law data.</b> The library must hold statutes and judgments an advocate has compared with the official source. Without it, every legal answer correctly says it could not check. Much Indian legal content is privately owned (SCC, AIR) or needs government permission. Permission emails to about 18 offices have been sent; replies are pending.",
    "<b>Real lawyers using it.</b> Lawyers adopt slowly, by word of mouth, after seeing it work on their own papers.",
    "<b>Trust and hosting.</b> A firm will ask where its data lives and who can read it before it signs anything. The business also has to be registered before payments, app stores and contracts.",
])]
s += [Paragraph("Money, people and time (rough)", H2)]
s += [tb([
    ["Item", "Continue VIDHI", "Start from scratch"],
    ["Engineering time before a pilot", "Weeks. Estimate only.", "Many months. Estimate only."],
    ["People needed", "One engineer plus an advocate partner can progress.", "More engineers, or a much longer timeline."],
    ["Ongoing cost", "Hosting, AI use (capped in the app), email, monitoring.", "The same, plus the cost of the rebuild."],
    ["Money already spent that is reused", "Most of it.", "Little, apart from lessons learned."],
], [44 * mm, 65 * mm, 65 * mm])]
s += [PageBreak()]

s += [Paragraph("Part 2. For engineers", H1)]
s += [Paragraph("What VIDHI is built on (from the project notes)", H2)]
s += [tb([
    ["Layer", "Today", "Note"],
    ["Backend", "FastAPI (Python), MongoDB through motor", "Routers per feature; shared libraries in backend/lib."],
    ["Frontend", "React, Vite, TypeScript, Tailwind-style components", "Light and dark themes; many languages; phone-first layouts."],
    ["Phone shell", "Capacitor (Android built; iOS not built)", "A web app wrapped for stores. Not needed for a firm web product."],
    ["Search", "Exact-citation lookup, Tantivy keyword indexes, versioned verified store", "Embeddings and re-ranker exist behind switches; NOT enabled or measured."],
    ["Claim checking", "lib/verify.py and lib/textmatch.py decide the label in code", "Model opinion can lift a claim to at most Partly verified."],
    ["Safety", "Prompt-injection fencing, per-organisation data separation, role-based access, AI spending caps", "Security audit items mostly closed; two open (AL2, S8)."],
    ["Tests", "About 11,459 backend tests; frontend unit tests; Playwright browser tests", "Full backend run takes roughly 17 to 40 minutes."],
    ["Hosting", "Local development; temporary tunnels for demos", "No production server yet."],
], [28 * mm, 70 * mm, 76 * mm])]
s += [Paragraph("Technical comparison", H2)]
s += [tb([
    ["Concern", "Continue VIDHI", "Rebuild"],
    ["Multi-tenancy", "Per-organisation data separation exists with cross-organisation tests. NOT CHECKED: behaviour with many firms, noisy neighbours, per-firm encryption keys or regional storage.", "Can be designed in (row-level security, per-tenant keys). Needs full re-implementation and re-testing."],
    ["Identity", "Email and password; Google sign-in option. NOT CHECKED: SAML or OIDC single sign-on, SCIM provisioning.", "Choose an identity provider first; usually cheaper to start with than to retrofit."],
    ["Audit trail", "Some logging exists. NOT CHECKED: a complete, tamper-evident record of who read which document.", "Design as append-only events from day one."],
    ["Data store", "MongoDB. Good for documents; NOT CHECKED: reporting, joins across matters, large-scale full-text beyond Tantivy.", "A relational store (for example PostgreSQL) may suit matters, roles and audit better. A trade-off, not a rule."],
    ["Retrieval and RAG", "Layers exist and are partly measured. Rank logic is tested on invented data only.", "Re-implement or port. The reusable part is the design, not the code."],
    ["AI providers", "Built around one provider key today; NOT CHECKED: easy swap or per-firm choice of provider.", "Put a provider-neutral layer first. Also possible inside VIDHI."],
    ["Document processing", "Upload, text extraction and OCR paths exist with page and size limits.", "Needs rebuilding; OCR on scanned and regional-language papers is hard in either path."],
    ["Workflows", "Five fixed tools. NOT CHECKED: a way to define new multi-step jobs without code.", "A workflow engine can be a first-class concept."],
    ["Deployment and operations", "Not yet deployed. No monitoring, backups or on-call.", "Same work, either path."],
    ["Code health", "NOT CHECKED: duplication, dead code, module coupling.", "Starts clean; drifts without discipline."],
], [30 * mm, 72 * mm, 72 * mm])]
s += [Paragraph("Ways to move without a full restart", H2)]
s += [tb([
    ["Option", "What it means", "Effort (estimate)", "Risk"],
    ["Trim and harden", "Hide or remove features that do not fit firms, behind switches, then add firm features one tested step at a time.", "Lowest", "Low"],
    ["Extract a core", "Move the rules and checking logic into a library, then build a new firm workspace layer on top that calls it.", "Medium", "Medium"],
    ["Strangler rebuild", "Replace one part at a time (for example identity, then storage) while the rest keeps running.", "Medium to high", "Medium"],
    ["Full rebuild", "New codebase; copy over the design and test cases, not the code.", "Highest", "Highest"],
], [30 * mm, 78 * mm, 32 * mm, 34 * mm])]
s += [Paragraph("The test cases are an asset in every path. Even in a full rebuild, the attack tests (altered quote, wrong Act, planted instructions in a document) are worth porting as the specification of correct behaviour.", SM)]
s += [PageBreak()]

s += [Paragraph("Part 3. Decision", H1)]
s += [Paragraph("Overall comparison", H2)]
s += [tb([
    ["Point", "Continue VIDHI", "Start from scratch"],
    ["Time to lawyer test", "Weeks", "Many months"],
    ["Feedback from lawyers on the way", "Possible soon", "None until it catches up"],
    ["Rules protected by tests", "About 11,459 tests", "None at the start"],
    ["Honest labels and quote checking", "Built and tested", "Rebuild; easy to get subtly wrong"],
    ["Security and tenancy", "Exist; not audited for firm scale", "Rebuild and re-audit"],
    ["Fit for firms", "Needs adding; some parts may be hard", "Designed in from day one"],
    ["Clutter", "Present (directory, payments code, extra tools); Legal Recovery is already switched off, not deleted; the rest can be hidden or removed in steps", "None at first; grows again"],
    ["Technology choice", "Tied to current stack", "Free choice"],
    ["Risk of new bugs", "Lower for existing parts", "Higher; all new"],
    ["Law data, lawyer use, hosting", "Still open", "Still open"],
], [50 * mm, 62 * mm, 62 * mm])]
s += [Paragraph("Choose by these rules", H2)]
s += [bl([
    "<b>Continue VIDHI</b> if your team is small, you want lawyer feedback within weeks, and the main gaps are data, trust and hosting.",
    "<b>Rebuild</b> if you have several engineers and months of runway, the audit below finds a hard blocker, or you need a structure VIDHI cannot reach.",
    "<b>Extract a core</b> if the audit finds blockers in only one or two layers.",
])]
s += [Paragraph("A one to two day audit would settle it (NOT DONE)", H2)]
s += [tb([
    ["Question", "Why it matters"],
    ["Can one firm's data be isolated, exported and deleted completely, and can every query be proven filtered by organisation?", "Firms will demand this; a gap here is hard to patch."],
    ["Can single sign-on be added without changing how users and organisations are stored?", "Large firms will not use separate passwords."],
    ["Can a full audit trail of reads and exports be added at one point, or must it be added in every router?", "Cost depends on how consistent the code is."],
    ["Does MongoDB suit matters, roles, reporting and per-firm regional storage, or would these force a second database?", "Decides if a data migration is needed."],
    ["How tangled are the modules (coupling and dead code)?", "Decides how costly trimming is."],
], [105 * mm, 69 * mm])]
s += [Paragraph("Recommended order, whichever path you pick", H2)]
s += [bl([
    "<b>1. Choose one wedge for firms.</b> Authority Check plus one repeated job, such as a pre-filing check.",
    "<b>2. Build the verified law library</b> with an advocate partner: statutes first, then judgments, each with an official source and date.",
    "<b>3. Make retrieval measurable.</b> 100 or more questions with advocate-checked answers; track right source in the top 5, correct answers, and confident-but-wrong answers.",
    "<b>4. Run live AI under a spending cap</b> and report accuracy honestly.",
    "<b>5. Add the firm features</b> (workspaces, single sign-on, audit trail, data location) in the order the audit supports.",
    "<b>6. Pilot with 5 to 10 lawyers</b> on their own drafts, then set a price.",
    "<b>7. Consider fine-tuning last</b>, for narrow repeated jobs, only if it beats plain retrieval on your fixed question set. Never train on client papers without written consent.",
])]
s += [Paragraph("What the owner must provide", H2)]
s += [bl([
    "Team size and the months available before lawyers must see something.",
    "The advocate partner's name, and the first 5 to 10 Acts for review.",
    "Permission replies from government offices, as they arrive (about 18 emails sent).",
    "An AI key with a spending cap, to measure live answers.",
    "Business registration, then the domain, email and payment accounts.",
])]

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="VIDHI: continue or rebuild", author="VIDHI")
doc.build(s, onFirstPage=footer, onLaterPages=footer)
print("wrote", OUT)
