"""Outbound email through Resend or SendGrid (HTTP APIs) - guarded. Recipients come from server records only (G4).

Configuration (environment):
  RESEND_API_KEY   API key (re_...)
  SENDGRID_API_KEY API key (SG....). EMAIL_PROVIDER=resend|sendgrid picks one; by default Resend if its key is set, else SendGrid.
  EMAIL_FROM       sender on a domain verified at the provider, e.g.  VIDHI <notices@mail.example.in>
  EMAIL_REPLY_TO   optional reply-to address
  EMAIL_DRY_RUN    DEV/TEST ONLY: capture mail in the email_outbox collection instead of sending
"""

import ipaddress
import logging
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from lib.monitoring import error_label

load_dotenv()
logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests inject httpx.MockTransport here

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = (
    "reply with your password", "reply with the code", "send your password", "cvv",
    "send us your password", "enter your password below", "confirm your card number",
    "your full card number", "seed phrase", "recovery phrase", "verify your card",
    "social security number", "confirm your bank details",
)
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self.visible: list[str] = []  # all text a reader can see (not attributes, not tags)
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        self.visible.append(data)
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    # Scan what a person reads, not link addresses: a random token in a link (for example "...xcvv...") must never trip this.
    visible_text = " ".join(scan.visible)
    body = re.sub(r"https?://\S+", " ", subject + "\n" + visible_text).lower()
    for p in _CRED_ASK:
        found = re.search(r"\b" + re.escape(p) + r"\b", body) if " " not in p else p in body
        if found:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")


def provider() -> str:
    """Which service sends the mail: EMAIL_PROVIDER if set and configured, else Resend, else SendGrid."""
    want = os.environ.get("EMAIL_PROVIDER", "").lower()
    has = {"resend": bool(os.environ.get("RESEND_API_KEY")), "sendgrid": bool(os.environ.get("SENDGRID_API_KEY"))}
    if want in has and has[want]:
        return want
    return "resend" if has["resend"] or not has["sendgrid"] else "sendgrid"


def _address(value: str) -> dict:
    """"Name <a@b.c>" or "a@b.c" -> SendGrid's {email, name}."""
    m = re.match(r"^\s*(.*?)\s*<\s*([^>]+)\s*>\s*$", value)
    return {"email": m.group(2), "name": m.group(1).strip(chr(34))} if m and m.group(1) else {"email": (m.group(2) if m else value).strip()}


async def _send_sendgrid(sender: str, to: str, subject: str, html: str, cc, reply, attachments) -> str | None:
    key = os.environ["SENDGRID_API_KEY"]
    pers: dict = {"to": [{"email": to}]}
    if cc:
        pers["cc"] = [{"email": c} for c in cc]
    payload: dict = {"personalizations": [pers], "from": _address(sender), "subject": subject, "content": [{"type": "text/html", "value": html}]}
    if reply:
        payload["reply_to"] = _address(reply)
    if attachments:
        payload["attachments"] = [{"content": a["content"], "filename": a["filename"], "type": "application/pdf" if a["filename"].lower().endswith(".pdf") else "application/octet-stream", "disposition": "attachment"} for a in attachments]
    async with httpx.AsyncClient(timeout=30, transport=_TRANSPORT) as client:
        resp = await client.post(SENDGRID_URL, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=payload)
    resp.raise_for_status()
    return resp.headers.get("x-message-id")  # SendGrid answers 202 with the id in a header


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    reply_to: str | None = None,
    attachments: list[dict] | None = None,
    cc: list[str] | None = None,
    idempotency_key: str | None = None,
) -> str | None:
    """Internal helper. `html` MUST come from a server-side template, never request input (G4).

    Returns the provider's message id. There is deliberately NO automatic retry: a send that timed out may
    have gone through, and the caller's idempotency key lets a deliberate retry avoid duplicates."""
    _assert_safe_email(subject, html)
    if os.environ.get("EMAIL_DRY_RUN", "false").lower() == "true":
        from datetime import datetime, timezone
        from uuid import uuid4

        from lib.db import db

        outbox_id = str(uuid4())
        await db.email_outbox.insert_one(
            {
                "id": outbox_id,
                "to": to,
                "cc": cc or [],
                "subject": subject,
                "html": html,
                "attachments": [a.get("filename") for a in (attachments or [])],
                "created_at": datetime.now(timezone.utc),
            }
        )
        return outbox_id

    sender = os.environ.get("EMAIL_FROM")
    if provider() == "sendgrid":
        if not os.environ.get("SENDGRID_API_KEY") or not sender:
            raise RuntimeError("SENDGRID_API_KEY and EMAIL_FROM must be configured to send email")
        try:
            return await _send_sendgrid(sender, to, subject, html, cc, reply_to or os.environ.get("EMAIL_REPLY_TO"), attachments)
        except Exception as e:  # noqa: BLE001
            logger.error("Email send failed: %s", error_label(e))  # the class and status only: a provider's message can repeat the address or the text
            raise
    key = os.environ.get("RESEND_API_KEY")
    if not key or not sender:
        raise RuntimeError("RESEND_API_KEY and EMAIL_FROM must be configured to send email")
    payload: dict = {"from": sender, "to": [to], "subject": subject, "html": html}
    if cc:
        payload["cc"] = cc
    reply = reply_to or os.environ.get("EMAIL_REPLY_TO")
    if reply:
        payload["reply_to"] = reply
    if attachments:
        payload["attachments"] = [{"filename": a["filename"], "content": a["content"]} for a in attachments]
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=30, transport=_TRANSPORT) as client:
            resp = await client.post(RESEND_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:  # noqa: BLE001
        logger.error("Email send failed: %s", error_label(e))
        raise
