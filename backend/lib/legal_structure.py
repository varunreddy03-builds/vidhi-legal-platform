"""Turns the plain text of an Act into provisions that keep their legal structure. Pure code: no database, no AI, nothing invented.

A provision (a section) is stored as ONE canonical record: its number, heading, where it sits (part, chapter), the page it starts on, the exact original
text, and an ordered list of components: the rule (with its numbered subsections and lettered clauses), provisos, explanations, illustrations and exceptions.
A proviso or exception is therefore always attached to the rule it limits and can never be dropped by cutting text into pieces.

Long provisions are also cut into child chunks (for matching and future search). A chunk never stands alone: it carries its parent's id, path and heading,
and `render_parent` always returns the complete provision with a flag saying whether every component was included.

The parser is deliberately cautious. It recognises the usual layout of Indian Acts ("12. Heading.-Text", "Provided that", "Explanation.-", "Illustration",
"Exception"), requires section numbers to run forward, and reports anything it could not place in `warnings` instead of guessing. It does not know what any section
means, and a person must still compare the parsed result with the official text before it can be reviewed as law."""

import re
from dataclasses import dataclass, field

DASH = r"[—–-]{1,2}"
SECTION = re.compile(r"^\s*(?P<num>\d{1,4}[A-Z]{0,3})\.\s+(?P<rest>\S.*)$")
HEAD_BODY = re.compile(rf"^(?P<h>.{{3,200}}?)\.\s*{DASH}\s*(?P<b>.*)$")
CHAPTER = re.compile(r"^\s*(?P<kind>CHAPTER|PART)\s+(?P<label>[IVXLCDM\d]+[A-Z]?)\b\.?\s*(?P<title>.*)$")
SCHEDULE = re.compile(r"^\s*(?:THE\s+)?(?P<name>[A-Z]+|\d+(?:ST|ND|RD|TH))\s+SCHEDULE\b(?P<rest>.*)$")
PROVISO = re.compile(r"^\s*Provided(?:\s+further)?(?:\s+also)?\s+that\b")
INLINE_PROVISO = re.compile(r"(?<=[;,.:—–-])\s+(?=Provided(?:\s+further)?(?:\s+also)?\s+that\b)")
EXPLANATION = re.compile(r"^\s*Explanation(?:s)?\b")
ILLUSTRATION = re.compile(r"^\s*Illustration(?:s)?\b")
EXCEPTION = re.compile(r"^\s*Exception(?:s)?\b")
SUBSECTION = re.compile(r"^\s*\((?P<l>\d{1,3}[A-Z]?)\)\s+\S")
CLAUSE = re.compile(r"^\s*\((?P<l>[a-z]{1,2})\)\s+\S")
KINDS = ("rule", "subsection", "clause", "proviso", "explanation", "illustration", "exception")


@dataclass
class Component:
    kind: str
    label: str
    lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label, "text": "\n".join(self.lines).strip()}


