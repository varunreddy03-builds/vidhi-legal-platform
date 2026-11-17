"""Split the official law PDFs (data/legal_sources_raw, checked against their manifests) into DRAFT library entries in data/legal_library/pending/.

  python scripts/law_extract.py check                 # verify every PDF against its SHA-256 in the manifests
  python scripts/law_extract.py run [--only <text>]   # write pending/<act>.json (one file per Act, one entry per section)
  python scripts/law_extract.py report [--only <text>]  # sections found per Act and any gaps in the numbering

The text is cut out of the PDF mechanically and never edited. PDF text extraction is not perfect (a stray space inside a word, a broken line), so every
entry says so and stays "UNVERIFIED - pending lawyer review": only `scripts/library_review.py approve` (a named lawyer comparing it with the official
source) can move it into the verified library. This script writes nothing into the verified library and knows no law of its own.

Which files are cut: English central Acts (folders 01 to 05 and 08 to 10) and the Telangana Acts and Rules (folder 11). Hindi texts, amending Acts and
Gazette notifications (folder 06) are kept as source files only. A file that yields fewer than 3 sections (a scan, a table-only rule) is listed as NOT EXTRACTED.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pypdf  # noqa: E402

from lib.library import DEFAULT_DIR, sha256_text  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "data" / "legal_sources_raw" / "VIDHI_Indian_Legal_Sources"
if sys.platform == "win32":  # a few Telangana file names push the full path past Windows' 260-character limit
    RAW = Path("\\\\?\\" + str(RAW.resolve()))
META = RAW / "07_Source_Manifest_and_Metadata"
PENDING = DEFAULT_DIR / "pending"

CENTRAL_FOLDERS = ("01_", "02_", "03_", "04_", "05_", "08_", "09_", "10_")
# Short ids kept stable for the first batch; every other file gets an id from its own name.
KNOWN_IDS = {
    "BNS_2023_Official.pdf": "bns", "BNSS_2023_Official.pdf": "bnss", "BSA_2023_Official.pdf": "bsa", "IPC_1860_Official_Repealed.pdf": "ipc",
    "CrPC_1973_Official_Repealed.pdf": "crpc", "Indian_Evidence_Act_1872_Official_Repealed.pdf": "iea", "MSMED_Act_2006_Official.pdf": "msmed",
    "Commercial_Courts_Act_2015_Official.pdf": "cca", "Arbitration_Conciliation_Act_1996_Official.pdf": "arb", "IT_Act_2000_Official.pdf": "it",
    "DPDP_Act_2023_Official.pdf": "dpdp", "Constitution_of_India_English_2026_Official.pdf": "coi",
}
HEAD = re.compile(r"(?m)^[ \t]*(?:\d{1,3}\[)?(\d{1,3}[A-Z]{0,3})\.[ \t]*((?:[^\n]*\n(?![ \t]*\d{1,3}[A-Z]{0,3}\.)){0,2}?[^\n]*?)[ \t]*\.?[ \t]*[—–]")
NOTE_WORDS = re.compile(r"^(?:Subs|Ins|Rep|Omitted|Added|The words|The original|Cl\.|Sub-|Clause|See|Vide|Renumbered|Re-numbered|Explanation|Proviso|Substituted|Inserted|Repealed|Sec\.|S\.)\b", re.I)
MAX_JUMP = 12  # a section the heading pattern misses must not stop the run; a jump this small cannot be a footnote number
TAIL_HEAD = re.compile(r"\n[ \t]*(?:CHAPTER|PART)[ \t]+[IVXLC0-9A-Z]+[^\n]*(?:\n[^\n]{0,120})?\s*$")
NOISE = re.compile(r"(?m)^[ \t]*(?:IndiaCode|\d{1,4})[ \t]*$")
MIN_SECTIONS = 3


def slug(s: str, n: int = 56) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def sources() -> list[dict]:
    """Every file named in the manifests: {file (relative to RAW), sha, title, number, url, version, commencement, currency, cut, id, unit}."""
    out = []
    with open(META / "VIDHI_Source_Manifest.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = r["File name"]
            cut = r["Folder"].startswith(CENTRAL_FOLDERS) and "Hindi" not in name and name.lower().endswith(".pdf")
            out.append({"file": f"{r['Folder']}/{name}", "sha": r["SHA-256 checksum"], "title": r["Document name"], "number": r["Act number and year"],
                        "url": r["Official source webpage URL"], "version": r["Version or publication date"], "commencement": r["Commencement status"],
                        "currency": r["Legal currency"], "cut": cut, "id": KNOWN_IDS.get(name) or slug(name.rsplit(".", 1)[0].replace("_Official", "")),
                        "unit": "Article" if name.startswith("Constitution") else "Section"})
    tg = META / "VIDHI_Telangana_Manifest.csv"
    if tg.exists():
        with open(tg, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                name = r.get("File name") or ""
                if not name:
                    continue
                kind = (r.get("Type") or "").upper()
                out.append({"file": name, "sha": r["SHA-256 checksum"], "title": r["Title"].strip(), "number": f"{kind.title()} {r['Act/Rule no.']} of {r['Year']}",
                            "url": r["Official source webpage URL"], "version": f"Telangana {kind.lower()}, issue date {r['Enactment / issue date']}",
                            "commencement": r.get("Enforcement date") or "not stated in the manifest",
                            "currency": "Repealed (flagged by India Code)" if (r.get("Repealed flag (India Code)") or "").lower() == "true" else "Telangana law as on India Code; currency not checked",
                            "cut": kind in ("ACT", "RULE") and name.lower().endswith(".pdf"), "id": "tg-" + slug(name.rsplit("/", 1)[-1].rsplit(".", 1)[0], 44),
                            "unit": "Rule" if kind == "RULE" else "Section"})
    seen: dict[str, int] = {}
    for s in out:  # two files may slug to the same id: number them so no entry is silently dropped
        seen[s["id"]] = seen.get(s["id"], 0) + 1
        if seen[s["id"]] > 1:
            s["id"] += f"-{seen[s['id']]}"
    return out


def check() -> int:
    bad = total = 0
    for s in sources():
        total += 1
        p = RAW / s["file"]
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != s["sha"]:
            print("BAD", s["file"])
            bad += 1
    print("checked", total, "files;", bad, "bad")
    return 1 if bad else 0


def pdf_text(path: Path) -> str:
    out = []
    for page in pypdf.PdfReader(str(path)).pages:
        t = page.extract_text() or ""
        out.append(NOISE.sub("", t))
    return "\n".join(out)


def key(label: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", label)
    return int(m.group(1)), m.group(2)


def split(text: str) -> list[tuple[str, str, str]]:
    """[(label, heading, body)] in order. A heading counts only if its number follows the previous one (so footnotes and list items are ignored)."""
    cands = [(m.start(), m.group(1), " ".join(m.group(2).split())) for m in HEAD.finditer(text)]
    picked: list[tuple[int, str, str]] = []
    for pos, label, head in cands:
        if len(head) > 220 or not (head[:1].isalpha() or head[:1] in "“‘\"'[") or NOTE_WORDS.match(head):
            continue
        if not picked:
            if key(label)[0] > 3:  # a code starts at 1 (or 1A): later numbers before that are the contents list or notes
                continue
            picked.append((pos, label, head))
            continue
        pn, ps = key(picked[-1][1])
        n, s = key(label)
        if (n == pn and s > ps) or pn < n <= pn + MAX_JUMP:
            picked.append((pos, label, head))
    secs = []
    for i, (pos, label, head) in enumerate(picked):
        end = picked[i + 1][0] if i + 1 < len(picked) else len(text)
        body = text[pos:end].strip()
        body = TAIL_HEAD.sub("", body).strip()  # the next Chapter/Part heading belongs to the next section, not this one
        secs.append((label, head, body))
    return secs


TOC_LINE = re.compile(r"(?m)^[ \t]*(\d{1,3}[A-Z]{0,3})\.[ \t]+([A-Z“‘\[][^\n]{2,200}?)[ \t]*\.?[ \t]*$")


TOC_LINE_OCR = re.compile(r"(?m)^[ \t]*(\d{1,3}[A-Z]{0,3})\.[ \t]*([A-Z“‘\[][^\n]{2,200}?)[ \t]*\.?[ \t]*$")  # OCR often drops the space after the full stop ("2.Definitions.")


def contents(text: str, ocr: bool = False) -> tuple[list[tuple[str, str]], int]:
    """The Act's own list of sections ([(label, title)], position where the list ends): the first run of heading-only lines whose numbers follow each other."""
    run: list[tuple[str, str, int]] = []
    for m in (TOC_LINE_OCR if ocr else TOC_LINE).finditer(text):
        label, title = m.group(1), " ".join(m.group(2).split())
        if NOTE_WORDS.match(title):
            continue
        if not run:
            if key(label)[0] <= 2:
                run.append((label, title, m.end()))
            continue
        pn, ps = key(run[-1][0])
        n, s = key(label)
        if (n == pn and s > ps) or pn < n <= pn + 3:
            run.append((label, title, m.end()))
        elif len(run) >= 5 and n < pn:
            break  # a second list (a Schedule) begins
    return ([(a, b) for a, b, _ in run], run[-1][2]) if len(run) >= 5 else ([], 0)


