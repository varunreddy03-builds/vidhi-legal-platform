"""Where a case citation is looked up. One adapter per source, all with the same small interface, so a second source can be added without touching the checker.

The one rule that matters here: an adapter either gives a DEFINITIVE answer (results, or a clearly empty and parseable reply) or it raises SourceDown.
A timeout, a refusal, a rate limit, a missing token, an error status or a reply that cannot be read is NEVER an empty answer. Only a definitive empty answer
can ever lead to "not found".

Judgment text is returned to the caller in memory for comparison; the report keeps only the citation, the result, the source link and the time.
The one source today is the local Supreme Court open dataset (scsource.py). This file holds what every source shares."""

import html
import os
import re
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import datetime, timezone


class SourceDown(Exception):
    """The source gave no definitive answer. `reason` is shown to the person in plain words."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Candidate:
    source: str
    doc_id: str
    title: str
    court: str
    url: str
    snippet: str = ""


@dataclass
class Attempt:
    """One query to one source: what was asked, when, and what came back. This is the audit trail behind every label."""

    strategy: str
    query: str
    source: str
    at: str
    status: str  # "results" | "empty" | "down"
    n: int = 0
    error: str = ""
    cost_inr: float = 0.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cost_per_lookup_inr() -> float:
    """An estimate (about Rs 21 for 30 citations was quoted), NOT a published price: set AUTHORITY_COST_PER_LOOKUP_INR to the real figure."""
    try:
        return float(os.environ.get("AUTHORITY_COST_PER_LOOKUP_INR", "0.7"))
    except ValueError:
        return 0.7


_TAGS = re.compile(r"<[^>]+>")


def plain(text: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", str(text or "")))).strip()


class _Blocks(HTMLParser):
    """The judgment's paragraph-level blocks (p, pre, blockquote; headings left out), in reading order, as plain text. Blocks nested in a block are part of the outer one, not repeated."""

    _BLOCK = ("p", "pre", "blockquote")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._depth = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCK:
            if self._depth == 0:
                self._buf = []
            self._depth += 1

    def handle_endtag(self, tag):
        if tag in self._BLOCK and self._depth:
            self._depth -= 1
            if self._depth == 0:
                text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self._buf)).strip()
                if text:
                    self.blocks.append(text)
                self._buf = []

    def handle_data(self, data):
        if self._depth:
            self._buf.append(data)


def blocks_of(doc_html: object) -> list[str]:
    parser = _Blocks()
    try:
        parser.feed(str(doc_html or ""))
        parser.close()
    except Exception:  # noqa: BLE001  (a page the parser cannot read gives no blocks; the caller then says the quote could not be checked)
        return []
    return parser.blocks
