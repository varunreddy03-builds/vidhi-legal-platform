"""AI spending caps, enforced by the backend (not by a dashboard): a monthly total, a daily total, and a daily amount per person.

Before EVERY paid AI call the money it could cost is reserved with atomic database updates that refuse if the month's cap, today's total cap or this person's cap for today would be
exceeded (a refusal gives back whatever was already reserved). After the call the reservation is replaced by the real cost (from the provider's own token counts where it reports them,
otherwise a cautious estimate). A failed call releases its reservation. Concurrent requests therefore cannot overshoot a cap, and a slow or retried call cannot be counted twice.
At 80% of the monthly cap the owner is alerted once a month; at 100% every AI call is refused until the next month. Each refusal says which limit was reached, in plain words (see
BudgetExceeded and ensure_available): the person's own daily allowance (429), today's shared total (503) or the month's budget (503).

The month and the day are the Indian calendar month and day (IST). The caps, the alert level and the price assumptions are settings:
  AI_MONTHLY_CAP_INR      default 20000     AI_ALERT_PERCENT   default 80          OWNER_ALERT_EMAIL   where the alert is sent
  AI_DAILY_CAP_INR        default 2000   all people together, per IST day (0 turns a cap off)
  Both totals GROW WITH PAYING CUSTOMERS: the month's cap is AI_MONTHLY_CAP_INR plus, for every active Pro seat, one Pro person's monthly allowance; the day's cap is AI_DAILY_CAP_INR plus, for
  every active Pro seat, one Pro person's daily allowance. A flat total would pause AI for everyone after about 25 Pro people. An administrator's absolute cap for a month (cap_override_inr) wins.
  AI_FREE_DAILY_CAP_INR   default 500    all FREE-plan people together, per IST day: free accounts can never use up the day's money that Pro customers pay for
  AI_USER_DAILY_CAP_INR   default 300    one Pro person, per IST day
  AI_FREE_USER_DAILY_CAP_INR default 15  one free-plan person, per IST day
  AI_USD_INR              default 97        AI_PRICES_JSON     per-provider {"sonnet": [in_usd_per_million, out_usd_per_million], ...}
The daily defaults were chosen on 2026-11-05 from docs/VIDHI_COST_MODEL.md (a Pro research answer about 4 rupees, a whole-matter synthesis about 34, a free-plan question about 1; those
figures are ASSUMED, not measured): 2000 is three times the monthly average (20000 / 30), 300 allows a Pro person two big syntheses and plenty of research, 15 covers the free plan's
5 requests a day. Set them from what the owner is willing to spend and from the real ledger (scripts/cost_report.py).
Who made a call, and on which plan, is known from the request (set by ensure_available, which every AI route runs first); a background job has no person and counts only against the totals.
The default prices are CAUTIOUS PLACEHOLDERS (they lean high so the cap stops spending early). Check each provider's current price page and
set AI_PRICES_JSON to the real numbers: the cap is only as accurate as these inputs.
The ledger keeps provider, task, token counts and cost: never prompts, documents or answers."""

import contextvars
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
# USD per million tokens (input, output), per MODEL, read from each provider's own price page on 2026-10-31:
#   Anthropic  https://platform.claude.com/docs/en/about-claude/pricing
#   Google     https://ai.google.dev/gemini-api/docs/pricing   (output price includes thinking tokens)
#   Groq       https://console.groq.com/docs/models
# Each entry is a schedule of (last day it applies, input, output); None means "from then on". Google's own page announces that Gemini 3.8 and 3.6 Flash
# double on 2027-01-01, so that change is built in. Prices change: re-read the pages every quarter and update the date above.
# NOT in this table because UNVERIFIED: OpenRouter's own fee on top of the provider price (a call through OpenRouter may cost a little more than shown).
MODEL_PRICES: list[tuple[str, list[tuple[str | None, float, float]]]] = [
    ("gemini-3.8-flash", [("2026-12-31", 0.75, 3.75), (None, 1.50, 7.50)]),
    ("gemini-3.6-flash", [("2026-12-31", 0.75, 3.75), (None, 1.50, 7.50)]),
    ("gemini-3.5-flash-lite", [(None, 0.30, 2.50)]),
    ("gemini-3.1-flash-lite", [(None, 0.25, 1.50)]),
    ("gemini-3.1-pro", [(None, 2.00, 12.00)]),
    ("gemini-3-flash", [(None, 0.50, 3.00)]),
    ("gemini-2.5-pro", [(None, 1.25, 10.00)]),
    ("gemini-2.5-flash-lite", [(None, 0.10, 0.40)]),
    ("gemini-2.5-flash", [(None, 0.30, 2.50)]),
    ("claude-sonnet-5", [(None, 2.00, 10.00)]),  # Sonnet 5 and Sonnet 5.5
    ("claude-haiku-5-5", [(None, 0.10, 0.50)]),  # for prompts up to 100,000 tokens; see LONG_PROMPT
    ("claude-haiku-4-5", [(None, 1.00, 5.00)]),
    ("gpt-oss-120b", [(None, 0.15, 0.60)]),
    ("gpt-oss-20b", [(None, 0.075, 0.30)]),
]
# models that cost more when the prompt is long: name -> (prompts over this many tokens, input, output)
LONG_PROMPT = {
    "claude-haiku-5-5": (100_000, 0.50, 2.50),
    "gemini-3.1-pro": (200_000, 4.00, 18.00),
    "gemini-2.5-pro": (200_000, 2.50, 15.00),
}
# which model each provider name means when no model name is given (the defaults in lib/ai.py)
DEFAULT_MODEL_FOR = {"gemini": "gemini-3.8-flash", "groq": "gpt-oss-120b", "haiku": "claude-haiku-4-5", "sonnet": "claude-sonnet-5-5"}
FALLBACK_PRICE = (3.0, 15.0)  # a model that is not in the table: a cautious price, and a warning in the log
FREE_PRICE = (0.0, 0.0)  # ollama: no per-token fee (hardware and power are the operator's cost)
DEFAULT_PRICES = {k: (0.0, 0.0) for k in ("ollama",)}  # kept for scripts that still read it; the real prices come from price_for()


