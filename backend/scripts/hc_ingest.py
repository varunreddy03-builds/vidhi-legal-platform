"""Turn the files fetched by scripts/hc_fetch.py into judgment records: data/hc_judgments/<court>.jsonl, one line per judgment.

    python scripts/hc_ingest.py [--ocr]

Text is the PDF's own text layer. With --ocr a PDF that has almost no text layer is read by OCR (needs the separate OCR environment, scripts/ocr_pdf.py) and marked "OCR".
A PDF that cannot be opened is kept as a record marked UNREADABLE with no text. Nothing is edited or summarised."""

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from pypdf import PdfReader  # noqa: E402

from lib import hc_judgments as H  # noqa: E402

RAW = HERE.parent / "data" / "hc_raw"
OUT = HERE.parent / "data" / "hc_judgments"
OCR_PY = Path(r"C:\vidhi-tools\venv-ocr\Scripts\python.exe")
MIN_TEXT = 200
logging.getLogger("pypdf").setLevel(logging.CRITICAL)


def pdf_text(path: Path) -> str | None:
    """The text layer, or None if the file cannot be opened."""
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages).strip()
    except Exception:  # noqa: BLE001 - a broken file is recorded as unreadable
        return None


def ocr(path: Path) -> str:
    if not OCR_PY.exists():
        return ""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "o.txt"
        r = subprocess.run([str(OCR_PY), "-I", "-X", "utf8", str(HERE / "ocr_pdf.py"), str(path), str(out)], capture_output=True, text=True)
        return out.read_text(encoding="utf-8").strip() if r.returncode == 0 and out.exists() else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr", action="store_true")
    a = ap.parse_args()
    by_court: dict[str, list[dict]] = {}
    for meta_path in sorted(RAW.glob("*/*/*/*.json")):
        year, court, bench = meta_path.parts[-4:-1]
        name = meta_path.stem
        pdf = meta_path.with_suffix(".pdf")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        text = pdf_text(pdf) if pdf.exists() else None
        kind = "TEXT"
        if text is None:
            text, kind = "", "UNREADABLE"
        elif len(text) < MIN_TEXT and a.ocr:
            o = ocr(pdf)
            if o:
                text, kind = o, "OCR"
        by_court.setdefault(court, []).append(H.build_record(meta, name, year, court, bench, text, kind))
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for court, recs in by_court.items():
        (OUT / f"{court}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
        n += len(recs)
    kinds = {}
    for recs in by_court.values():
        for r in recs:
            kinds[r["text_kind"]] = kinds.get(r["text_kind"], 0) + 1
    print(f"wrote {n} judgment(s) for {len(by_court)} court(s): {kinds}")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
