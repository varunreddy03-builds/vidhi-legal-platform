"""Field-level encryption for the text taken out of uploaded documents (documents.pages), with the same key as the uploaded files (DATA_ENCRYPTION_KEY).

Why: the original files were already encrypted at rest, but the text read from them sat in MongoDB as plain fields, so anyone who could read the database (or a backup of it) could
read every client document. Each page is now stored as "vp1:" + base64 of an AES-256-GCM blob. Reading opens it again, so the rest of the code sees ordinary text.

* Pages written before this existed are plain strings: they are read as they are and are encrypted by the startup migration 0002 (and by tools/encrypt_text.py).
* With no key configured nothing is encrypted (a laptop); a live site refuses to start without one (lib/startup_check.py).
* A page that was encrypted with a key this server no longer has raises an error rather than returning garbage: keep every old key in DATA_ENCRYPTION_KEY (comma separated)."""

import base64

from lib import crypto

PREFIX = "vp1:"
AAD = b"vidhi-doc-pages"


def is_sealed(page: object) -> bool:
    return isinstance(page, str) and page.startswith(PREFIX)


def seal_page(page: object) -> object:
    if not isinstance(page, str) or not page or is_sealed(page) or not crypto.enabled():
        return page
    return PREFIX + base64.urlsafe_b64encode(crypto.encrypt(page.encode("utf-8"), AAD)).decode("ascii")


def open_page(page: object) -> object:
    if not is_sealed(page):
        return page
    return crypto.decrypt(base64.urlsafe_b64decode(page[len(PREFIX):].encode("ascii")), AAD).decode("utf-8")


def seal_pages(pages: object) -> object:
    return [seal_page(p) for p in pages] if isinstance(pages, list) else pages


def open_pages(pages: object) -> object:
    return [open_page(p) for p in pages] if isinstance(pages, list) else pages


def open_doc(doc: dict | None) -> dict | None:
    """The document row with its pages opened (the same dict, changed in place; None stays None)."""
    if doc and "pages" in doc:
        doc["pages"] = open_pages(doc["pages"])
    return doc