MONTH_MESSAGE = "VIDHI's AI features are paused because this month's AI budget has been used up. They return at the start of next month. Tools that do not use AI keep working."
DAY_MESSAGE = "VIDHI's AI features have reached today's shared limit. They return after midnight (India time). Tools that do not use AI keep working."
USER_MESSAGE = "You have used your AI allowance for today. It renews after midnight (India time). Tools that do not use AI keep working."
FREE_MESSAGE = "The free plan has reached today's shared AI limit. It renews after midnight (India time); Pro is not affected. Tools that do not use AI keep working."
WEEK_MESSAGE = "You have used this week's AI allowance. It renews on Monday at midnight (India time). Tools that do not use AI keep working."
USER_MONTH_MESSAGE = "You have used this month's AI allowance. It renews on the 1st of next month (India time). Tools that do not use AI keep working."


AI_OFF_MESSAGE = "AI features are switched off for your organisation by its owner. Nothing you write is sent to an AI service. Tools that do not use AI keep working."


class BudgetExceeded(Exception):
    """A spending cap is reached. `scope` says which: "month" / "day" / "free" (shared by many people) or, for one person, "window" (the rolling few-hour limit), "user" (today), "week" or
    "user_month". `public_message` is what a person is shown, `status_code` the HTTP status (429 for a person's own allowance, 503 for a shared limit) and `retry_after()` the seconds until it
    renews. Subclassing Exception on purpose: callers that do not know about it still stop."""

    scope = "month"
    status_code = 503
    resets_at: datetime | None = None  # when this limit renews, when it is known

    @property
    def public_message(self) -> str:
        if self.scope == "window":
            when = ""
            if self.resets_at:
                at = self.resets_at.astimezone(IST)
                mins = max(1, int((self.resets_at - datetime.now(timezone.utc)).total_seconds() // 60))
                when = f" at {at:%H:%M} India time (in about {mins // 60} h {mins % 60} min)" if mins >= 60 else f" at {at:%H:%M} India time (in about {mins} min)"
            return f"You have reached your AI limit for this {window_hours():g}-hour period. It renews{when or ' when the period ends'}. Tools that do not use AI keep working."
        return {"month": MONTH_MESSAGE, "day": DAY_MESSAGE, "free": FREE_MESSAGE, "user": USER_MESSAGE, "week": WEEK_MESSAGE, "user_month": USER_MONTH_MESSAGE}[self.scope]

    def retry_after(self) -> int:
        if self.resets_at:
            return max(60, int((self.resets_at - datetime.now(timezone.utc)).total_seconds()))
        return 86400 if self.scope == "month" else seconds_to_midnight()


class AiSwitchedOff(BudgetExceeded):
    """The organisation's owner switched AI off. Not a spending limit, but it travels the same way (a clear refusal before anything is sent), so every route that handles
    BudgetExceeded handles it. There is no time when it renews, so there is no Retry-After."""

    scope = "org_off"
    status_code = 403

    @property
    def public_message(self) -> str:
        return AI_OFF_MESSAGE

    def retry_after(self) -> int:
        return 0


class DailyCapReached(BudgetExceeded):
    scope = "day"


class FreePoolCapReached(BudgetExceeded):
    scope = "free"


class UserDailyCapReached(BudgetExceeded):
    scope = "user"
    status_code = 429


class WindowCapReached(BudgetExceeded):
    scope = "window"
    status_code = 429


class WeekCapReached(BudgetExceeded):
    scope = "week"
    status_code = 429


class UserMonthCapReached(BudgetExceeded):
    scope = "user_month"
    status_code = 429


SCOPE_CLASS = {"month": BudgetExceeded, "day": DailyCapReached, "free": FreePoolCapReached, "user": UserDailyCapReached, "window": WindowCapReached, "week": WeekCapReached, "user_month": UserMonthCapReached}


def _raise(cls, text: str, resets_at: datetime | None = None):
    exc = cls(text)
    exc.resets_at = resets_at
    raise exc


# who is making the AI calls of this request: (user id, organisation id, plan "free" or "pro"). Set by ensure_available; a background job leaves it empty.
_CURRENT: contextvars.ContextVar[tuple | None] = contextvars.ContextVar("ai_budget_user", default=None)


def _plan_of(user: dict) -> str:
    try:
        from lib.plans import tier_of

        return "free" if tier_of(user) == "free" else "pro"
    except Exception:  # noqa: BLE001 - when the plan cannot be told, the stricter free limits apply
        return "free"


def set_current_user(user: dict | None) -> None:
    _CURRENT.set((str(user["id"]), user.get("organization_id"), _plan_of(user)) if user and user.get("id") else None)


def daily_cap_inr() -> float:
    return float(os.environ.get("AI_DAILY_CAP_INR", "2000"))


def free_daily_cap_inr() -> float:
    return float(os.environ.get("AI_FREE_DAILY_CAP_INR", "500"))


def window_hours() -> float:
    return float(os.environ.get("AI_WINDOW_HOURS", "5"))


def person_caps(plan: str = "pro") -> dict[str, float]:
    """One person's limits in rupees of AI cost, widest last. The Pro plan (Rs 1,999 a month) works like Claude's plans: a short rolling window (5 hours), a day, a week and the month, so a
    person cannot spend the month in one burst and a heavy day does not eat the whole week. The free plan has only a small daily amount (its request count is limited separately). 0 turns a limit off."""
    if plan == "free":
        return {"day": float(os.environ.get("AI_FREE_USER_DAILY_CAP_INR", "15"))}
    return {
        "window": float(os.environ.get("AI_USER_WINDOW_CAP_INR", "40")),
        "day": float(os.environ.get("AI_USER_DAILY_CAP_INR", "60")),
        "week": float(os.environ.get("AI_USER_WEEKLY_CAP_INR", "200")),
        "month": float(os.environ.get("AI_USER_MONTHLY_CAP_INR", "800")),
    }


def user_daily_cap_inr(plan: str = "pro") -> float:
    return person_caps(plan)["day"]


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m-%d")


def week_key(now: datetime | None = None) -> str:
    y, w, _ = (now or datetime.now(timezone.utc)).astimezone(IST).isocalendar()
    return f"{y}-W{w:02d}"


def next_midnight(now: datetime | None = None) -> datetime:
    t = (now or datetime.now(timezone.utc)).astimezone(IST)
    return (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_monday(now: datetime | None = None) -> datetime:
    t = (now or datetime.now(timezone.utc)).astimezone(IST)
    return (t + timedelta(days=7 - t.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_month_start(now: datetime | None = None) -> datetime:
    t = (now or datetime.now(timezone.utc)).astimezone(IST)
    first = t.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (first + timedelta(days=32)).replace(day=1).astimezone(timezone.utc)


def seconds_to_midnight(now: datetime | None = None) -> int:
    t = now or datetime.now(timezone.utc)
    return max(60, int((next_midnight(t) - t).total_seconds()))


class Reservation(str):
    """What `Budget.reserve` returns. It IS the month's id (a string, so existing callers keep working) and also remembers every other document that was reserved against (the day, the
    free plan's day, one person's day, week and month, and the person's rolling window), so settle and release change exactly those."""

    day_id: str | None = None
    pool_id: str | None = None
    person_docs: tuple = ()
    window_id: str | None = None
    window_start: datetime | None = None
    user_id: str | None = None
    org: str | None = None

    def others(self) -> list[str]:
        return [x for x in (self.day_id, self.pool_id, *self.person_docs) if x]


def cap_inr() -> float:
    return float(os.environ.get("AI_MONTHLY_CAP_INR", "20000"))


def alert_percent() -> float:
    return float(os.environ.get("AI_ALERT_PERCENT", "80"))


def usd_inr() -> float:
    """Rupees per US dollar. Default 97: just above the highest rate found for the 52 weeks to 22 July 2026 (96.96; the rate that day was about 96.5).
    UNVERIFIED for today: set AI_USD_INR to the current RBI reference rate. A higher number only makes the cap stricter, never looser."""
    return float(os.environ.get("AI_USD_INR") or "97")  # an empty value means "not set"


def prices() -> dict:
    """The owner's own overrides (AI_PRICES_JSON, flat prices per provider name). Empty unless the owner set it."""
    out: dict = {}
    try:
        for k, v in json.loads(os.environ.get("AI_PRICES_JSON", "{}") or "{}").items():
            out[k] = (float(v[0]), float(v[1]))
    except (ValueError, TypeError, IndexError):
        logger.error("AI_PRICES_JSON is not valid; using the built-in prices")
    return out


def _norm_model(model: str) -> str:
    return model.lower().replace(".", "-").replace("_", "-")


def price_for(model: str, tokens_in: int = 0, today: str | None = None) -> tuple[float, float] | None:
    """USD per million tokens (input, output) for a model name as of a day (default today, IST), or None when the model is not in the table."""
    name = _norm_model(model)
    day = today or datetime.now(timezone.utc).astimezone(IST).strftime("%Y-%m-%d")
    for key, schedule in sorted(MODEL_PRICES, key=lambda e: -len(e[0])):  # the most specific name wins ("gemini-2.5-flash-lite" before "gemini-2.5-flash")
        if _norm_model(key) in name:
            for last_day, p_in, p_out in schedule:
                if last_day is None or day <= last_day:
                    long = LONG_PROMPT.get(key)
                    if long and tokens_in > long[0]:
                        return (long[1], long[2])
                    return (p_in, p_out)
    return None


def est_tokens(text: str) -> int:
    """A cautious token estimate. Indian scripts take far more tokens per character than English, so they are counted heavier."""
    letters = [c for c in text if c.isalpha()]
    latin = not letters or sum(1 for c in letters if c.isascii()) / len(letters) >= 0.6
    return int(len(text) / (3.2 if latin else 1.2)) + 1


def file_tokens(mime: str, b64_len: int) -> int:
    raw = b64_len * 3 // 4
    return min(1_000_000, max(1500, raw // 20)) if mime == "application/pdf" else 1500


def cost_inr(provider: str, tokens_in: int, tokens_out: int, model: str | None = None, today: str | None = None) -> float:
    """Rupees for one call. The owner's AI_PRICES_JSON wins; otherwise the price of the MODEL named (or the provider's default model)."""
    own = prices()
    if provider in own:
        p_in, p_out = own[provider]
    elif provider == "ollama":
        p_in, p_out = FREE_PRICE
    else:
        name = model or DEFAULT_MODEL_FOR.get(provider, "")
        found = price_for(name, tokens_in, today) if name else None
        if found is None:
            logger.warning("no price on file for model %r (provider %s): using a cautious price", name or provider, provider)
            found = FALLBACK_PRICE
        p_in, p_out = found
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000 * usd_inr()


def fixed_cost_inr(kind: str, amount: float = 1.0) -> float:
    """Services priced by something other than tokens. kind: tts (characters), stt (bytes of audio), image (pictures)."""
    usd = {
        "tts": float(os.environ.get("AI_PRICE_TTS_PER_1K_CHARS_USD") or "0.30") * amount / 1000,
        "stt": float(os.environ.get("AI_PRICE_STT_PER_MIN_USD") or "0.40") * max(1.0, amount / 1_000_000),  # about a megabyte of audio a minute
        "image": float(os.environ.get("AI_PRICE_IMAGE_USD") or "0.08") * amount,
    }[kind]
    return usd * usd_inr()


def month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(IST).strftime("%Y-%m")


class Budget:
    def __init__(self, spend, ledger, alert=None, now=None, users=None, orgs=None):
        self.spend, self.ledger, self._alert, self._now = spend, ledger, alert, now or (lambda: datetime.now(timezone.utc))
        self.orgs = orgs  # the organisations collection, to honour an owner's "AI off" switch; without it nothing is switched off
        self.users = users  # the accounts collection, to count Pro seats; without it the totals stay at their base values
        self._seats_ttl, self._seats_at, self._seats_n = 300.0, None, 0

    async def ai_off(self, org_id: str | None) -> bool:
        """True when this organisation's owner switched AI off (organizations.ai_enabled is False). Checked on every reservation, so no path can spend for an organisation that said no."""
        if self.orgs is None or not org_id:
            return False
        row = await self.orgs.find_one({"id": org_id}, {"ai_enabled": 1})
        return bool(row) and row.get("ai_enabled") is False

    async def seats(self) -> int:
        """Active Pro seats (plan PRO, paid until now or within the grace days, or an older Pro account with no date). Counted at most once per `_seats_ttl` seconds."""
        if self.users is None:
            return 0
        t = time.monotonic()
        if self._seats_at is not None and t - self._seats_at < self._seats_ttl:
            return self._seats_n
        from lib.plans import GRACE

        self._seats_n = await self.users.count_documents({"plan": {"$in": ["PRO", "FIRM"]}, "$or": [{"pro_until": None}, {"pro_until": {"$gt": self._now() - GRACE}}]})
        self._seats_at = t
        return self._seats_n

    async def day_cap(self) -> float:
        """Today's total cap for everyone: the base plus one Pro daily allowance per active Pro seat (0 when the daily total is turned off)."""
        base = daily_cap_inr()
        return base + await self.seats() * person_caps("pro").get("day", 0) if base > 0 else 0.0

    def _mid(self) -> str:
        return month_key(self._now())

    async def _doc(self, mid: str) -> dict:
        await self.spend.update_one(
            {"_id": mid}, {"$setOnInsert": {"reserved_inr": 0.0, "spent_inr": 0.0, "calls": 0, "by_provider": {}, "by_task": {}, "created_at": self._now()}}, upsert=True
        )
        return await self.spend.find_one({"_id": mid})

    async def cap(self, doc: dict | None = None) -> float:
        doc = doc or await self._doc(self._mid())
        if doc.get("cap_override_inr"):
            return float(doc["cap_override_inr"])  # an administrator's absolute cap for this month
        return cap_inr() + await self.seats() * person_caps("pro").get("month", 0)

    async def _part(self, doc_id: str, est_inr: float, cap: float):
        """Reserve est_inr in one document (a day, a week, a person's period...) unless that would pass `cap`. None when refused."""
        for _ in range(2):  # two calls creating the document at the same moment: the second one just finds it
            try:
                await self.spend.update_one({"_id": doc_id}, {"$setOnInsert": {"reserved_inr": 0.0, "spent_inr": 0.0, "calls": 0, "created_at": self._now()}}, upsert=True)
                break
            except DuplicateKeyError:
                continue
        return await self.spend.find_one_and_update({"_id": doc_id, "$expr": {"$lte": [{"$add": ["$reserved_inr", est_inr]}, cap]}}, {"$inc": {"reserved_inr": est_inr}})

    async def _window_part(self, uid: str, est_inr: float, cap: float):
        """The person's rolling window (a few hours, started by their first call after the last one ended). Returns (document before this reservation, or None when refused, its start)."""
        wid, now = f"w:{uid}", self._now()
        for _ in range(2):
            try:
                await self.spend.update_one({"_id": wid}, {"$setOnInsert": {"start": now, "reserved_inr": 0.0, "spent_inr": 0.0, "calls": 0}}, upsert=True)
                break
            except DuplicateKeyError:
                continue
        await self.spend.update_one({"_id": wid, "start": {"$lte": now - timedelta(hours=window_hours())}},
                                    {"$set": {"start": now, "reserved_inr": 0.0, "spent_inr": 0.0, "calls": 0}})  # the last window has ended: a new one starts (only one caller wins this)
        got = await self.spend.find_one_and_update({"_id": wid, "$expr": {"$lte": [{"$add": ["$reserved_inr", est_inr]}, cap]}}, {"$inc": {"reserved_inr": est_inr}})
        if got is not None:
            return got, got["start"]
        cur = await self.spend.find_one({"_id": wid}) or {}
        return None, cur.get("start", now)

    def _person_docs(self, uid: str, plan: str) -> list[tuple[str, str, float, datetime]]:
        """(scope, document id, cap, when it renews) for one person's day, week and month (the window is handled apart), in the order they are checked."""
        now, caps = self._now(), person_caps(plan)
        out = []
        if caps.get("day", 0) > 0:
            out.append(("user", f"u:{uid}:{day_key(now)}", caps["day"], next_midnight(now)))
        if caps.get("week", 0) > 0:
            out.append(("week", f"k:{uid}:{week_key(now)}", caps["week"], next_monday(now)))
        if caps.get("month", 0) > 0:
            out.append(("user_month", f"m:{uid}:{now.astimezone(IST):%Y-%m}", caps["month"], next_month_start(now)))
        return out

    async def reserve(self, est_inr: float, user: tuple | None = None) -> Reservation:
        """Set aside est_inr, atomically, against the month, today, (for a free-plan person) the free plan's day, and (when the caller is a known person) that person's rolling window, day, week
        and month; raise BudgetExceeded (with the scope that was reached) if any cap would be passed, after giving back whatever was already set aside."""
        who = user or _CURRENT.get()
        if who and len(who) > 1 and await self.ai_off(who[1]):
            raise AiSwitchedOff("AI is switched off for this organisation")  # before anything is set aside or sent
        mid = self._mid()
        doc = await self._doc(mid)
        cap = await self.cap(doc)
        got = await self.spend.find_one_and_update({"_id": mid, "$expr": {"$lte": [{"$add": ["$reserved_inr", est_inr]}, cap]}}, {"$inc": {"reserved_inr": est_inr}})
        if got is None:
            await self._maybe_alert(mid, "100", doc, cap)
            raise BudgetExceeded(f"the monthly AI budget of {cap:,.0f} rupees is used up")
        await self._maybe_alert(mid, "80", {**got, "reserved_inr": got["reserved_inr"] + est_inr}, cap)
        res = Reservation(mid)
        now = self._now()
        day = day_key(now)
        who = user or _CURRENT.get()
        try:
            dcap = await self.day_cap()
            if dcap > 0:
                if await self._part(f"d:{day}", est_inr, dcap) is None:
                    logger.warning("AI daily cap of %.0f rupees reached for %s", dcap, day)
                    _raise(DailyCapReached, f"today's AI cap of {dcap:,.0f} rupees is used up", next_midnight(now))
                res.day_id = f"d:{day}"
            plan = who[2] if who and len(who) > 2 else "pro"
            fcap = free_daily_cap_inr()
            if who and plan == "free" and fcap > 0:
                if await self._part(f"f:{day}", est_inr, fcap) is None:
                    logger.warning("AI daily cap of %.0f rupees reached for the free plan on %s", fcap, day)
                    _raise(FreePoolCapReached, f"the free plan's AI cap of {fcap:,.0f} rupees for today is used up", next_midnight(now))
                res.pool_id = f"f:{day}"
            if who:
                res.user_id, res.org = who[0], who[1]
                caps = person_caps(plan)
                if caps.get("window", 0) > 0:
                    before, start = await self._window_part(who[0], est_inr, caps["window"])
                    if before is None:
                        logger.warning("AI %g-hour limit reached for one person", window_hours())
                        _raise(WindowCapReached, f"this person's {window_hours():g}-hour AI cap of {caps['window']:,.0f} rupees is used up", _utc(start) + timedelta(hours=window_hours()))
                    res.window_id, res.window_start = f"w:{who[0]}", start
                taken: list[str] = []
                for scope, doc_id, pcap, renews in self._person_docs(who[0], plan):
                    if await self._part(doc_id, est_inr, pcap) is None:
                        res.person_docs = tuple(taken)
                        logger.warning("AI %s cap of %.0f rupees reached for one person", scope, pcap)
                        _raise(SCOPE_CLASS[scope], f"this person's AI cap of {pcap:,.0f} rupees ({scope}) is used up", renews)
                    taken.append(doc_id)
                res.person_docs = tuple(taken)
        except BudgetExceeded:
            await self.release(res, est_inr)
            raise
        return res

    async def _adjust(self, mid, delta: float, spent: float = 0.0, calls: int = 0) -> None:
        inc = {"reserved_inr": delta, **({"spent_inr": spent, "calls": calls} if calls else {})}
        for extra in getattr(mid, "others", lambda: [])():
            await self.spend.update_one({"_id": extra}, {"$inc": inc})
        if getattr(mid, "window_id", None):  # only while it is still the same window: a window that has rolled over since is not touched
            await self.spend.update_one({"_id": mid.window_id, "start": mid.window_start}, {"$inc": inc})

    async def release(self, mid: str, est_inr: float) -> None:
        await self.spend.update_one({"_id": str(mid)}, {"$inc": {"reserved_inr": -est_inr}})
        await self._adjust(mid, -est_inr)

    async def limit_info(self, user_id: str | None = None, plan: str = "pro") -> tuple[str, datetime | None] | None:
        """(scope, when it renews) of the limit that is already used up right now, or None. The shared limits come first; of one person's own limits the one that renews LAST is named,
        because that is when they can really use AI again. A cheap look so a person gets a clear message before any work is done."""
        now = self._now()
        doc = await self.spend.find_one({"_id": self._mid()})
        if doc and float(doc.get("reserved_inr", 0)) >= await self.cap(doc):
            return "month", None
        day = day_key(now)
        dcap = await self.day_cap()
        if dcap > 0:
            d = await self.spend.find_one({"_id": f"d:{day}"})
            if d and float(d.get("reserved_inr", 0)) >= dcap:
                return "day", next_midnight(now)
        fcap = free_daily_cap_inr()
        if user_id and plan == "free" and fcap > 0:
            f = await self.spend.find_one({"_id": f"f:{day}"})
            if f and float(f.get("reserved_inr", 0)) >= fcap:
                return "free", next_midnight(now)
        if not user_id:
            return None
        full: list[tuple[str, datetime]] = []
        wcap = person_caps(plan).get("window", 0)
        if wcap > 0:
            w = await self.spend.find_one({"_id": f"w:{user_id}"})
            if w and _utc(w["start"]) + timedelta(hours=window_hours()) > now and float(w.get("reserved_inr", 0)) >= wcap:
                full.append(("window", _utc(w["start"]) + timedelta(hours=window_hours())))
        for scope, doc_id, pcap, renews in self._person_docs(user_id, plan):
            u = await self.spend.find_one({"_id": doc_id})
            if u and float(u.get("reserved_inr", 0)) >= pcap:
                full.append((scope, renews))
        return max(full, key=lambda x: x[1]) if full else None

    async def limit_reached(self, user_id: str | None = None, plan: str = "pro") -> str | None:
        """Just the scope of limit_info."""
        info = await self.limit_info(user_id, plan)
        return info[0] if info else None

    async def usage(self, user_id: str, plan: str = "pro") -> list[dict]:
        """One person's use of each of their limits, as a share (never rupees) and when it renews, for a usage meter like Claude's. Only limits that are on are listed."""
        now, rows = self._now(), []
        caps = person_caps(plan)
        if caps.get("window", 0) > 0:
            w = await self.spend.find_one({"_id": f"w:{user_id}"})
            live = bool(w) and _utc(w["start"]) + timedelta(hours=window_hours()) > now
            used = float(w.get("reserved_inr", 0)) if live else 0.0
            rows.append({"name": "window", "label": f"{window_hours():g}-hour", "percent": round(min(100.0, 100 * used / caps["window"]), 1), "resets_at": (_utc(w["start"]) + timedelta(hours=window_hours())).isoformat() if live else None})
        labels = {"user": "day", "week": "week", "user_month": "month"}
        for scope, doc_id, pcap, renews in self._person_docs(user_id, plan):
            u = await self.spend.find_one({"_id": doc_id})
            rows.append({"name": labels[scope], "label": labels[scope], "percent": round(min(100.0, 100 * float((u or {}).get("reserved_inr", 0)) / pcap), 1), "resets_at": renews.isoformat()})
        return rows

    async def settle(self, mid: str, est_inr: float, actual_inr: float, *, provider: str, task: str, org: str | None = None, tokens: tuple[int, int] | None = None, estimated: bool = True, latency_ms: int | None = None, model: str | None = None) -> None:
        """Replace the reservation by what the call really cost, and record it: one ledger row (who, which model, tokens, rupees; never the prompt or the answer) and one log line."""
        await self.spend.update_one(
            {"_id": str(mid)},
            {"$inc": {"reserved_inr": actual_inr - est_inr, "spent_inr": actual_inr, "calls": 1, f"by_provider.{provider}": actual_inr, f"by_task.{task}": actual_inr}},
        )
        await self._adjust(mid, actual_inr - est_inr, actual_inr, 1)
        user_id, org = getattr(mid, "user_id", None), org or getattr(mid, "org", None)
        await self.ledger.insert_one({
            "created_at": self._now(), "month": str(mid), "day": day_key(self._now()), "provider": provider, "model": model, "task": task, "organization_id": org, "user_id": user_id,
            "cost_inr": round(actual_inr, 4), "tokens_in": tokens[0] if tokens else None, "tokens_out": tokens[1] if tokens else None, "estimated": estimated, "ok": True, "latency_ms": latency_ms,
        })
        logger.info("ai cost provider=%s model=%s task=%s tokens_in=%s tokens_out=%s cost_inr=%.4f estimated=%s user=%s", provider, model, task,
                    tokens[0] if tokens else None, tokens[1] if tokens else None, actual_inr, estimated, user_id)  # numbers and ids only: never the prompt, a document or an answer
        doc = await self.spend.find_one({"_id": mid})
        await self._maybe_alert(mid, "80", doc, await self.cap(doc))

    async def record_failure(self, *, provider: str, task: str, latency_ms: int, error: str) -> None:
        """A call that failed costs nothing, but its provider, task, time and error class are kept so failure rates and latency can be measured (never the prompt or the provider's message)."""
        try:
            await self.ledger.insert_one({"created_at": self._now(), "month": self._mid(), "provider": provider, "task": task, "cost_inr": 0.0, "ok": False, "latency_ms": latency_ms, "error": error[:60]})
        except Exception:  # noqa: BLE001 - bookkeeping must never mask the real failure
            logger.exception("could not record the failed AI call")

    async def reliability(self, since_days: int = 30) -> dict:
        """Per provider over the recent ledger: calls, failures, failure rate and latency (p50/p95) in milliseconds. Only what was recorded: an empty ledger gives an empty result."""
        since = self._now() - timedelta(days=since_days)
        rows = await self.ledger.find({"created_at": {"$gte": since}}, {"provider": 1, "ok": 1, "latency_ms": 1, "_id": 0}).to_list(50000)
        out: dict[str, dict] = {}
        for r in rows:
            o = out.setdefault(r["provider"], {"calls": 0, "failures": 0, "lat": []})
            o["calls"] += 1
            o["failures"] += 0 if r.get("ok", True) else 1
            if r.get("latency_ms") is not None:
                o["lat"].append(r["latency_ms"])
        res = {}
        for prov, o in out.items():
            lat = sorted(o["lat"])
            pick = lambda q: lat[min(len(lat) - 1, int(q * (len(lat) - 1) + 0.5))] if lat else None  # noqa: E731
            res[prov] = {"calls": o["calls"], "failures": o["failures"], "failure_rate_pct": round(100 * o["failures"] / o["calls"], 1), "latency_ms_p50": pick(0.5), "latency_ms_p95": pick(0.95), "latency_samples": len(lat)}
        return res

    async def _maybe_alert(self, mid: str, level: str, doc: dict, cap: float) -> None:
        used = float(doc.get("reserved_inr", 0))
        threshold = cap if level == "100" else cap * alert_percent() / 100
        if used < threshold - 1e-9 and level == "80":
            return
        field = f"alert{level}_at"
        won = await self.spend.update_one({"_id": mid, field: {"$exists": False}}, {"$set": {field: self._now()}})
        if won.modified_count and self._alert:
            try:
                await self._alert(level, used, cap)
            except Exception:  # noqa: BLE001 - an alert that cannot be sent must never break the call that triggered it
                logger.exception("could not send the AI budget alert")

    async def status(self) -> dict:
        mid = self._mid()
        doc = await self._doc(mid)
        cap = await self.cap(doc)
        used = float(doc.get("reserved_inr", 0))
        today = await self.spend.find_one({"_id": f"d:{day_key(self._now())}"}) or {}
        return {
            "day": day_key(self._now()), "daily_cap_inr": await self.day_cap(), "pro_seats": await self.seats(), "daily_used_inr": round(float(today.get("reserved_inr", 0)), 2), "free_daily_cap_inr": free_daily_cap_inr(), "user_daily_cap_inr": user_daily_cap_inr("pro"), "free_user_daily_cap_inr": user_daily_cap_inr("free"), "pro_person_caps_inr": person_caps("pro"), "window_hours": window_hours(),
            "month": mid, "cap_inr": cap, "used_inr": round(used, 2), "spent_inr": round(float(doc.get("spent_inr", 0)), 2), "percent": round(100 * used / cap, 1) if cap else 100.0,
            "calls": int(doc.get("calls", 0)), "by_provider": {k: round(v, 2) for k, v in (doc.get("by_provider") or {}).items()}, "by_task": {k: round(v, 2) for k, v in (doc.get("by_task") or {}).items()},
            "alert80_sent": "alert80_at" in doc, "exhausted": used >= cap, "alert_email_configured": bool(os.environ.get("OWNER_ALERT_EMAIL")),
        }


async def notify_owner(level: str, used: float, cap: float) -> None:
    """Email the owner. With no OWNER_ALERT_EMAIL it is logged loudly and shown in the admin console instead (never silently lost)."""
    pct = alert_percent() if level == "80" else 100
    subject = f"VIDHI AI budget: {pct:.0f}% of this month's cap reached"
    text = (f"The AI spending for this month has reached {used:,.0f} rupees of the {cap:,.0f} rupee cap ({pct:.0f}%)."
            + (" AI features are now paused until next month." if level == "100" else " AI features keep working; at 100% they pause until next month."))
    logger.error("%s: %s", subject, text)
    to = os.environ.get("OWNER_ALERT_EMAIL")
    if not to:
        return
    from lib.email import send_email

    await send_email(to=to, subject=subject, html=f'<p style="font-family:Arial,sans-serif">{text}</p>')


_instance: Budget | None = None


def get_budget() -> Budget:
    global _instance
    if _instance is None:
        from lib.db import db

        _instance = Budget(db.ai_spend, db.ai_ledger, alert=notify_owner, users=db.users, orgs=db.organizations)
    return _instance


async def ensure_available(user: dict | None = None) -> None:
    """A cheap early check so a person gets a clear message instead of a failed call, and the place where the request's person is recorded for the budget. (The hard stop is the
    reservation itself.) Pass the signed-in user from every AI route: without one only the shared limits can be checked."""
    from fastapi import HTTPException

    set_current_user(user)
    b = get_budget()
    if user and hasattr(b, "ai_off") and await b.ai_off(user.get("organization_id")):
        raise HTTPException(status_code=AiSwitchedOff.status_code, detail=AI_OFF_MESSAGE)
    uid = str(user["id"]) if user and user.get("id") else None
    plan = _plan_of(user) if uid else "pro"
    info = None
    if hasattr(b, "limit_info"):
        info = await b.limit_info(uid, plan)
    elif hasattr(b, "limit_reached"):
        scope = await b.limit_reached(uid, plan)
        info = (scope, None) if scope else None
    if info is None and (await b.status())["exhausted"]:
        info = ("month", None)
    if info:
        exc = SCOPE_CLASS[info[0]]()
        exc.resets_at = info[1]
        raise HTTPException(status_code=exc.status_code, detail=exc.public_message, headers={"Retry-After": str(exc.retry_after())})


class fixed:
    """async with fixed("tts", chars, task="tts"): ... for services priced by characters, minutes or pictures."""

    def __init__(self, kind: str, amount: float, task: str | None = None, org: str | None = None):
        self.kind, self.cost, self.task, self.org = kind, fixed_cost_inr(kind, amount), task or kind, org

    async def __aenter__(self):
        self.mid = await get_budget().reserve(self.cost)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            await get_budget().settle(self.mid, self.cost, self.cost, provider=self.kind, task=self.task, org=self.org)
        else:
            await get_budget().release(self.mid, self.cost)
        return False