def split_by_contents(text: str, ocr: bool = False) -> list[tuple[str, str, str]]:
    """For Acts whose body headings carry no dash ("1. (1) This Act may be called ..."): take the headings from the contents list and find where each section starts, in order."""
    toc, end = contents(text, ocr)
    starts: list[tuple[int, str, str]] = []
    pos = end
    for label, title in toc:
        m = None
        if ocr:
            # A printed margin heading is read into the line before the number ("Definitions. 2. In this Code"), so the number is not at the start of a line. It must be followed by "(" or a capital
            # and must not follow "section", "and", "to" ... (a cross-reference such as "section 4. The ...").
            pattern = r"(?<![\w.\d])" + re.escape(label) + r"\.[ \t]*(?=[(“‘A-Z])"
            for cand in re.finditer(pattern, text[pos:]):
                before = text[max(0, pos + cand.start() - 14) : pos + cand.start()]
                if re.search(r"(?i)(?:sections?|ss?\.|and|to|of|under|see)[ \t]*$", before) or NOTE_WORDS.match(text[pos + cand.end() : pos + cand.end() + 40]):
                    continue
                m = cand
                break
        else:
            for cand in re.finditer(r"(?m)^[ \t]*(?:\d{1,3}\[)?" + re.escape(label) + r"\.(?!\d)[ \t]*", text[pos:]):
                if not NOTE_WORDS.match(text[pos + cand.end() : pos + cand.end() + 40]):
                    m = cand
                    break
        if m is None:
            continue  # this section's start was not found: it is left out, not guessed
        starts.append((pos + m.start(), label, title))
        pos = pos + m.end()
    secs = []
    for i, (p, label, title) in enumerate(starts):
        e = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        secs.append((label, title, TAIL_HEAD.sub("", text[p:e].strip()).strip()))
    return secs


