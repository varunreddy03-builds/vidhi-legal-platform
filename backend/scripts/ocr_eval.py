"""Measure how well VIDHI's scan reader reads YOUR sample scans, file by file, and say what fails and what the person using VIDHI would see.

  python scripts/ocr_eval.py <folder> --check      list the pairs found, what each is tagged as, and whether the reader is installed. Reads nothing.
  python scripts/ocr_eval.py <folder>              read every scan with Tesseract and write a dated report under docs/evals/ (an old report is never overwritten)
  python scripts/ocr_eval.py <folder> --hosted     PLAN ONLY for the paid AI reader: how many calls and the rough cost. Nothing is sent.

The folder holds pairs: a scan (<name>.png, .jpg or .pdf) and its correct text typed by a person (<name>.txt, UTF-8). Tag the file name so the report can group the results:
a language tag (eng, hin, tel, tam) and a condition tag (clean, skewed, lowq for low quality, photo), for example  petition1.clean.hin.png + petition1.clean.hin.txt  or  order3.skewed.tel.pdf.

For each file the report gives the accuracy (1 minus the character error rate; both texts are first put in Unicode form NFC and zero-width marks are removed, so a different way of typing the same
Telugu or Hindi letters is not counted as a mistake), Tesseract's own mean confidence, the pages the reader marked uncertain, what failed, and what the person would see in VIDHI.
Above all it counts the DANGEROUS case separately: text that is wrong but was NOT marked uncertain, because then nothing warns the person.

What this measures is Tesseract, the free reader VIDHI uses for scanned PDFs when it is installed. A photo uploaded as an image (png or jpg) is read by a hosted AI model instead, which reports no
confidence and is therefore always marked uncertain; that path costs money and is not run here (see --hosted)."""

import argparse
import json
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from lib import ocr_engine  # noqa: E402

LANGS = {"eng": "English", "hin": "Hindi", "tel": "Telugu", "tam": "Tamil"}
CONDITIONS = {"clean": "clean", "skewed": "skewed", "lowq": "low quality", "lowquality": "low quality", "photo": "photo"}
WRONG_BELOW = 0.85  # an accuracy under this is "wrong" text: more than one character in seven is mistaken
INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"))  # zero-width marks


def tags_of(path: Path) -> tuple[str, str]:
    """(language tag, condition) read from the file name; 'unknown' when absent."""
    parts = path.stem.lower().split(".")
    lang = next((p for p in parts[1:] if p in LANGS), "unknown")
    cond = next((CONDITIONS[p] for p in parts[1:] if p in CONDITIONS), "unknown")
    return lang, cond


def normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").translate(INVISIBLE)


def accuracy(truth: str, read: str) -> float:
    """1 minus the character error rate (floored at 0), after Unicode normalisation."""
    return round(max(0.0, 1.0 - ocr_engine.char_error_rate(normalise(truth), normalise(read))), 4)


def pairs(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".pdf") and p.with_suffix(".txt").exists())


def images_for(path: Path) -> list[bytes]:
    return ocr_engine.render_pages(path.read_bytes()) if path.suffix.lower() == ".pdf" else [path.read_bytes()]


def tesseract_reader(cmd: str, languages: str):
    """A reader: file -> [(page text, mean confidence or None), ...]. Raises on any failure; the caller records it."""

    def read(path: Path) -> list[tuple[str, float | None]]:
        out = []
        for png in images_for(path):
            text, conf, _ = ocr_engine.parse_tsv(ocr_engine.run_tesseract(cmd, png, languages))
            out.append((text, conf))
        return out

    return read


