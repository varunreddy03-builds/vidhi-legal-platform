"""The operator's weekly view (Admin console > This week): what the owner needs to look at once a week, in one call.

  AI cost by day, AI errors, reports that a result was wrong, progress of the law library review, and the pilot accounts.

Numbers and names of organisations only. Nothing here returns a prompt, an answer, a document, a question, or the text of anyone's comment. The same guard as every admin route
applies (it is added to the admin router in routers/admin.py). Days are Indian days (Asia/Kolkata), the same as the AI spending caps."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from lib import verified_store as vstore
from lib.db import db
from lib.platform import require_platform_admin

admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])  # the same guard as every admin route, declared here too: routes added to another router do not inherit its guard
IST = timezone(timedelta(hours=5, minutes=30))
WEEK = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%Y-%m-%d")


async def ai_cost_by_day(days: int) -> list[dict]:
    """One row for each of the last `days` days, newest first, including days with no calls (a quiet day is information too)."""
    since = _now() - timedelta(days=days)
    rows = await db.ai_ledger.aggregate([
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at", "timezone": "+05:30"}}, "provider": "$provider", "ok": {"$ne": ["$ok", False]}},
                    "calls": {"$sum": 1}, "cost": {"$sum": {"$ifNull": ["$cost_inr", 0]}}}},
    ]).to_list(5000)
    by_day: dict[str, dict] = {}
    for r in rows:
        d = by_day.setdefault(r["_id"]["day"], {"calls": 0, "failed": 0, "cost_inr": 0.0, "by_provider": {}})
        d["calls"] += r["calls"]
        if not r["_id"]["ok"]:
            d["failed"] += r["calls"]
        d["cost_inr"] += r["cost"]
        d["by_provider"][r["_id"]["provider"]] = round(d["by_provider"].get(r["_id"]["provider"], 0.0) + r["cost"], 2)
    out = []
    for i in range(days):
        key = _day(_now() - timedelta(days=i))
        d = by_day.get(key, {"calls": 0, "failed": 0, "cost_inr": 0.0, "by_provider": {}})
        out.append({"day": key, "calls": d["calls"], "failed": d["failed"], "cost_inr": round(d["cost_inr"], 2), "by_provider": d["by_provider"]})
    return out


async def ai_errors(since: datetime) -> dict:
    """Failed AI calls since `since`: how many, and which provider and which error class (the class only, never the provider's message)."""
    rows = await db.ai_ledger.aggregate([
        {"$match": {"created_at": {"$gte": since}, "ok": False}},
        {"$group": {"_id": {"provider": "$provider", "error": {"$ifNull": ["$error", "unknown"]}, "task": "$task"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}, {"$limit": 20},
    ]).to_list(20)
    total = await db.ai_ledger.count_documents({"created_at": {"$gte": since}, "ok": False})
    calls = await db.ai_ledger.count_documents({"created_at": {"$gte": since}})
    return {"failed": total, "calls": calls, "failure_rate_pct": round(100 * total / calls, 1) if calls else 0.0,
            "top": [{"provider": r["_id"]["provider"], "task": r["_id"]["task"], "error": r["_id"]["error"], "count": r["count"]} for r in rows]}


async def wrong_result_reports(since: datetime) -> dict:
    """How many times a lawyer marked an answer down or a result wrong. Counts only: the comments belong to the lawyer and stay on the pilot tab (pilot organisations only)."""
    down_all = await db.answer_feedback.count_documents({"rating": "down", "created_at": {"$gte": since}})
    up_all = await db.answer_feedback.count_documents({"rating": "up", "created_at": {"$gte": since}})
    wrong = await db.pilot_feedback.count_documents({"kind": "wrong_result", "created_at": {"$gte": since}})
    by_kind = await db.pilot_feedback.aggregate([
        {"$match": {"kind": "wrong_result", "created_at": {"$gte": since}}}, {"$group": {"_id": {"$ifNull": ["$ref_kind", "unknown"]}, "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 10},
    ]).to_list(10)
    return {"answers_marked_down": down_all, "answers_marked_up": up_all, "results_marked_wrong": wrong, "wrong_by_kind": [{"kind": r["_id"], "count": r["count"]} for r in by_kind],
            "all_time": {"answers_marked_down": await db.answer_feedback.count_documents({"rating": "down"}), "results_marked_wrong": await db.pilot_feedback.count_documents({"kind": "wrong_result"})}}


async def library_review(since: datetime) -> dict:
    """Progress of the law library review: sections compared with the official text by a named person, rejected, and still waiting; and what is waiting in the candidate queue."""
    total = await vstore.count("provisions")
    reviewed = await vstore.count("provisions", {"review_status": "reviewed"})
    rejected = await vstore.count("provisions", {"review_status": "rejected"})
    since_day = _day(since)
    recent = await vstore.count("provisions", {"review_status": {"$in": ["reviewed", "rejected"]}, "reviewed_on": {"$gte": since_day}})
    return {"sections_total": total, "reviewed": reviewed, "rejected": rejected, "waiting": max(total - reviewed - rejected, 0),
            "reviewed_percent": round(100 * reviewed / total, 1) if total else 0.0, "reviewed_or_rejected_last_7_days": recent,
            "library_entries_verified": await vstore.count("library_entries"), "candidates_waiting": await vstore.count("legal_source_candidates")}


async def pilot_accounts(since: datetime) -> list[dict]:
    """Each pilot organisation: when it started, who is in it, how much it has used and when it was last seen. Names and counts; never what is in their matters."""
    out = []
    async for org in db.organizations.find({"pilot": True}, {"_id": 0, "id": 1, "name": 1, "created_at": 1}).sort("created_at", -1).limit(50):
        oid = org["id"]
        last = await db.audit_events.find({"organization_id": oid}, {"_id": 0, "created_at": 1}).sort("created_at", -1).limit(1).to_list(1)
        ai = await db.ai_ledger.aggregate([{"$match": {"organization_id": oid, "created_at": {"$gte": since}}}, {"$group": {"_id": None, "calls": {"$sum": 1}, "cost": {"$sum": {"$ifNull": ["$cost_inr", 0]}}}}]).to_list(1)
        out.append({"organisation": org["name"], "started": org.get("created_at"), "members": await db.users.count_documents({"organization_id": oid}),
                    "matters": await db.matters.count_documents({"organization_id": oid}), "last_seen": last[0]["created_at"] if last else None,
                    "ai_calls_7d": ai[0]["calls"] if ai else 0, "ai_cost_7d_inr": round(ai[0]["cost"], 2) if ai else 0.0,
                    "marked_down_7d": await db.answer_feedback.count_documents({"organization_id": oid, "rating": "down", "created_at": {"$gte": since}})})
    return out


@admin_router.get("/weekly")
async def weekly(days: int = Query(14, ge=1, le=60)):
    since = _now() - WEEK
    return {"generated_at": _now(), "days": days, "ai_cost_by_day": await ai_cost_by_day(days), "ai_errors_7d": await ai_errors(since), "wrong_results_7d": await wrong_result_reports(since),
            "library_review": await library_review(since), "pilot_accounts": await pilot_accounts(since)}