OCR_DIR = Path(__file__).resolve().parent.parent / "data" / "ocr"  # text read from a scanned PDF by scripts/ocr_pdf.py, named <act id>.txt


def build(s: dict) -> tuple[list[dict], list[str]]:
    ocr_file = OCR_DIR / f"{s['id']}.txt"
    by_ocr = ocr_file.is_file()
    text = NOISE.sub("", ocr_file.read_text(encoding="utf-8")) if by_ocr else pdf_text(RAW / s["file"])
    secs = split(text)
    toc, _ = contents(text, by_ocr)
    if toc and len(secs) < 0.95 * len(toc):  # the dash-heading rule found fewer sections than the Act itself lists: try the Act's own contents list, keep whichever finds more
        alt = split_by_contents(text, by_ocr)
        if len(alt) > len(secs):
            secs = alt
    entries = []
    for label, head, body in secs:
        entries.append({
            "id": f"{s['id']}-{label.lower()}",
            "citation": f"{s['unit']} {label}, {s['title']}",
            "kind": "STATUTE_SECTION" if s["unit"] != "Rule" else "RULE",
            "jurisdiction": "IN",
            "heading": head,
            "text": body,
            "text_sha256": sha256_text(body),
            "source_name": f"India Code (Legislative Department): {s['number']}, file {s['file'].rsplit('/', 1)[-1]}",
            "source_url": s["url"],
            "version": s["version"],
            "commencement": s["commencement"],
            "legal_currency": s["currency"],
            "pdf_sha256": s["sha"],
            "status": "UNVERIFIED - pending lawyer review",
            "oversized": len(body) > 30000,  # the last section of an Act can run on into its Schedules or notes: a lawyer must cut it at the real end
            "extraction_note": (
                "Read from a SCANNED official PDF by OCR (a program reading a picture) and cut mechanically. OCR makes mistakes: words run together, letters and numbers are misread. A lawyer must compare every word with the PDF before approving."
                if by_ocr
                else "Cut mechanically from the official PDF; text extraction can add a stray space or break a line. A lawyer must compare it with the PDF before approving."
            ),
            "text_source": "OCR" if by_ocr else "PDF_TEXT_LAYER",
            "coverage_note": (f"Only {len(secs)} of the {len(toc)} sections listed in the Act's own contents could be found in this draft; the others are missing, not repealed." if toc and len(secs) < len(toc) else ""),
        })
    nums = sorted({key(e["id"].rsplit("-", 1)[1].upper())[0] for e in entries})
    gaps = [str(n) for n in range(nums[0], nums[-1] + 1) if n not in nums] if nums else []
    return entries, gaps


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("check", "run", "report"))
    p.add_argument("--only")
    a = p.parse_args()
    if a.cmd == "check":
        return check()
    if check():
        return 1
    not_extracted, total = [], 0
    for s in sources():
        if not s["cut"] or (a.only and a.only.lower() not in s["file"].lower()):
            continue
        try:
            entries, gaps = build(s)
        except Exception as exc:  # a damaged PDF must not stop the other files
            entries, gaps = [], []
            print(f"ERROR {s['file']}: {type(exc).__name__}")
        if len(entries) < MIN_SECTIONS:
            not_extracted.append(s["file"])
            continue
        total += len(entries)
        print(f"{s['file'].rsplit('/', 1)[-1]}: {len(entries)} sections; numbers missing from the run: {', '.join(gaps[:12]) or 'none'}{' ...' if len(gaps) > 12 else ''}")
        if a.cmd == "run":
            PENDING.mkdir(parents=True, exist_ok=True)
            (PENDING / f"{s['id']}.json").write_text(json.dumps({"entries": entries}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"TOTAL {total} sections; NOT EXTRACTED ({len(not_extracted)}): " + "; ".join(x.rsplit('/', 1)[-1] for x in not_extracted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