def judge(path: Path, truth: str, pages: list[tuple[str, float | None]] | None, error: str | None, languages: str = "") -> dict:
    """One file's result, with the failures named and what the person would see. `pages` is None when the reader failed (then `error` says how)."""
    lang, cond = tags_of(path)
    row: dict = {"file": path.name, "language": lang, "condition": cond, "accuracy": None, "mean_confidence": None, "uncertain_pages": [], "fails": [], "user_sees": "", "dangerous": False, "error": error}
    if pages is None:
        row["fails"].append(f"the reader failed ({error})")
        row["user_sees"] = "The upload ends as FAILED with a reason, or the page text is empty. Nothing from this file can support an answer."
        return row
    meta = [ocr_engine._meta(i + 1, "tesseract", languages, conf, [], text) for i, (text, conf) in enumerate(pages)]
    row["uncertain_pages"] = ocr_engine.uncertain_pages(meta)
    confs = [c for _, c in pages if c is not None]
    row["mean_confidence"] = round(sum(confs) / len(confs), 1) if confs else None
    read = "\n".join(t for t, _ in pages)
    row["accuracy"] = accuracy(truth, read)
    if not read.strip():
        row["fails"].append("no text was found")
        row["user_sees"] = "The document card says no readable text was found; the matter cannot answer from this file, and an absence claim about it is only partly verified."
        return row
    if row["uncertain_pages"]:
        row["fails"].append(f"low confidence or empty on page(s) {', '.join(map(str, row['uncertain_pages']))}")
        row["user_sees"] = ("The document card shows 'Read from a scan: check against the original' naming those pages and the reader's confidence. A statement resting on them is shown as at most partly verified, "
                            "never verified.")
    if row["accuracy"] < WRONG_BELOW and not row["uncertain_pages"]:
        row["dangerous"] = True
        row["fails"].append(f"the text is wrong (accuracy {row['accuracy']:.0%}) but the reader marked no page uncertain")
        row["user_sees"] = "NOTHING warns the person: the text looks as good as a clean file. This is the dangerous case."
    elif row["accuracy"] < WRONG_BELOW:
        row["fails"].append(f"many characters are wrong (accuracy {row['accuracy']:.0%})")
    if not row["fails"]:
        row["user_sees"] = "Nothing to flag: the text is accurate and the reader was confident."
    return row


def evaluate(files: list[Path], reader, languages: str = "") -> list[dict]:
    out = []
    for p in files:
        truth = p.with_suffix(".txt").read_text(encoding="utf-8")
        try:
            out.append(judge(p, truth, reader(p), None, languages))
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest; the class of the error is recorded, never its message
            out.append(judge(p, truth, None, type(exc).__name__, languages))
    return out


def summarise(rows: list[dict]) -> dict:
    def block(sel):
        done = [r for r in sel if r["accuracy"] is not None]
        return {"files": len(sel), "read": len(done), "mean_accuracy": round(sum(r["accuracy"] for r in done) / len(done), 4) if done else None,
                "worst": min((r["accuracy"] for r in done), default=None), "flagged_uncertain": sum(1 for r in sel if r["uncertain_pages"]), "dangerous": sum(1 for r in sel if r["dangerous"]),
                "failed_to_read": sum(1 for r in sel if r["error"])}

    return {"all": block(rows), "by_language": {k: block([r for r in rows if r["language"] == k]) for k in sorted({r["language"] for r in rows})},
            "by_condition": {k: block([r for r in rows if r["condition"] == k]) for k in sorted({r["condition"] for r in rows})}}


def _pct(x) -> str:
    return "-" if x is None else f"{x:.0%}"


def render(rows: list[dict], meta: dict) -> str:
    s = summarise(rows)
    a = s["all"]
    out = [f"# OCR evaluation: {meta['date']}", "",
           f"- Folder: `{meta['folder']}`, {a['files']} files; languages asked of the reader: `{meta['languages']}`; reader: Tesseract {meta.get('tesseract', 'not installed')}",
           "- Accuracy is 1 minus the character error rate after Unicode NFC and removal of zero-width marks. It is computed against the text a person typed for each page.",
           "- This measures Tesseract only. Photos uploaded as images go to a hosted AI reader (no confidence figure, always marked uncertain); that was not run.", "",
           "## The dangerous case first", ""]
    out.append(f"**{a['dangerous']} file(s)** were read wrongly (accuracy under {WRONG_BELOW:.0%}) with no page marked uncertain, so nothing would warn the person"
               + (": " + ", ".join(r["file"] for r in rows if r["dangerous"]) + "." if a["dangerous"] else "."))
    out += ["", "## Summary", "", "| Group | Files | Mean accuracy | Worst | Marked uncertain | Dangerous | Failed to read |", "|---|---|---|---|---|---|---|"]
    for name, b in [("all", a)] + [(f"language {k}", v) for k, v in s["by_language"].items()] + [(f"condition {k}", v) for k, v in s["by_condition"].items()]:
        out.append(f"| {name} | {b['files']} | {_pct(b['mean_accuracy'])} | {_pct(b['worst'])} | {b['flagged_uncertain']} | {b['dangerous']} | {b['failed_to_read']} |")
    out += ["", "## File by file", "", "| File | Language | Condition | Accuracy | Reader confidence | Uncertain pages | What fails | What the person sees |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['file']} | {r['language']} | {r['condition']} | {_pct(r['accuracy'])} | {r['mean_confidence'] if r['mean_confidence'] is not None else '-'} | "
                   f"{', '.join(map(str, r['uncertain_pages'])) or '-'} | {'; '.join(r['fails']) or '-'} | {r['user_sees']} |")
    out += ["", "## Limits", "", "- A handful of files says little: use a few dozen pages of each kind before choosing a setting.",
            "- Tesseract's confidence is its own estimate; a page can be wrong and confident. That is the dangerous case counted above.",
            "- The correct text is only as good as the person who typed it."]
    return "\n".join(out) + "\n"


