"""Measures how well each available OCR engine reads YOUR scans. Not run yet: it needs real scanned pages with their correct text, which only you can supply.

  python scripts/ocr_benchmark.py <folder> [--hosted] [--languages eng+tel+hin]

The folder holds pairs: <name>.png|.jpg|.pdf (a scan) and <name>.txt (the correct text of that scan, typed by a person from the page). Put the language in the
name (for example petition1.tel.png, notice2.hin.pdf, order3.eng.png) so results are grouped by language.

For each scan it reports character error rate (0 = perfect; edit distance divided by the length of the correct text) for each engine that is installed:
  tesseract       needs the Tesseract program (TESSERACT_CMD or on the PATH) and its language data (eng, tel, hin)
  hosted-vision   only with --hosted, because it sends the scan to a hosted AI model and costs money (it counts against the monthly AI cap)
and Tesseract's own mean confidence. Nothing is written to the database. Use a few dozen representative pages before choosing a configuration:
a result on a handful of clean pages says nothing about blurry petitions."""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import ocr_engine  # noqa: E402


def lang_of(path: Path) -> str:
    parts = path.stem.split(".")
    return parts[-1] if len(parts) > 1 and parts[-1] in ("eng", "tel", "hin") else "unknown"


def images_for(path: Path) -> list[bytes]:
    if path.suffix.lower() == ".pdf":
        return ocr_engine.render_pages(path.read_bytes())
    return [path.read_bytes()]


async def hosted_text(path: Path) -> str:
    pages, _ = await ocr_engine.read_pdf("benchmark", path.read_bytes()) if path.suffix.lower() == ".pdf" else ([""], [])
    return "\n".join(pages)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--hosted", action="store_true", help="also try the hosted AI reader (costs money; PDFs only)")
    ap.add_argument("--languages", default="eng+tel+hin")
    a = ap.parse_args()
    cmd = ocr_engine.tesseract_cmd()
    if not cmd:
        print("Tesseract was not found (set TESSERACT_CMD or add it to the PATH). Nothing to measure for it.")
    scans = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".pdf") and p.with_suffix(".txt").exists())
    if not scans:
        print("No scans with matching .txt files found.")
        return 2
    rows: dict[tuple[str, str], list[float]] = defaultdict(list)
    confs: dict[str, list[float]] = defaultdict(list)
    detail = []
    for p in scans:
        truth = p.with_suffix(".txt").read_text(encoding="utf-8")
        lang = lang_of(p)
        if cmd:
            texts, cs = [], []
            for png in images_for(p):
                text, conf, _ = ocr_engine.parse_tsv(ocr_engine.run_tesseract(cmd, png, a.languages))
                texts.append(text)
                if conf is not None:
                    cs.append(conf)
            cer = ocr_engine.char_error_rate(truth, "\n".join(texts))
            rows[("tesseract", lang)].append(cer)
            if cs:
                confs[lang].append(sum(cs) / len(cs))
            detail.append({"file": p.name, "language": lang, "engine": "tesseract", "cer": cer, "mean_confidence": round(sum(cs) / len(cs), 1) if cs else None})
        if a.hosted and p.suffix.lower() == ".pdf":
            cer = ocr_engine.char_error_rate(truth, asyncio.run(hosted_text(p)))
            rows[("hosted-vision", lang)].append(cer)
            detail.append({"file": p.name, "language": lang, "engine": "hosted-vision", "cer": cer, "mean_confidence": None})
    print(f"{'engine':15} {'language':9} {'pages':>5} {'mean CER':>9} {'worst CER':>10}")
    for (engine, lang), v in sorted(rows.items()):
        print(f"{engine:15} {lang:9} {len(v):5} {sum(v) / len(v):9.3f} {max(v):10.3f}")
    out = Path(a.folder) / "ocr_benchmark_result.json"
    out.write_text(json.dumps({"languages": a.languages, "results": detail}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"details written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())