"""Anonymous product numbers: how often each tool is used, how long it takes, and how often it fails. For the operator only.

WHAT IS KEPT, exactly (this list is the source for the privacy policy; docs/privacy/PRODUCT_NUMBERS.md repeats it):
  one row per day (an Indian calendar date) and per tool, holding only counters: runs, refused (a 4xx answer), failed (a 5xx answer), the total of the run times in milliseconds,
  and how many runs took under 1 s, 1 to 3 s, 3 to 10 s, and 10 s or more.
WHAT IS NOT KEPT: who used it (no user id, no organisation id, no email, no name), the request or the answer, any text, any file name, any id of a matter or a document, the IP address, the browser,
the time of day, or the exact route with its ids. The tool is chosen from the route TEMPLATE (for example /api/authority/checks), never from the real address.
The counters are written by the request middleware in server.py after the answer is built; a failure to write is swallowed (and logged without detail) so it can never break a request.
Rows older than ROWS_KEPT_DAYS are removed by the nightly retention job (lib/retention.py)."""

from pymongo.errors import DuplicateKeyError
import logging
import re
from datetime import datetime, timedelta, timezone

from lib.db import db

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
ROWS_KEPT_DAYS = 400
BUCKETS = (("under_1s", 1000), ("1_to_3s", 3000), ("3_to_10s", 10000), ("10s_or_more", None))

# (tool key, label shown to the operator, HTTP method, regex over the route TEMPLATE)
TOOLS: list[tuple[str, str, str, re.Pattern]] = [
    ("authority_check", "Authority Check", "POST", re.compile(r"^/api/authority/checks(/file)?$")),
    ("date_list", "List of dates", "POST", re.compile(r"^/api/datelists(/file)?$")),
    ("defect_check", "Pre-filing defect check", "POST", re.compile(r"^/api/defectchecks(/file)?$")),
    ("old_code_check", "Old-code to new-code checker", "POST", re.compile(r"^/api/oldcodechecks(/file)?$")),
    ("deadline_engine", "Deadline engine", "POST", re.compile(r"^/api/deadline-rules/calculate$")),
    ("research", "Ask / Research (AI)", "POST", re.compile(r"^/api/research$")),
    ("template_draft", "Draft from a template", "POST", re.compile(r"^/api/templates/\{template_id\}/draft$")),
    ("draft_check", "Check this draft", "POST", re.compile(r"^/api/drafts/\{draft_id\}/check$")),
    ("draft_review", "Send a draft for review", "POST", re.compile(r"^/api/drafts/\{draft_id\}/send-for-review$")),
    ("document_upload", "Document upload", "POST", re.compile(r"^/api/matters/\{matter_id\}/documents$")),
]
LABELS = {key: label for key, label, _, _ in TOOLS}


def tool_for(method: str, route: str) -> str | None:
    for key, _label, m, rx in TOOLS:
        if method == m and rx.match(route or ""):
            return key
    return None


def day_of(moment: datetime | None = None) -> str:
    return (moment or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m-%d")


def bucket_of(ms: float) -> str:
    for name, edge in BUCKETS:
        if edge is None or ms < edge:
            return name
    return BUCKETS[-1][0]


async def record(method: str, route: str, status: int, ms: float) -> None:
    """Count one finished request if it belongs to a tool. Never raises."""
    key = tool_for(method, route)
    if not key:
        return
    try:
        inc: dict = {"ms_total": int(ms), f"b_{bucket_of(ms)}": 1}
        if status >= 500:
            inc["failed"] = 1
        elif status >= 400:
            inc["refused"] = 1
        else:
            inc["runs"] = 1
        for attempt in (1, 2):  # two first requests of the day can race to create the row; the unique index lets one win, the other retries
            try:
                await db.product_stats.update_one({"day": day_of(), "tool": key}, {"$inc": inc, "$setOnInsert": {"day": day_of(), "tool": key}}, upsert=True)
                break
            except DuplicateKeyError:
                if attempt == 2:
                    raise
    except Exception as exc:  # noqa: BLE001 - counting must never break a request
        logger.warning("product numbers could not be recorded (%s)", type(exc).__name__)


async def trim(now: datetime | None = None) -> int:
    cutoff = day_of((now or datetime.now(timezone.utc)) - timedelta(days=ROWS_KEPT_DAYS))
    return (await db.product_stats.delete_many({"day": {"$lt": cutoff}})).deleted_count


async def report(days: int) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    first_day = day_of(since)
    rows: dict[str, dict] = {key: {} for key in LABELS}
    async for r in db.product_stats.find({"day": {"$gte": first_day}}, {"_id": 0}):
        t = rows.setdefault(r["tool"], {})
        for k, v in r.items():
            if k not in ("day", "tool") and isinstance(v, int):
                t[k] = t.get(k, 0) + v
    wrong = await db.pilot_feedback.count_documents({"kind": "wrong_result", "created_at": {"$gte": since}})  # only Authority Check has a "this result is wrong" button
    out = []
    for key, label in LABELS.items():
        t = rows.get(key, {})
        runs, failed, refused = t.get("runs", 0), t.get("failed", 0), t.get("refused", 0)
        finished = runs + failed + refused
        under3 = t.get("b_under_1s", 0) + t.get("b_1_to_3s", 0)
        has_button = key == "authority_check"
        out.append({
            "tool": key, "label": label, "runs": runs, "failed": failed, "refused": refused,
            "avg_ms": round(t.get("ms_total", 0) / finished) if finished else None,
            "buckets": {name: t.get(f"b_{name}", 0) for name, _ in BUCKETS},
            "share_under_3s_pct": round(100 * under3 / finished, 1) if finished else None,
            "failed_pct": round(100 * failed / finished, 1) if finished else None,
            "wrong_result_reports": wrong if has_button else None,
            "wrong_result_rate_pct": (round(100 * wrong / runs, 1) if runs else None) if has_button else None,
        })
    return {"days": days, "from_day": first_day, "tools": out,
            "note": "Counters only: no person, organisation, matter, text or address is kept. 'Wrong-result rate' exists only for Authority Check, the one tool with a 'this result is wrong' button (reports in the period divided by runs in the period); the other tools show a dash."}