def save(text: str, data: dict, directory: Path, now: datetime | None = None) -> Path:
    """<directory>/ocr-eval-<date>-<time>.md and .json; an existing name gets -2, -3 ...: an old report is never replaced."""
    now = now or datetime.now(timezone.utc)
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"ocr-eval-{now:%Y-%m-%d-%H%M}"
    n = 1
    while True:
        name = stem if n == 1 else f"{stem}-{n}"
        try:
            with open(directory / f"{name}.md", "x", encoding="utf-8") as f:
                f.write(text)
            with open(directory / f"{name}.json", "x", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            return directory / f"{name}.md"
        except FileExistsError:
            n += 1


INSTALL_HELP = (
    "Tesseract was not found on this computer. To measure the free reader:\n"
    "  1. Install Tesseract (Windows: the UB Mannheim installer, linked from https://tesseract-ocr.github.io/tessdoc/Installation.html; during setup tick the language data for Hindi, Telugu and Tamil).\n"
    "  2. Make sure `tesseract --list-langs` lists eng, hin, tel (and tam), or set TESSERACT_CMD to the program's full path.\n"
    "  3. Run this tool again.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--hosted", action="store_true")
    ap.add_argument("--languages", default="eng+hin+tel+tam")
    ap.add_argument("--out-dir", default=str(REPO / "docs" / "evals"))
    a = ap.parse_args()
    folder = Path(a.folder)
    if not folder.is_dir():
        print(f"{folder} is not a folder.")
        return 2
    files = pairs(folder)
    if not files:
        print("No scans with a matching .txt file were found. Each scan needs its correct text in a file with the same name and a .txt ending.")
        return 2
    cmd = ocr_engine.tesseract_cmd()
    have = ocr_engine.installed_languages(cmd) if cmd else set()
    print(f"{len(files)} scans with correct text found in {folder}.")
    for p in files:
        lang, cond = tags_of(p)
        print(f"  {p.name}: language {lang}, condition {cond}" + ("   (no language tag: add one such as .hin or .tel)" if lang == "unknown" else ""))
    print("Tesseract:", cmd or "NOT installed", "| languages installed:", ", ".join(sorted(have)) or "none", "| page renderer (for PDFs):", "yes" if ocr_engine.renderer_available() else "NO (pip install pypdfium2)")
    if a.hosted:
        n_images = sum(1 for p in files if p.suffix.lower() != ".pdf")
        pages = sum(len(images_for(p)) for p in files) if ocr_engine.renderer_available() else len(files)
        print(f"HOSTED READER PLAN: about {pages} pages would be sent to a hosted AI model, one call each ({n_images} are images, which VIDHI always reads this way). Nothing is sent by this tool; "
              "the cost is the per-call price of the model the server uses (see docs/VIDHI_COST_MODEL.md) and counts against the AI cap. Tell Claude \"run\" if you want it measured.")
        return 0
    if a.check:
        return 0
    if not cmd:
        print(INSTALL_HELP)
        return 2
    missing = [l for l in a.languages.split("+") if l not in have]
    if missing:
        print(f"WARNING: Tesseract has no data for: {', '.join(missing)}. Pages in those languages will read badly or not at all. The data goes in Tesseract's tessdata folder.")
    languages = "+".join(l for l in a.languages.split("+") if l in have) or "eng"
    rows = evaluate(files, tesseract_reader(cmd, languages), languages)
    meta = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "folder": folder.name, "languages": languages, "tesseract": cmd}
    text = render(rows, meta)
    path = save(text, {"meta": meta, "summary": summarise(rows), "files": rows}, Path(a.out_dir))
    s = summarise(rows)["all"]
    print(f"Report saved: {path}")
    print(f"  {s['read']} of {s['files']} read; mean accuracy {_pct(s['mean_accuracy'])}, worst {_pct(s['worst'])}; marked uncertain {s['flagged_uncertain']}; DANGEROUS (wrong, not marked) {s['dangerous']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
