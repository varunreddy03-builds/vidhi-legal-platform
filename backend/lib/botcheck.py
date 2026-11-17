"""Bot protection for signup.

With Cloudflare Turnstile configured (TURNSTILE_SITE_KEY shown to the page, TURNSTILE_SECRET_KEY kept here) a signup needs a token that Cloudflare confirms.
Without it, a weaker fallback applies: a hidden field people never fill and a minimum time on the form. Those only stop simple bots, which is why Turnstile
is the real protection and is the first thing to switch on before launch. The per-address signup limit applies either way."""

import os

MIN_FORM_MS = 1200
_TRANSPORT = None  # tests inject an httpx.MockTransport here
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def configured() -> bool:
    return bool((os.environ.get("TURNSTILE_SECRET_KEY") or "").strip())


def site_key() -> str | None:
    return (os.environ.get("TURNSTILE_SITE_KEY") or "").strip() or None


async def human(token: str | None, ip: str | None, *, honeypot: str = "", elapsed_ms: int | None = None) -> bool:
    """True if this looks like a person. Fails closed when Turnstile is configured and anything is wrong."""
    if honeypot.strip():
        return False
    if configured():
        if not token or len(token) > 4096:
            return False
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0, transport=_TRANSPORT) as c:
                r = await c.post(VERIFY_URL, data={"secret": os.environ["TURNSTILE_SECRET_KEY"], "response": token, **({"remoteip": ip} if ip else {})})
            return r.status_code == 200 and r.json().get("success") is True
        except Exception:  # noqa: BLE001 - if Cloudflare cannot be reached, nobody gets in this way (fail closed)
            return False
    return elapsed_ms is None or elapsed_ms >= MIN_FORM_MS