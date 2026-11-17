"""OCR a scanned PDF into plain text. Run with the SEPARATE OCR environment, not the app's:

    C:\\vidhi-tools\\venv-ocr\\Scripts\\python.exe -I -X utf8 scripts/ocr_pdf.py input.pdf output.txt [--max-pages N]

Uses pypdfium2 (draws each page) and RapidOCR (reads the picture). OCR is a program reading a picture: it makes mistakes, especially on stamps, tables and handwriting.
Text made this way is only ever a DRAFT. It is marked as OCR wherever it is kept and no lawyer has compared it with the page."""

import argparse
import sys

import pypdfium2 as pdfium
from rapidocr_onnxruntime import RapidOCR


def ocr_pdf(path: str, max_pages: int | None = None, scale: float = 2.0) -> str:
    engine = RapidOCR()
    pdf = pdfium.PdfDocument(path)
    pages: list[str] = []
    for i in range(len(pdf)):
        if max_pages is not None and i >= max_pages:
            break
        image = pdf[i].render(scale=scale).to_numpy()
        result, _ = engine(image)
        # result rows are [box, text, confidence]; read top to bottom, then left to right, in line bands
        rows = sorted(((r[0][0][1], r[0][0][0], r[1]) for r in (result or [])), key=lambda t: (round(t[0] / 12), t[1]))
        lines: list[str] = []
        band = None
        for y, _x, text in rows:
            b = round(y / 12)
            if band is not None and b == band and lines:
                lines[-1] += " " + text
            else:
                lines.append(text)
            band = b
        pages.append("\n".join(lines))
    return "\n\n".join(pages)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("out")
    ap.add_argument("--max-pages", type=int)
    a = ap.parse_args()
    text = ocr_pdf(a.pdf, a.max_pages)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"OCR wrote {len(text)} characters")
    return 0 if text.strip() else 1


if __name__ == "__main__":
    sys.exit(main())
