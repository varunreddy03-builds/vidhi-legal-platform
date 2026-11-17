"""What each plan of Legal Intelligence includes. Legal Recovery is free for everyone and is never limited here.

FREE  simple questions and single-document reading, with the light AI models, a small reading budget and a few AI
      requests a day. It deliberately does not take on complex work: no contract review, no whole-matter synthesis.
PRO   (a monthly subscription) everything, the strongest models, the full reading budget and a generous daily allowance.

The plan belongs to the organisation (its owner pays); every member uses it. These limits are enforced here on the
server; the screens only describe them.
"""

import os
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException

from lib.ratelimit import hit

# The numbers (AI requests a day, how much the AI reads at once, locked tasks, people allowed, prices) are DATA in backend/data/plans.json, read by lib/plan_config.py, so the operator changes them by editing a file.
from lib import plan_config

GRACE = timedelta(days=2)  # a late renewal does not lock people out the same hour

FREE_LOCKED = {  # what each lockable task is called when a plan does not include it
    "synthesize": "Reading every document in a matter together to find who is who and where sources differ",
    "analyze-contract": "Clause-by-clause contract review",
}
PAID = ("pro", "firm")


def price() -> dict:
    return {
        "amount": float(Decimal(os.environ.get("PRO_PRICE_AMOUNT", "1999"))),
        "currency": os.environ.get("PRO_PRICE_CURRENCY", "inr").lower(),
        "interval": "month",
    }


def summary() -> dict:
    """The plan comparison shown in Settings (kept next to the enforcement so they cannot drift apart)."""
    free, pro, firm = (plan_config.plan(t) for t in ("free", "pro", "firm"))
    fprice = firm["price"]
    return {
        "price": price(),
        "free": {
            "ai_per_day": free["ai_per_day"],
            "locked": [FREE_LOCKED[t] for t in free["locked_tasks"]],
            "reads_at_once_chars": free["context_chars"],
            "members_max": free["members_max"],
            "models": "Light, fast models. Good for simple questions; not for complex matters.",
        },
        "pro": {
            "ai_per_day": pro["ai_per_day"],
            "locked": [FREE_LOCKED[t] for t in pro["locked_tasks"]],
            "reads_at_once_chars": pro["context_chars"],
            "members_max": pro["members_max"],
            "models": "The strongest models, chosen per task, with automatic fall-back.",
        },
        "firm": {
            "ai_per_day": firm["ai_per_day"],
            "locked": [FREE_LOCKED[t] for t in firm["locked_tasks"]],
            "reads_at_once_chars": firm["context_chars"],
            "members_max": firm["members_max"],
            "price": None if fprice.get("amount") is None else {"amount": float(fprice["amount"]), "currency": str(fprice["currency"]).lower(), "interval": fprice.get("interval", "month")},
            "models": "The strongest models, chosen per task, with automatic fall-back. Set up for your organisation by VIDHI; there is no online checkout for it.",
        },
    }


def tier_of(user: dict) -> str:
    from lib.auth import entitlement_for

    return entitlement_for(user)["tier"]


def context_budget(user: dict) -> int | None:
    """How much matter text the AI may be shown: capped on the free plan, the normal budget otherwise."""
    return plan_config.plan(tier_of(user))["context_chars"]


async def usage_today(user: dict) -> dict:
    """AI requests used today by this organisation on the free plan (shown in Settings so nobody is surprised)."""
    from lib.ratelimit import _limit, peek

    tier = tier_of(user)
    cfg = plan_config.plan(tier)
    limit = _limit(f"plan-ai-{tier}", cfg["ai_per_day"])
    used = min(await peek(f"plan-ai-{tier}", user["organization_id"], 86400), limit)
    members = await members_in_use(user["organization_id"])
    usage = {"ai_used_today": used, "ai_limit_today": limit, "members_used": members, "members_limit": cfg["members_max"]}
    if tier != "free":
        return {"ai_used_today": 0, "ai_limit_today": None, "usage": usage}  # the older two fields keep their meaning: they describe the free plan only
    return {"ai_used_today": used, "ai_limit_today": limit, "usage": usage}


