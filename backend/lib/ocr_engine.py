"""Reading a PDF page by page, and recording HOW each page was read.

Chain for every page, cheapest and most trustworthy first:
  1. embedded text (the PDF already has a text layer): engine "embedded-text", no confidence concept.
  2. Tesseract, if it is installed (TESSERACT_CMD or on the PATH) and pypdfium2 can render the page: engine "tesseract", with the REAL mean word confidence from Tesseract.
  3. the hosted vision model (lib/ocr.py), for pages still unread: engine "hosted-vision". It reports no confidence, so none is stored: `confidence` is None, never invented.

Every page gets a metadata row: page, engine, languages, confidence (a number only when the engine produced one), warnings, and `uncertain`.
A page is uncertain when its text is empty, when Tesseract's own confidence is below LOW_CONFIDENCE, or when the reader marked words [illegible]. Uncertain pages are
carried into the document record so the answer layer can refuse to call a claim based on them verified, and so a person is told before they rely on them.
Tesseract is optional: nothing here fails when it is absent, and nothing here has been benchmarked against real scans yet (scripts/ocr_benchmark.py does that)."""

import asyncio
import csv
import io
import os
import shutil
import subprocess
import tempfile

from lib import ocr

LOW_CONFIDENCE = 60.0
MIN_TEXT_LAYER = 20  # characters; fewer means the page is treated as a picture
DEFAULT_LANGUAGES = ("eng", "tel", "hin")  # Tamil is opt-in: OCR_LANGUAGES=eng+tel+hin+tam. On 12 synthetic images (2026-11-06) asking for four languages at once read Telugu slightly worse than three (58% vs 63%), and this is not yet measured on real scans


def configured_languages() -> tuple[str, ...]:
    """The languages asked of Tesseract: OCR_LANGUAGES (letters joined by + or commas, e.g. eng+tel+hin+tam) or the default. Anything that is not a plain language code is ignored."""
    raw = os.environ.get("OCR_LANGUAGES", "")
    names = tuple(x for x in (y.strip() for y in raw.replace(",", "+").split("+")) if x.isalpha() and x.islower() and 2 < len(x) < 9)
    return names or DEFAULT_LANGUAGES
def max_pages() -> int:
    """Longest scanned PDF read automatically (a cost limit: every unreadable page may cost a hosted AI call). Change with OCR_MAX_PAGES."""
    try:
        return max(1, int(os.environ.get("OCR_MAX_PAGES", "60")))
    except ValueError:
        return 60


HOSTED_WARNING = "Read by a hosted AI model, which reports no confidence. Compare with the original page before relying on it."


def tesseract_cmd() -> str | None:
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd:
        return None
    return cmd if (os.path.exists(cmd) or shutil.which(cmd)) else None


def renderer_available() -> bool:
    try:
        import pypdfium2  # noqa: F401

        return True
    except ImportError:
        return False


def tessdata_args() -> list[str]:
    """`--tessdata-dir <folder>` when OCR_TESSDATA_DIR names an existing folder, so the language files (Hindi, Telugu, Tamil, ...) can live outside the Tesseract install. The folder needs the
    language `.traineddata` files and a `configs` folder (copy it from the Tesseract install). Otherwise Tesseract's own default (or TESSDATA_PREFIX) applies."""
    folder = os.environ.get("OCR_TESSDATA_DIR", "").strip()
    return ["--tessdata-dir", folder] if folder and os.path.isdir(folder) else []


def installed_languages(cmd: str) -> set[str]:
    try:
        out = subprocess.run([cmd, *tessdata_args(), "--list-langs"], capture_output=True, text=True, timeout=20).stdout.splitlines()
        return {x.strip() for x in out if x.strip().isalpha() and not x.startswith("List of")}  # one language per line after the header line
    except Exception:  # noqa: BLE001
        return set()


def render_pages(data: bytes, dpi: int = 300) -> list[bytes]:
    """PNG bytes for every page (pypdfium2). Replaced in tests."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    out = []
    for i in range(len(pdf)):
        img = pdf[i].render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(buf.getvalue())
    return out


def run_tesseract(cmd: str, png: bytes, languages: str) -> str:
    """Tesseract's TSV output for one page image. Replaced in tests."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "page.png")
        with open(path, "wb") as f:
            f.write(png)
        out = subprocess.run([cmd, path, "stdout", *tessdata_args(), "-l", languages, "--psm", "3", "tsv"], capture_output=True, text=True, timeout=180, encoding="utf-8").stdout
        if out.strip() and not out.startswith("level"):  # the 'tsv' config was not found (a data folder without its configs folder): plain text came back, and reading it as TSV would silently find no words
            raise RuntimeError("Tesseract did not return word data: its 'tsv' config is missing from the data folder")
        return out


