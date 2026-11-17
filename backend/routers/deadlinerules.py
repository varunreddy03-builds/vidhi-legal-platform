"""Deadline engine: works out a due date from a rule that a person entered and a named reviewer marked reviewed. The code contains no law; see lib/deadlinerules/.
Off by default (DEADLINE_ENGINE_ENABLED=false). No AI, no outside service, no cost. A calculation is not stored; it is written to the audit log.
The admin routes (add and review rules and calendars) are mounted under /api/admin/legal and need the platform-admin guard."""

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from lib.auth import audit, current_user
from lib.deadlinerules import compute, loader, store
from lib.platform import require_platform_admin
from lib.ratelimit import user_limit

router = APIRouter(tags=["deadlinerules"])
# Its routes are added to the admin router (routers/admin.py). Routes added that way do NOT inherit that router's guard, so this router carries the same guard itself.
admin_router = APIRouter(prefix="/admin/legal", tags=["admin", "legal"], dependencies=[Depends(require_platform_admin)])


def enabled() -> bool:
    return os.environ.get("DEADLINE_ENGINE_ENABLED", "false").lower() == "true"


def _on(user: dict = Depends(current_user)) -> dict:
    if not enabled():
        raise HTTPException(status_code=404, detail="The deadline engine is not switched on.")
    return user


class CalculateIn(BaseModel):
    rule_id: str = Field(min_length=1, max_length=64)
    start: str = Field(max_length=20)  # an empty date reaches the engine, which answers in plain words


@router.get("/deadline-rules")
async def list_reviewed_rules(user: dict = Depends(_on)):
    rules = await store.list_rules(reviewed_only=True)
    return {"rules": rules, "message": None if rules else store.NONE_LOADED}


@router.post("/deadline-rules/calculate", dependencies=[Depends(user_limit("deadline-calc", 120, 3600))])
async def calculate(body: CalculateIn, user: dict = Depends(_on)):
    try:
        out = await store.calculate(body.rule_id, body.start)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except compute.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit(user, "DEADLINE_ENGINE_CALCULATED", detail=f"{body.rule_id} {out['due']}")
    return out


class CalendarIn(BaseModel):
    title: str = Field(max_length=200)
    weekend_days: list[int] = Field(default_factory=list, max_length=7)
    holidays: list[dict] = Field(default_factory=list, max_length=store.MAX_HOLIDAYS)
    authorities: list[str] = Field(default_factory=list, max_length=10)


class RuleIn(BaseModel):
    title: str = Field(max_length=200)
    starts_from: str = Field(max_length=200)
    period: dict
    count_from: str | None = None
    month_end: str | None = None
    when_not_working: str | None = None
    calendar_id: str | None = Field(default=None, max_length=64)
    not_applied: list[str] = Field(default_factory=list, max_length=10)
    authorities: list[str] = Field(default_factory=list, max_length=10)


class ReviewIn(BaseModel):
    reviewed_by: str = Field(max_length=120)
    on: str = Field(max_length=20)


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail=str(exc))


@admin_router.get("/deadline-rules")
async def admin_rules():
    return await store.list_rules(reviewed_only=False)


@admin_router.post("/deadline-rules", status_code=201)
async def add_rule(body: RuleIn, admin: dict = Depends(require_platform_admin)):
    try:
        r = await store.create_rule(body.model_dump(), admin["email"])
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "DEADLINE_RULE_ADDED", detail=r["id"])
    return r


@admin_router.post("/deadline-rules/{rule_id}/review")
async def review_rule(rule_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        r = await store.review_rule(rule_id, body.reviewed_by, body.on)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "DEADLINE_RULE_REVIEWED", detail=f"{rule_id} {body.reviewed_by[:60]}")
    return r


MAX_UPLOAD = 1_000_000


async def _file(upload: UploadFile) -> bytes:
    raw = await upload.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="The file is larger than 1 MB.")
    return raw


@admin_router.post("/deadline-data/preview")
async def preview_file(file: UploadFile = File(...), admin: dict = Depends(require_platform_admin)):
    """Checks a holiday-calendar or deadline-rules file and says what loading it would do. Stores nothing."""
    out = await loader.load(await _file(file), file.filename or "file", admin["email"], dry_run=True)
    await audit(admin, "DEADLINE_DATA_PREVIEWED", detail=(file.filename or "file")[:80])
    return out


@admin_router.post("/deadline-data/load")
async def load_file(file: UploadFile = File(...), admin: dict = Depends(require_platform_admin)):
    """Stores the file's calendar or rules as UNREVIEWED records under a new batch id. A file with any problem is refused as a whole."""
    out = await loader.load(await _file(file), file.filename or "file", admin["email"])
    await audit(admin, "DEADLINE_DATA_LOADED" if out["ok"] else "DEADLINE_DATA_REFUSED", detail=f"{(file.filename or 'file')[:80]} {out.get('batch_id') or ''}")
    if not out["ok"]:
        raise HTTPException(status_code=422, detail=" ".join(out["problems"]))
    return out


class RollbackIn(BaseModel):
    reason: str = Field(min_length=10, max_length=300)


@admin_router.post("/deadline-data/batches/{batch_id}/rollback")
async def rollback_batch(batch_id: str, body: RollbackIn, admin: dict = Depends(require_platform_admin)):
    out = await loader.rollback(batch_id, admin["email"], body.reason)
    await audit(admin, "DEADLINE_DATA_ROLLED_BACK", detail=f"{batch_id} deleted {out['deleted']} withdrawn {out['withdrawn']}")
    return out


@admin_router.get("/deadline-data/coverage")
async def deadline_coverage():
    return await loader.coverage()


@admin_router.post("/deadline-calendars/{cal_id}/enable")
async def enable_calendar(cal_id: str, admin: dict = Depends(require_platform_admin)):
    try:
        out = await loader.set_enabled(cal_id, True)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "DEADLINE_CALENDAR_ENABLED", detail=cal_id)
    return out


@admin_router.post("/deadline-calendars/{cal_id}/disable")
async def disable_calendar(cal_id: str, admin: dict = Depends(require_platform_admin)):
    try:
        out = await loader.set_enabled(cal_id, False)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "DEADLINE_CALENDAR_DISABLED", detail=cal_id)
    return out


@admin_router.get("/deadline-calendars")
async def admin_calendars():
    return await store.list_calendars()


@admin_router.post("/deadline-calendars", status_code=201)
async def add_calendar(body: CalendarIn, admin: dict = Depends(require_platform_admin)):
    try:
        c = await store.create_calendar(body.model_dump(), admin["email"])
    except (ValueError, compute.RuleError) as exc:
        raise _bad(exc) from exc
    await audit(admin, "DEADLINE_CALENDAR_ADDED", detail=c["id"])
    return c


@admin_router.post("/deadline-calendars/{cal_id}/review")
async def review_calendar(cal_id: str, body: ReviewIn, admin: dict = Depends(require_platform_admin)):
    try:
        c = await store.review_calendar(cal_id, body.reviewed_by, body.on)
    except ValueError as exc:
        raise _bad(exc) from exc
    await audit(admin, "DEADLINE_CALENDAR_REVIEWED", detail=f"{cal_id} {body.reviewed_by[:60]}")
    return c
