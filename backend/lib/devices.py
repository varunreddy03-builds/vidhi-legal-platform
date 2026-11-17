"""Describing where someone is signed in, without keeping more than needed.
We keep a short description ("Chrome on Windows"), a hash of that description (to notice a new device) and the IP with its last part hidden."""

import hashlib
import ipaddress
import re

_BROWSERS = [("Edge", r"Edg(e|A|iOS)?/"), ("Opera", r"OPR/|Opera"), ("Firefox", r"Firefox/|FxiOS"), ("Chrome", r"Chrome/|CriOS"), ("Safari", r"Safari/")]
_SYSTEMS = [("Android", r"Android"), ("iPhone or iPad", r"iPhone|iPad|iPod"), ("Windows", r"Windows"), ("Mac", r"Macintosh|Mac OS X"), ("Linux", r"Linux|X11")]


def parse(ua: str | None) -> tuple[str, str]:
    ua = ua or ""
    browser = next((n for n, rx in _BROWSERS if re.search(rx, ua)), "A browser")
    system = next((n for n, rx in _SYSTEMS if re.search(rx, ua)), "an unknown device")
    return browser, system


def describe(ua: str | None) -> str:
    b, s = parse(ua)
    return f"{b} on {s}"


def fingerprint(ua: str | None) -> str:
    return hashlib.sha256(describe(ua).encode()).hexdigest()[:16]


def mask_ip(ip: str | None) -> str:
    """203.0.113.57 -> 203.0.113.x ; 2001:db8:1:2::5 -> 2001:db8:1:x. Enough to recognise a place, not to identify a person."""
    try:
        a = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return "unknown"
    if a.version == 4:
        return ".".join(str(a).split(".")[:3]) + ".x"
    return ":".join(a.exploded.split(":")[:3]) + ":x"