def _num_key(num: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", num)
    return int(m.group(1)), m.group(2)


def _split_components(body_lines: list[str]) -> list[dict]:
    comps: list[Component] = [Component("rule", "")]
    for line in body_lines:
        s = line.strip()
        if not s:
            comps[-1].lines.append("")
            continue
        new: tuple[str, str] | None = None
        if PROVISO.match(line):
            new = ("proviso", "")
        elif EXPLANATION.match(line):
            new = ("explanation", re.match(r"^\s*(Explanations?(?:\s*\d+[A-Za-z]?)?)", line).group(1))
        elif ILLUSTRATION.match(line):
            new = ("illustration", "")
        elif EXCEPTION.match(line):
            new = ("exception", re.match(r"^\s*(Exceptions?(?:\s*\d+[A-Za-z]?)?)", line).group(1))
        elif (m := SUBSECTION.match(line)) and comps[-1].kind in ("rule", "subsection", "clause"):
            new = ("subsection", f"({m.group('l')})")
        elif (m := CLAUSE.match(line)) and comps[-1].kind in ("subsection", "clause", "rule") and (comps[-1].kind != "rule" or comps[-1].lines):
            new = ("clause", f"({m.group('l')})")
        if new:
            comps.append(Component(new[0], new[1], [line.rstrip()]))
        else:
            comps[-1].lines.append(line.rstrip())
    out: list[dict] = []
    for c in comps:
        d = c.as_dict()
        if not d["text"]:
            continue
        if c.kind in ("rule", "subsection", "clause") and len(INLINE_PROVISO.split(d["text"])) > 1:
            parts = INLINE_PROVISO.split(d["text"])  # "...; Provided that ..." inside one paragraph: the proviso becomes its own component
            out.append({**d, "text": parts[0].strip()})
            out.extend({"kind": "proviso", "label": "", "text": p.strip()} for p in parts[1:] if p.strip())
        else:
            out.append(d)
    return out


def parse_provisions(pages: list[str]) -> dict:
    """pages: the text of each page, in order. Returns {"provisions": [...], "warnings": [...]}.
    Each provision: number, heading, part, chapter, page_start, components, text_full (the exact original lines)."""
    lines: list[tuple[int, str]] = [(i + 1, ln) for i, page in enumerate(pages) for ln in page.splitlines()]
    provisions: list[dict] = []
    warnings: list[str] = []
    part = chapter = None
    cur: dict | None = None
    last_key = (0, "")
    in_schedule = False

    def close():
        nonlocal cur
        if cur:
            body = cur.pop("_body")
            cur["components"] = _split_components(body)
            cur["text_full"] = "\n".join(cur.pop("_raw")).strip()
            provisions.append(cur)
        cur = None

    idx = 0
    while idx < len(lines):
        page, line = lines[idx]
        idx += 1
        if in_schedule:
            cur["_raw"].append(line)
            cur["_body"].append(line)
            continue
        sched = SCHEDULE.match(line)
        if sched and line.strip() == line.strip().upper() and len(line.strip()) < 60:
            close()
            in_schedule = True
            cur = {"number": f"Schedule {sched.group('name').title()}", "heading": line.strip(), "part": part, "chapter": chapter, "page_start": page, "kind": "schedule", "_raw": [line], "_body": []}
            continue
        ch = CHAPTER.match(line)
        if ch and not SECTION.match(line):
            label = f"{ch.group('kind')} {ch.group('label')}"
            title = ch.group("title").strip(" .-—–")
            if not title and idx < len(lines) and lines[idx][1].strip() and lines[idx][1].strip() == lines[idx][1].strip().upper() and not SECTION.match(lines[idx][1]):
                title = lines[idx][1].strip()
                idx += 1
            if ch.group("kind") == "PART":
                part, chapter = (label + (f" {title}" if title else "")), None
            else:
                chapter = label + (f" {title}" if title else "")
            continue
        sec = SECTION.match(line)
        if sec:
            num, rest = sec.group("num"), sec.group("rest").strip()
            key = _num_key(num)
            hb = HEAD_BODY.match(rest)
            heading_only = None
            if not hb and len(rest) < 200 and not rest.endswith(",") and not rest.endswith(";"):
                nxt = lines[idx][1].strip() if idx < len(lines) else ""
                if nxt and (rest.endswith(".") or rest.endswith(".—")) and key >= last_key:
                    heading_only = rest.rstrip(".— ")
            if (hb or heading_only is not None) and key >= last_key:
                close()
                last_key = key
                heading = hb.group("h").strip() if hb else heading_only
                first = hb.group("b").strip() if hb else ""
                cur = {"number": num, "heading": heading, "part": part, "chapter": chapter, "page_start": page, "kind": "section", "_raw": [line], "_body": [first] if first else []}
                continue
            if cur is None:
                warnings.append(f"page {page}: numbered line before any section was not placed: {line.strip()[:60]!r}")
        if cur is not None:
            cur["_raw"].append(line)
            cur["_body"].append(line)
        elif line.strip() and not (line.strip() == line.strip().upper() and len(line.strip()) < 120):  # an all-capitals title line ("THE ... ACT, 1901") is expected before section 1
            warnings.append(f"page {page}: text before the first section was not placed: {line.strip()[:60]!r}")
    close()
    seen: dict[str, int] = {}
    for p in provisions:
        seen[p["number"]] = seen.get(p["number"], 0) + 1
    for n, c in seen.items():
        if c > 1:
            warnings.append(f"section number {n} appears {c} times; check the text")
    for p in provisions:
        if p["kind"] == "section" and not any(c["kind"] in ("rule", "subsection", "clause") and c["text"] for c in p["components"]):
            warnings.append(f"section {p['number']} has no operative text; check the text")
    return {"provisions": provisions, "warnings": warnings}


def make_chunks(provision: dict, max_chars: int = 1800) -> list[dict]:
    """Child chunks of one provision, in order. Together they cover every component exactly once; each knows its parent and where it sits."""
    header = " > ".join(x for x in (provision.get("part"), provision.get("chapter"), f"{provision.get('number')}. {provision.get('heading', '')}".strip()) if x)
    comps = provision["components"]
    chunks: list[dict] = []
    group: list[int] = []
    size = 0

    def flush():
        nonlocal group, size
        if group:
            chunks.append({"ordinal": len(chunks), "component_range": [group[0], group[-1]], "header": header, "text": "\n".join(comps[i]["text"] for i in group)})
        group, size = [], 0

    for i, c in enumerate(comps):
        if len(c["text"]) > max_chars:
            flush()
            sentences = re.split(r"(?<=[.;])\s+", c["text"])
            piece, plen = [], 0
            for s in sentences:
                if plen + len(s) > max_chars and piece:
                    chunks.append({"ordinal": len(chunks), "component_range": [i, i], "header": header, "text": " ".join(piece)})
                    piece, plen = [], 0
                piece.append(s)
                plen += len(s) + 1
            if piece:
                chunks.append({"ordinal": len(chunks), "component_range": [i, i], "header": header, "text": " ".join(piece)})
            continue
        if size + len(c["text"]) > max_chars:
            flush()
        group.append(i)
        size += len(c["text"])
    flush()
    return chunks


def render_parent(provision: dict, included: list[int] | None = None) -> dict:
    """The complete provision as the model or a reader must see it: ALWAYS every component, in order. `included` (optional) lists the component numbers a caller
    claims to have used; `complete` is false if that does not cover every component, so a partial use can be detected and refused."""
    comps = provision["components"]
    return {
        "citation_number": provision["number"], "heading": provision.get("heading", ""), "path": [x for x in (provision.get("part"), provision.get("chapter")) if x],
        "components": comps, "complete": bool(comps) and (included is None or sorted(set(included)) == list(range(len(comps)))),
        "limits": [c for c in comps if c["kind"] in ("proviso", "exception")],
        "text": "\n".join(c["text"] for c in comps),
    }
