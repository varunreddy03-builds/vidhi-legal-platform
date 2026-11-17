"""Turns the saved NCRB Sankalan "Chapters and Sections" pages (Ministry of Home Affairs) of the BNS, BNSS and BSA into draft sections in data/legal_library/pending/ncrb-<act>.json.

Nothing is verified or shown by this script: the drafts are UNVERIFIED, and they stay switched off until the permission reference is recorded (lib/library.PERMISSION_REQUIRED_NAMES).
The words of a section are taken exactly as the page prints them. The page's own comparison labels ("(Change)", "(New Addition)", "(Deleted)") are NOT law text: they are cut from the heading and kept
in a separate field. The Schedules are not read here.

    python scripts/ncrb_acts_save.py <folder holding ChaptersBNS.html, ChaptersBNSS.html, ChaptersBSA.html> [--check]
"""

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

PENDING = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "pending"
SOURCE_NAME = "NCRB Sankalan portal (Ministry of Home Affairs): Chapters and Sections"
ACTS = {
    "BNS": ("bns", "The Bharatiya Nyaya Sanhita, 2023", "Act No. 45 of 2023", 358),
    "BNSS": ("bnss", "The Bharatiya Nagarik Suraksha Sanhita, 2023", "Act No. 46 of 2023", 531),
    "BSA": ("bsa", "The Bharatiya Sakshya Adhiniyam, 2023", "Act No. 47 of 2023", 170),
}
LABEL = re.compile(r"\s*\((?:Change|New Addition|New Section|Deleted|Omitted)\)\s*", re.I)


class Page(HTMLParser):
    """Collects, in order, the paragraphs inside <div id="searchResults">, each with its text, whether it was all bold, and the id of the <span id="N"> section block it sits in."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_results = 0
        self.block = None
        self.paras: list[dict] = []
        self._p = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and a.get("id") == "searchResults":
            self.in_results = 1
        elif self.in_results and tag == "span" and a.get("id"):
            self.block = a["id"]
        elif self.in_results and tag == "p":
            self._p = {"text": [], "bold": [], "block": self.block}
            self._bold = 0
        elif self._p is not None and tag == "strong":
            self._bold += 1
        elif self._p is not None and tag == "br":
            self._p["text"].append(" ")
            self._p["bold"].append(False)

    def handle_endtag(self, tag):
        if self._p is not None and tag == "strong":
            self._bold -= 1
        elif tag == "p" and self._p is not None:
            text = "".join(self._p["text"])
            bold = [b for t, b in zip(self._p["text"], self._p["bold"]) if t.strip()]
            self.paras.append({"text": re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip(), "all_bold": bool(bold) and all(bold), "block": self._p["block"]})
            self._p = None
        elif tag == "span" and self.in_results and self._p is None:
            self.block = None

    def handle_data(self, data):
        if self._p is not None:
            self._p["text"].append(data)
            self._p["bold"].append(self._bold > 0)


def parse_act(html: str) -> tuple[list[dict], dict]:
    p = Page()
    p.feed(html)
    sections: dict[str, dict] = {}
    order: list[str] = []
    chapter_lines: list[str] = []
    stats = {"paragraphs": len(p.paras), "labels_removed": 0, "no_number": []}
    for para in p.paras:
        if not para["text"]:
            continue
        if para["block"] is None:
            if para["all_bold"]:
                chapter_lines.append(para["text"])
            continue
        s = sections.get(para["block"])
        if s is None:
            s = sections[para["block"]] = {"id": para["block"], "chapter": " ".join(chapter_lines[-3:]) if chapter_lines else "", "heading": "", "paras": []}
            order.append(para["block"])
            chapter_lines = []
        s["paras"].append(para)
    out = []
    for key in order:
        s = sections[key]
        paras = s["paras"]
        heading_parts, body = [], []
        number_para = None
        for para in paras:
            if number_para is None and re.match(r"^\d+[A-Za-z]{0,3}\.", para["text"]):
                number_para = para
            if number_para is None:
                heading_parts.append(para["text"])  # the heading line(s) printed above the number (some are not bold)
            else:
                body.append(para["text"])
        if number_para is None:
            stats["no_number"].append(key)
            continue
        m = re.match(r"^(\d+[A-Za-z]{0,3})\.+\s*(.*)$", body[0], re.S)  # (one section is printed with two dots)
        number, first_rest = m.group(1), m.group(2)
        labels = LABEL.findall(" ".join(heading_parts))
        heading = " ".join(heading_parts)
        heading = LABEL.sub(" ", heading)
        stats["labels_removed"] += len(labels)
        heading = re.sub(r"\s+", " ", heading).strip().rstrip(".").strip()
        rest = "\n".join([first_rest] + body[1:]).strip()
        out.append({"number": number, "heading": heading, "labels": [x.strip() for x in labels], "chapter": s["chapter"], "rest": rest})
    return out, stats


def build(act_key: str, folder: Path) -> dict:
    slug, title, act_no, expected = ACTS[act_key]
    page_url = f"https://www.ncrb.mha.gov.in/uploads/SankalanPortal/Chapters{act_key}.html"
    sections, stats = parse_act((folder / f"Chapters{act_key}.html").read_text(encoding="utf-8", errors="replace"))
    entries = []
    for s in sections:
        text = f"{s['number']}. {s['heading']}.—{s['rest']}" if s["heading"] else f"{s['number']}. {s['rest']}"
        e = {
            "id": f"ncrb-{slug}-{s['number'].lower()}", "citation": f"Section {s['number']}, {title}", "kind": "STATUTE_SECTION", "jurisdiction": "IN", "heading": s["heading"], "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "source_name": SOURCE_NAME, "source_url": page_url,
            "version": f"{act_no} as printed on the NCRB Sankalan portal page (no consolidation date or amendment history is stated there)",
            "commencement": "Not stated on this page: use the Gazette notification", "legal_currency": "Not stated on this page",
            "status": "UNVERIFIED - pending lawyer review", "chapter": s["chapter"],
            "extraction_note": "Taken from the portal's HTML page. The portal's comparison labels were cut from the heading" + (f" (it printed: {', '.join(s['labels'])})" if s["labels"] else "") + "; the section words are as printed.",
        }
        entries.append(e)
    return {"entries": entries, "expected": expected, "stats": stats}


def main() -> None:
    folder = Path(sys.argv[1])
    check = "--check" in sys.argv
    for key in ACTS:
        built = build(key, folder)
        n = len(built["entries"])
        nums = [e["citation"] for e in built["entries"]]
        dup = len(nums) - len(set(nums))
        print(f"{key}: sections {n} (the Act has {built['expected']}), duplicates {dup}, without a number {len(built['stats']['no_number'])}, labels cut {built['stats']['labels_removed']}")
        if not check:
            (PENDING / f"ncrb-{ACTS[key][0]}.json").write_text(json.dumps({"entries": built["entries"]}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
