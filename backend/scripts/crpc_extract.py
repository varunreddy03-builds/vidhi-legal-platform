"""Cuts the Code of Criminal Procedure, 1973 into draft sections from the text layer of the owner-supplied PDF (the India Code repealed-Acts file, SHA-256 865cc3e1...), and writes data/legal_library/pending/crpc.json.

The text layer was made by a program reading a scan (Adobe Paper Capture): it has stray characters and some garbled numbers. So:
  * every section is UNVERIFIED and marked as machine-read (text_source "OCR"); no lawyer has compared it with the page;
  * a section is written only when its own number is found in the text, in order, after the previous one: a section whose number was too garbled to read is NOT written (it is listed as missing in
    the coverage note), never guessed;
  * the heading comes from the Act's own contents list (also machine-read) and may carry the same stray characters; it is empty when the contents list line was not readable;
  * this is the 1974 print of the Act: sections inserted by later amendments (41A and the like) are not in it.

A clean text-layer PDF of the Act as amended (CrPC_1973_as_amended_clean.pdf) is read with scripts/law_extract.py (the same rules as the other India Code files): every section is found by its own
number and checked against the Act's own contents list, and the last section is cut at the First Schedule. A scanned file falls back to the scan reader below.

    python scripts/crpc_extract.py <pdf> [--check]
"""

import hashlib
import io
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

PENDING = Path(__file__).resolve().parent.parent / "data" / "legal_library" / "pending" / "crpc.json"
TITLE = "The Code of Criminal Procedure, 1973"
EXPECTED_MAX = 484
HEADER = re.compile(r"(?m)^[ \t]*(?:\[?OF 1974\]?[ \t]*)?(?:\d{1,3}[ \t]+)?Code of Criminal Procedure(?:[ \t]*\[?ACT 2)?[ \t]*(?:\d{1,3})?[ \t]*$|^[ \t]*:?OF ?1974\][ \t]*Code of Criminal Procedure[ \t]*\d*[ \t]*$")
TAIL_HEAD = re.compile(r"\n[ \t]*(?:CHAPTER|PART)[ \t]+[IVXLC0-9A-Z]+[^\n]*(?:\n[^\n]{0,120})?\s*$")
SCHEDULE = re.compile(r"(?m)^[ \t]*THE FIRST SCHEDULE\b|^[ \t]*SCHEDULE[ \t]+I\b")


def pages_of(pdf: str) -> list[str]:
    err, sys.stderr = sys.stderr, io.StringIO()  # pypdf warns about fonts for every page
    try:
        return [(p.extract_text() or "") for p in PdfReader(pdf).pages]
    finally:
        sys.stderr = err


