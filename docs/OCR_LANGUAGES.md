# Reading scans in Indian languages (2026-11-09)

VIDHI reads a scanned PDF with Tesseract first and a hosted AI model only for pages Tesseract leaves empty. Tesseract needs one `.traineddata` file per language.

**Set up on a machine or server**
1. Put the language files in a folder, for example `C:\vidhi-tools\tessdata` (here: Hindi, Telugu, Tamil, Kannada, Malayalam, Bengali, Marathi, Gujarati, Punjabi, Urdu, English; the "fast" models from the official tesseract-ocr/tessdata_fast repository, about 22 MB).
2. Copy the `configs` folder from the Tesseract install into that folder (without it word data cannot be read; VIDHI detects this and says so).
3. Set `OCR_TESSDATA_DIR` to the folder, and `OCR_LANGUAGES` (for example `eng+tel+hin+tam`). Names only are in `backend/.env.example`; real values go in `backend/.env`.
Default languages stay English, Telugu, Hindi. Tamil and the others are opt-in, because asking for four languages at once read Telugu slightly worse in the 2026-11-06 test.

**What the check showed (2026-11-09, clean synthetic one-line images in the Nirmala font, NOT real scans)**
Hindi 81.9, Telugu 83.5, Tamil 80.9, English 95.1 mean word confidence; each line came back readable but with wrong letters (for example the Hindi "याचिका" read as "याचकि", Telugu "న్యాయస్థానం" read as "నయయన్‌థనం"). So: usable for search and reading, never for a quotation without checking the original. VIDHI keeps the real confidence per page and marks low-confidence pages uncertain, so a claim resting on them cannot become VERIFIED. Real scanned court papers are NOT tested (needs the owner's scans).
