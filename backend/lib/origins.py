"""The single list of browser origins we trust (CORS and payment redirect targets)."""

import os
from urllib.parse import urlparse


def _origin_of(url: str) -> str | None:
    p = urlparse(url.strip())
    if p.scheme in ("http", "https") and p.netloc:
        return f"{p.scheme}://{p.netloc}".lower()
    return None


def has_wildcard() -> bool:
    return "*" in [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",")]


def allowed_origins() -> list[str]:
    """Explicit origins from CORS_ORIGINS plus APP_URL. A "*" entry is ignored: credentialed
    requests must never be allowed from arbitrary sites."""
    found: list[str] = []
    for raw in os.environ.get("CORS_ORIGINS", "").split(","):
        o = _origin_of(raw) if raw.strip() and raw.strip() != "*" else None
        if o:
            found.append(o)
    app = _origin_of(os.environ.get("APP_URL", ""))
    if app:
        found.append(app)
    return list(dict.fromkeys(found))


def is_allowed_origin(url: str, extra: str | None = None) -> bool:
    o = _origin_of(url)
    if o is None:
        return False
    return o in allowed_origins() or (extra is not None and o == _origin_of(extra))