def key(n: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([A-Z]*)", n)
    return (int(m.group(1)), m.group(2)) if m else (10**9, n)


def contents_headings(pages: list[str], body_page: int) -> dict[int, str]:
    """number -> heading from the Arrangement of Sections pages (wrapped lines joined; a line ending with a hyphen continues on the next)."""
    text = "\n".join(pages[:body_page])
    out: dict[int, str] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^[ \t]*,?(\d{1,3})[ \t]*[\.,:;][ \t]*(.+?)[ \t]*$", lines[i])
        if m and re.match(r"[A-Z\"“‘]", m.group(2)):
            n, head = int(m.group(1)), m.group(2)
            while (head.endswith(("-", "­")) or not head.rstrip().endswith(".")) and i + 1 < len(lines) and len(head) < 220:
                nxt = lines[i + 1].strip()
                if not nxt or re.match(r"^,?\d{1,3}[ \t]*[\.,:;]|^(CHAPTER|SECTIONS|Arrangement)", nxt):
                    break
                head = (head[:-1] if head.endswith(("-", "­")) else head + " ") + nxt
                i += 1
            if 1 <= n <= EXPECTED_MAX and n not in out:
                out[n] = re.sub(r"\s+", " ", head).strip().rstrip(".").strip()
        i += 1
    return out


def find_starts(body: str) -> tuple[dict[int, int], list[int]]:
    """position of each main-number section start. Pass 1: a number at the start of a line, in order. Pass 2: a number that is part garbled is looked for, in order, inside the gap
    between the two neighbouring sections that were found."""
    cands = [(m.start(), m.group(1)) for m in re.finditer(r"(?m)^[ \t]*,?(\d{1,3})[ \t]*[\.,;:][ \t]*(?=\(|[A-Z\"“‘a-z])", body)]
    # the longest run of numbers that rise in step with their position: a stray number inside a section's text (a figure, a cross-reference) falls out of the run instead of derailing it
    import bisect

    seq = [(int(n), pos) for pos, n in cands if 1 <= int(n) <= EXPECTED_MAX]
    tails: list[int] = []  # smallest tail value of an increasing run of each length
    tail_idx: list[int] = []
    prev = [-1] * len(seq)
    for i, (v, _pos) in enumerate(seq):
        j = bisect.bisect_left(tails, v)
        if j == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[j] = v
            tail_idx[j] = i
        prev[i] = tail_idx[j - 1] if j else -1
    starts: dict[int, int] = {}
    i = tail_idx[-1] if tail_idx else -1
    while i != -1:
        starts[seq[i][0]] = seq[i][1]
        i = prev[i]
    missing = []
    for n in range(1, EXPECTED_MAX + 1):
        if n in starts:
            continue
        lo = max([p for k, p in starts.items() if k < n], default=0)
        hi = min([p for k, p in starts.items() if k > n], default=len(body))
        digits = r"\s?".join(str(n))
        m = re.search(rf"(?<![\d])(?<!section )(?<!sections )(?<!Rs\. ){digits}[ \t]*[\.;:,][ \t]*(?=\(1\)|[A-Z])", body[lo + 20 : hi])
        if m and (hi - lo) > 80:
            starts[n] = lo + 20 + m.start()
        else:
            missing.append(n)
    return starts, missing


def build(pdf: str) -> tuple[list[dict], list[int], dict]:
    pages = pages_of(pdf)
    body_page = next(i for i, p in enumerate(pages) if re.search(r"This Act may be called the Code of Criminal Procedure", p))
    heads = contents_headings(pages, body_page)
    body = "\n".join(pages[body_page:])
    starts, missing = find_starts(body)
    order = sorted(starts)
    sha = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()
    entries = []
    for idx, n in enumerate(order):
        s = starts[n]
        e = min([starts[k] for k in order[idx + 1 :] if starts[k] > s], default=len(body))
        raw = body[s:e]
        if n == max(order):
            sch = SCHEDULE.search(raw)
            raw = raw[: sch.start()] if sch else raw
        raw = HEADER.sub("", raw)
        raw = re.sub(r"[ 	]*IndiaCode[ 	]*", " ", raw)  # the portal's watermark, not law text
        raw = TAIL_HEAD.sub("", raw.rstrip()).strip()
        raw = re.sub(r"^[ \t]*,?\d{1,3}[ \t]*[\.,;:][ \t]*", "", raw, count=1)
        raw = re.sub(r"[ \t]+\n", "\n", raw).strip()
        if len(raw) < 20:
            missing.append(n)
            continue
        head = heads.get(n, "")
        text = f"{n}. {head}.—{raw}" if head else f"{n}. {raw}"
        entries.append({
            "id": f"crpc-{n}", "citation": f"Section {n}, The Code of Criminal Procedure 1973, 02 of 1974 (Rep., Act 46 of 2023)", "kind": "STATUTE_SECTION", "jurisdiction": "IN", "heading": head, "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "source_name": "India Code (Legislative Department): Act No. 2 of 1974, file CrPC_1973_Official_Repealed.pdf", "source_url": "https://indiacode.gov.in/items/973d60aa-105c-4a2f-94f1-7640f0b5d6a7",
            "version": "Historical text from India Code \"Repeal Acts\" collection (1974 print: sections inserted by later amendments are not in it)",
            "commencement": "REPEALED by BNSS (Act 46 of 2023) w.e.f. 01-07-2024", "legal_currency": "HISTORICAL - not current law; BNSS s.531 savings apply to pending matters", "pdf_sha256": sha,
            "status": "UNVERIFIED - pending lawyer review", "oversized": "False",
            "extraction_note": "Read from the text layer of a SCANNED official PDF (made by a program reading the pictures) and cut mechanically. It has stray characters, run-together or split words and some garbled numbers; "
                               "the heading comes from the Act's own contents list and may carry the same errors. No one has compared this text with the page. Never quote it without checking the official page.",
            "text_source": "OCR",
        })
    missing = sorted(set(missing))
    note = (f"{len(entries)} of the {EXPECTED_MAX} sections of the 1974 print were found in this draft; {len(missing)} could not be read (garbled number or text) and are missing, not repealed: "
            + ", ".join(str(m) for m in missing[:200]))
    for e in entries:
        e["coverage_note"] = note
    return entries, missing, {"contents_headings": len(heads)}


CLEAN_SOURCE = "Owner-supplied PDF CrPC_1973_as_amended_clean.pdf (an official-format text of the Act as amended; the publisher is not stated in the file)"


def build_clean(pdf: str) -> tuple[list[dict], list[str], dict] | None:
    """Sections of a clean text-layer PDF, or None when it is not one (fewer than 95% of the Act's own contents list found)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    err, sys.stderr = sys.stderr, io.StringIO()
    try:
        import law_extract

        text = law_extract.pdf_text(Path(pdf))
    finally:
        sys.stderr = err
    secs = law_extract.split(text)
    toc, _ = law_extract.contents(text)
    if not toc or len(secs) < 0.95 * len(toc):
        return None
    sha = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()
    entries, missing = [], [l for l, _ in toc if l not in {s[0] for s in secs}]
    for label, head, body in secs:
        if label == "484":
            sch = SCHEDULE.search(body)
            body = body[: sch.start()].rstrip() if sch else body
        body = re.sub(r"[ \t]+\n", "\n", body).strip()
        entries.append({
            "id": f"crpc-{label.lower()}", "citation": f"Section {label}, The Code of Criminal Procedure 1973, 02 of 1974 (Rep., Act 46 of 2023)", "kind": "STATUTE_SECTION", "jurisdiction": "IN", "heading": head, "text": body,
            "text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "source_name": CLEAN_SOURCE, "source_url": "", "version": "Act as amended (text-layer PDF dated 2019-11-21; the date up to which it is amended is not stated in the file)",
            "commencement": "REPEALED by BNSS (Act 46 of 2023) w.e.f. 01-07-2024", "legal_currency": "HISTORICAL - not current law; BNSS s.531 savings apply to pending matters", "pdf_sha256": sha,
            "status": "UNVERIFIED - pending lawyer review", "oversized": "False",
            "extraction_note": "Cut mechanically from the text layer of the supplied PDF; text extraction can add a stray space or break a line, and amendment markers such as 1[ ... ] are kept as printed. A lawyer must compare it with the PDF before approving.",
            "text_source": "PDF_TEXT_LAYER",
            "coverage_note": "" if not missing else f"{len(missing)} sections listed in the Act's own contents could not be found: {', '.join(missing[:100])}",
        })
    return entries, missing, {"contents_headings": len(toc), "clean": True}


def main() -> None:
    pdf = sys.argv[1]
    built = build_clean(pdf)
    entries, missing, stats = built if built else build(pdf)
    print("mode:", "clean text layer" if built else "scan reader")
    print(f"sections written: {len(entries)} (a clean file lists its own; a scan is checked against {EXPECTED_MAX}) | missing: {len(missing)} {missing[:40]} | contents headings read: {stats['contents_headings']}")
    if "--check" not in sys.argv:
        PENDING.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
