"""Upload validation shared by documents, recovery proofs and logos.

Extension alone is not trusted: content must match its claimed type, archives (DOCX) are bounded
against zip-bombs, and filenames are stripped of paths/control characters before being stored.
"""

import asyncio
import io
import os
import re
import zipfile

from fastapi import HTTPException, UploadFile

from lib import malware_scan

MAX_ZIP_ENTRIES = 3000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024  # 200 MB


def safe_filename(name: str | None, fallback: str = "untitled") -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base[:200] or fallback)


async def read_limited(file: UploadFile, max_bytes: int, too_big: str) -> bytes:
    """Read at most max_bytes+1 so an oversized upload is rejected without loading all of it."""
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=too_big)
    if malware_scan.mode() != "off":  # every upload route reads its file here, so none can skip the scan
        await asyncio.to_thread(malware_scan.check, data)
    return data


def _is_text(data: bytes) -> bool:
    head = data[:8192]
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multibyte char cut at the 8 KB boundary is fine; anything earlier is not text.
        if exc.start < len(head) - 4:
            return False
    return True


def _zip_office_check(member: str):
    """A Word, Excel or PowerPoint file is a zip holding one named part; this checks the zip is sane and holds it."""
    def check(data: bytes) -> bool:
        return _check_docx(data, member)
    return check


_HEADER_LINE = re.compile(rb"^(?:From|To|Date|Subject|Received|Return-Path|MIME-Version|Message-ID|Content-Type):", re.I | re.M)


def _check_eml(data: bytes) -> bool:
    """An email file is text that starts with header lines (From:, Date:, Subject: ...)."""
    return _is_text(data) and bool(_HEADER_LINE.search(data[:4096]))


def _check_docx(data: bytes, member: str = "word/document.xml") -> bool:
    if data[:4] != b"PK\x03\x04":
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return False
            if sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED:
                return False
            return any(i.filename == member for i in infos)
    except zipfile.BadZipFile:
        return False


_CHECKS = {
    ".pdf": lambda d: d[:5] == b"%PDF-",
    ".docx": _check_docx,
    ".xlsx": _zip_office_check("xl/workbook.xml"),
    ".pptx": _zip_office_check("ppt/presentation.xml"),
    ".eml": _check_eml,
    ".txt": _is_text,
    ".md": _is_text,
    ".png": lambda d: d[:8] == b"\x89PNG\r\n\x1a\n",
    ".jpg": lambda d: d[:3] == b"\xff\xd8\xff",
    ".jpeg": lambda d: d[:3] == b"\xff\xd8\xff",
    ".webp": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP",
    # media evidence (CCTV, recordings): container signatures only - we store and show them, we do not decode them
    ".mp4": lambda d: d[4:8] == b"ftyp",
    ".mov": lambda d: d[4:8] == b"ftyp" or d[4:8] in (b"moov", b"wide", b"mdat", b"free"),
    ".m4a": lambda d: d[4:8] == b"ftyp",
    ".webm": lambda d: d[:4] == b"\x1aE\xdf\xa3",
    ".mp3": lambda d: d[:3] == b"ID3" or (len(d) > 1 and d[0] == 0xFF and (d[1] & 0xE0) == 0xE0),
    ".wav": lambda d: d[:4] == b"RIFF" and d[8:12] == b"WAVE",
}


def validate_content(filename: str, data: bytes, allowed: tuple[str, ...], type_msg: str) -> None:
    """Raise 415 unless the extension is allowed AND the bytes look like that file type."""
    ext = os.path.splitext(filename.lower())[1]
    if ext not in allowed:
        raise HTTPException(status_code=415, detail=type_msg)
    if data[:2] == b"MZ" or data[:4] == b"\x7fELF":
        raise HTTPException(status_code=415, detail="That file type is not allowed.")
    check = _CHECKS.get(ext)
    if check is None or not check(data):
        raise HTTPException(
            status_code=415,
            detail="That file does not look like a valid " + ext.lstrip(".").upper() + " file.",
        )