def parse_tsv(tsv: str) -> tuple[str, float | None, int]:
    """(text, mean word confidence or None, word count) from Tesseract TSV. Confidence is the mean over real words (conf >= 0), as Tesseract reports it."""
    rows = list(csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE))
    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    for r in rows:
        word = (r.get("text") or "").strip()
        try:
            conf = float(r.get("conf", "-1"))
        except ValueError:
            continue
        if not word or conf < 0:
            continue
        confs.append(conf)
        lines.setdefault((r.get("block_num"), r.get("par_num"), r.get("line_num")), []).append(word)
    text = "\n".join(" ".join(w) for w in lines.values())
    return text, (round(sum(confs) / len(confs), 1) if confs else None), len(confs)


def _meta(page: int, engine: str, languages: str, confidence: float | None, warnings: list[str], text: str) -> dict:
    uncertain = not text.strip() or "[illegible]" in text.lower() or (confidence is not None and confidence < LOW_CONFIDENCE) or engine == "hosted-vision"  # a hosted reader gives no confidence at all
    if not text.strip():
        warnings = warnings + ["No text was found on this page."]
    elif "[illegible]" in text.lower():
        warnings = warnings + ["Some words could not be read (marked [illegible])."]
    if confidence is not None and confidence < LOW_CONFIDENCE:
        warnings = warnings + [f"Low reading confidence ({confidence}); check this page against the original."]
    if engine == "hosted-vision" and HOSTED_WARNING not in warnings:
        warnings = warnings + [HOSTED_WARNING]
    return {"page": page, "engine": engine, "languages": languages, "confidence": confidence, "warnings": warnings, "uncertain": uncertain}


async def read_pdf(session_id: str, data: bytes, languages: tuple[str, ...] | None = None) -> tuple[list[str], list[dict]]:
    """(page texts, page metadata). Raises ValueError for oversized files and lets the hosted reader's errors through."""
    from pypdf import PdfReader

    languages = languages or configured_languages()
    try:
        embedded = [(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(data)).pages]
    except Exception:  # noqa: BLE001 - a damaged text layer just means every page goes to OCR
        embedded = []
    if len(embedded) > max_pages():
        raise ValueError(f"That PDF has {len(embedded)} pages; documents longer than {max_pages()} pages are not read automatically. Split it into parts and upload each.")
    pages: list[str] = list(embedded)
    meta: list[dict | None] = [None] * len(embedded)
    for i, t in enumerate(embedded):
        if len(t.replace(" ", "")) >= MIN_TEXT_LAYER:
            meta[i] = _meta(i + 1, "embedded-text", "", None, [], t)
    todo = [i for i, m in enumerate(meta) if m is None]
    if todo:
        cmd = tesseract_cmd()
        if cmd and renderer_available():
            have = installed_languages(cmd)
            use = [lang for lang in languages if lang in have] or (["eng"] if "eng" in have else [])
            if use:
                warn = [f"Language data not installed: {', '.join(l for l in languages if l not in have)}."] if len(use) < len(languages) else []
                langs = "+".join(use)
                try:
                    images = await asyncio.to_thread(render_pages, data)
                except Exception:  # noqa: BLE001
                    images = []
                for i in todo:
                    if i >= len(images):
                        continue
                    try:
                        text, conf, words = parse_tsv(await asyncio.to_thread(run_tesseract, cmd, images[i], langs))
                    except Exception:  # noqa: BLE001 - this page falls through to the hosted reader
                        continue
                    pages[i] = text
                    meta[i] = _meta(i + 1, "tesseract", langs, conf, list(warn), text)
        todo = [i for i, m in enumerate(meta) if m is None]
        if todo:
            hosted = await ocr.ocr_pdf(session_id, data)
            if not embedded:  # the file's own page list could not be read: the hosted reader's pages are all there is
                pages, meta = list(hosted), [None] * len(hosted)
                todo = list(range(len(hosted)))
            aligned = not embedded or len(hosted) == len(embedded)
            for i in todo:
                text = hosted[i] if i < len(hosted) else ""
                pages[i] = text
                meta[i] = _meta(i + 1, "hosted-vision", "any", None, [HOSTED_WARNING] + ([] if aligned else ["Page boundaries from the reader did not match the file; check the page numbers."]), text)
    return pages, [m for m in meta if m is not None]


def char_error_rate(truth: str, read: str) -> float:
    """Edit distance between the correct text and what was read, divided by the length of the correct text (0.0 = perfect). Whitespace is normalised first."""
    a, b = " ".join(truth.split()), " ".join(read.split())
    if not a:
        return 0.0 if not b else 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / len(a), 4)


def uncertain_pages(meta: list[dict]) -> list[int]:
    return [m["page"] for m in meta if m.get("uncertain")]