async def members_in_use(org_id: str) -> int:
    """People of the firm's own roles in the organisation, plus invitations still open (clients of the portal do not count)."""
    from lib.db import db
    from lib.legal_store import now
    from lib.rbac import ROLES

    people = await db.users.count_documents({"organization_id": org_id, "role": {"$in": list(ROLES)}})
    pending = await db.invites.count_documents({"organization_id": org_id, "accepted_at": None, "expires_at": {"$gt": now()}, "role": {"$in": list(ROLES)}})
    return people + pending


async def require_room_for_member(org_id: str, user: dict, extra: int = 1, pending_counted: bool = False) -> None:
    """Refuse (402) when the organisation's plan allows no more people. `pending_counted` = the invitation being accepted is already one of the open invitations."""
    limit = plan_config.plan(tier_of(user))["members_max"]
    if limit is None:
        return
    used = await members_in_use(org_id) - (1 if pending_counted else 0)
    if used + extra > limit:
        raise HTTPException(status_code=402, detail=f"Your plan allows {limit} people in the organisation, and {used} are already in it or invited. Ask VIDHI about a larger plan, or remove someone first.")


# The bucket the current request was charged to (one value per request, because each request runs in its own task), so a refund goes back to exactly that bucket, once.
_CHARGED: ContextVar[str | None] = ContextVar("vidhi_ai_charged_bucket", default=None)


async def refund_ai(user: dict) -> None:
    """The AI service failed, so the person did not get an answer: give the request back instead of using up one of their daily requests.
    It refunds the very bucket that was charged (even if midnight passed meanwhile or the plan changed), and only once per request."""
    from lib.ratelimit import refund_key

    key = _CHARGED.get()
    if key:
        _CHARGED.set(None)
        await refund_key(key)


async def gate_ai(user: dict, task: str) -> str:
    """Call before every Legal Intelligence AI request. Returns the tier to run it at, or refuses with 402."""
    from lib.aibudget import ensure_available

    from lib.rbac import can

    if not can(user, "ai"):  # every AI path (uploads that read scans and photos included) obeys the role's capability, not only the routes that list it
        raise HTTPException(status_code=403, detail="Your role in this organisation cannot use AI features. Ask an owner or admin.")
    await ensure_available(user)  # the spending caps (month, today, this person's today): a clear 503 or 429 before anything is counted against the person
    tier = tier_of(user)
    if tier == "free":
        try:  # one ceiling for the whole free plan per day, so free accounts together can never use up the month's budget that Pro customers pay for
            await hit("plan-ai-free-all", "platform", plan_config.free_platform_ai_per_day(), 86400)
        except HTTPException as exc:
            if exc.status_code != 429:
                raise
            raise HTTPException(status_code=503, detail="The free plan has reached today's shared limit. It resets tomorrow; Pro is not affected.") from exc
        if task in plan_config.plan("free")["locked_tasks"]:
            raise HTTPException(
                status_code=402,
                detail=f"This is a Pro feature: {FREE_LOCKED[task].lower()}. The free plan is for simple questions - "
                "upgrade to Pro in Settings for complex matters and the strongest models.",
            )
    elif task in plan_config.plan(tier)["locked_tasks"]:
        raise HTTPException(status_code=402, detail=f"Your plan does not include this task: {FREE_LOCKED[task].lower()}.")
    limit, scope = plan_config.plan(tier)["ai_per_day"], f"plan-ai-{tier}"
    try:
        _CHARGED.set(await hit(scope, user["organization_id"], limit, 86400))
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        raise HTTPException(
            status_code=402 if tier == "free" else 429,
            detail=(
                f"You have used today's {limit} free AI requests. They renew tomorrow, or upgrade to Pro for far more and the strongest models."
                if tier == "free"
                else "Today's fair-use allowance for AI requests has been reached. Please try again tomorrow."
            ),
        ) from exc
    return tier
