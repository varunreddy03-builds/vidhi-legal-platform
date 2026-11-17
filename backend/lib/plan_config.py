"""The plans (free, pro, firm) as DATA: what each allows and what it costs, read from backend/data/plans.json (or the file named by PLANS_FILE) so the operator can change a limit or a price by editing
a file, with no code change and no restart (the file is looked at again when its modification time changes).

Safety rules:
* A file with any mistake (not JSON, a missing plan, a number that is not a whole number, an unknown task, a negative limit) is ignored AS A WHOLE and the built-in defaults are used, so a typo can never
  remove a limit. The reason is kept in `status()` for the operator console.
* ai_per_day must be a whole number for every plan (there is no 'unlimited' AI use); a value of null is allowed only where it means 'no limit' and is harmless: context_chars and members_max.
* A price of null means 'not set': nothing is invented and nothing can be bought for it. This file holds no payment details and takes no payment.
* The older settings FREE_AI_PER_DAY, PRO_AI_PER_DAY, FREE_CONTEXT_CHARS and FREE_AI_PLATFORM_PER_DAY, when set, still win over the file (a deployment that set them keeps working)."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "data" / "plans.json"
TIERS = ("free", "pro", "firm")
KNOWN_TASKS = ("synthesize", "analyze-contract")
MAX_AI = 100_000

DEFAULTS: dict = {
    "free_platform_ai_per_day": 3000,
    "plans": {
        "free": {"label": "Free", "price": {"amount": 0, "currency": "inr", "interval": "month"}, "ai_per_day": 5, "context_chars": 12000, "locked_tasks": list(KNOWN_TASKS), "members_max": None},
        "pro": {"label": "Pro", "price": {"amount": None, "currency": "inr", "interval": "month"}, "ai_per_day": 500, "context_chars": None, "locked_tasks": [], "members_max": None},
        "firm": {"label": "Firm", "price": {"amount": None, "currency": "inr", "interval": "month"}, "ai_per_day": 2000, "context_chars": None, "locked_tasks": [], "members_max": 25},
    },
}
_cache: dict = {"key": None, "data": DEFAULTS, "problem": None, "source": "built-in defaults"}


def path() -> Path:
    return Path(os.environ.get("PLANS_FILE") or DEFAULT_FILE)


def _whole(v, low=0, high=10**9) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and low <= v <= high


def problems(data) -> list[str]:
    """Everything wrong with a plans file, in plain words (empty = usable)."""
    bad: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("plans"), dict):
        return ['the file must be an object with a "plans" object in it']
    if not _whole(data.get("free_platform_ai_per_day", DEFAULTS["free_platform_ai_per_day"]), 0, 10**7):
        bad.append("free_platform_ai_per_day must be a whole number")
    for tier in TIERS:
        p = data["plans"].get(tier)
        if not isinstance(p, dict):
            bad.append(f"the {tier} plan is missing")
            continue
        if not _whole(p.get("ai_per_day"), 0, MAX_AI):
            bad.append(f"{tier}: ai_per_day must be a whole number from 0 to {MAX_AI} (it cannot be empty or unlimited)")
        if p.get("context_chars") is not None and not _whole(p["context_chars"], 1000, 10**7):
            bad.append(f"{tier}: context_chars must be a whole number from 1000, or null for no limit")
        if p.get("members_max") is not None and not _whole(p["members_max"], 1, 100_000):
            bad.append(f"{tier}: members_max must be a whole number from 1, or null for no limit")
        locked = p.get("locked_tasks")
        if not isinstance(locked, list) or any(t not in KNOWN_TASKS for t in locked):
            bad.append(f"{tier}: locked_tasks must be a list of tasks from {list(KNOWN_TASKS)}")
        price = p.get("price")
        if not isinstance(price, dict) or not (price.get("amount") is None or (isinstance(price["amount"], (int, float)) and not isinstance(price["amount"], bool) and 0 <= price["amount"] <= 10**8)):
            bad.append(f"{tier}: price.amount must be a number of 0 or more, or null for 'not set'")
        elif not isinstance(price.get("currency"), str) or not price["currency"].strip():
            bad.append(f"{tier}: price.currency is missing")
        if not isinstance(p.get("label"), str) or not p["label"].strip():
            bad.append(f"{tier}: label is missing")
    if not bad and data["plans"]["free"]["ai_per_day"] > data["plans"]["pro"]["ai_per_day"]:
        bad.append("the free plan cannot allow more AI requests a day than the pro plan")
    return bad


def load() -> dict:
    """The plans now in force. Cheap: the file is read again only when it changed."""
    p = path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(p), None, None)
    if _cache["key"] == key:
        return _cache["data"]
    data, problem, source = DEFAULTS, None, "built-in defaults"
    if key[1] is None:
        problem = f"the plans file {p.name} could not be found"
    else:
        try:
            parsed = json.loads(p.read_text(encoding="utf-8"))
            found = problems(parsed)
            if found:
                problem = "; ".join(found)
            else:
                data, source = parsed, str(p)
        except (OSError, ValueError) as exc:
            problem = f"the plans file could not be read ({type(exc).__name__})"
    if problem:
        logger.error("plans file ignored, built-in defaults used: %s", problem)
    _cache.update(key=key, data=data, problem=problem, source=source)
    return data


def status() -> dict:
    load()
    return {"source": _cache["source"], "problem": _cache["problem"], "file": str(path())}


def _env_int(name: str) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def plan(tier: str) -> dict:
    """The limits of one plan ('free', 'pro' or 'firm'), with the older environment settings applied on top. An unknown tier is treated as free (the strictest)."""
    tier = tier if tier in TIERS else "free"
    out = dict(load()["plans"][tier])
    if tier == "free":
        out["ai_per_day"] = _env_int("FREE_AI_PER_DAY") if _env_int("FREE_AI_PER_DAY") is not None else out["ai_per_day"]
        out["context_chars"] = _env_int("FREE_CONTEXT_CHARS") if _env_int("FREE_CONTEXT_CHARS") is not None else out["context_chars"]
    if tier == "pro" and _env_int("PRO_AI_PER_DAY") is not None:
        out["ai_per_day"] = _env_int("PRO_AI_PER_DAY")
    return out


def free_platform_ai_per_day() -> int:
    env = _env_int("FREE_AI_PLATFORM_PER_DAY")
    return env if env is not None else load().get("free_platform_ai_per_day", DEFAULTS["free_platform_ai_per_day"])
