"""Knowledge library routes. The operator's routes (catalogue, rights, ingestion) are admin-only under /api/admin/knowledge; any signed-in user can search the library plus their own
organisation's private documents. See lib/knowledge.py for the rules; nothing here makes text available that a person has not recorded rights for and approved."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from lib import knowledge
from lib.auth import audit, current_user
from lib.platform import require_platform_admin
from lib.ratelimit import user_limit

router = APIRouter(tags=["knowledge"])
# Added to the admin router (routers/admin.py) by extending its routes, so the guard is repeated here, as for the legal routes.
admin_router = APIRouter(prefix="/admin/knowledge", tags=["admin", "knowledge"], dependencies=[Depends(require_platform_admin)])


def _http(exc: Exception) -> HTTPException:
    code = 404 if isinstance(exc, LookupError) else 409 if isinstance(exc, PermissionError) else 422
    return HTTPException(status_code=code, detail=str(exc).strip("'\""))


class StatusIn(BaseModel):
    status: str = Field(max_length=60)
    evidence: str = Field(max_length=2000)
    approval: str = Field(default="", max_length=1000)


class RightsIn(BaseModel):
    terms_quote: str = Field(max_length=4000)
    permitted: list[str] = Field(default_factory=list, max_length=10)
    source_url: str = Field(max_length=1000)
    edition: str = Field(max_length=300)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=5_000_000)
    complete: bool = False  # true only if this is the whole work


class PrivateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=300_000)


@admin_router.post("/import-registry")
async def import_registry(admin: dict = Depends(require_platform_admin)):
    out = await knowledge.import_registry()
    await audit(admin, "KNOWLEDGE_REGISTRY_IMPORT", detail=f"added={out['added']}")
    return out


@admin_router.get("/dashboard")
async def dashboard():
    return await knowledge.dashboard()


@admin_router.get("/works")
async def works():
    from lib.db import db

    return [knowledge._public(w) async for w in db.knowledge_works.find({"scope": {"$ne": "org"}}).sort("number", 1)]


@admin_router.post("/works/{number}/rights")
async def rights(number: Annotated[int, Path(ge=-10**10, le=10**10)], body: RightsIn, admin: dict = Depends(require_platform_admin)):
    try:
        w = await knowledge.record_rights(number, body.terms_quote, body.permitted, body.source_url, body.edition)
    except (ValueError, LookupError) as exc:
        raise _http(exc) from exc
    await audit(admin, "KNOWLEDGE_RIGHTS", detail=str(number))
    return w


@admin_router.post("/works/{number}/status")
async def status(number: Annotated[int, Path(ge=-10**10, le=10**10)], body: StatusIn, admin: dict = Depends(require_platform_admin)):
    try:
        w = await knowledge.set_status(number, body.status, body.evidence, body.approval)
    except (ValueError, LookupError) as exc:
        raise _http(exc) from exc
    await audit(admin, "KNOWLEDGE_STATUS", detail=f"{number} -> {body.status}")
    return w


@admin_router.post("/works/{number}/text")
async def ingest(number: Annotated[int, Path(ge=-10**10, le=10**10)], body: TextIn, admin: dict = Depends(require_platform_admin)):
    try:
        out = await knowledge.ingest_text(number, body.text, body.complete)
    except (ValueError, LookupError, PermissionError) as exc:
        raise _http(exc) from exc
    await audit(admin, "KNOWLEDGE_INGEST", detail=f"{number} chunks+={out['chunks_added']}")
    return out


@router.get("/knowledge/search", dependencies=[Depends(user_limit("knowledge-search", 300, 3600))])
async def search(q: str = Query("", max_length=300), collection: str | None = Query(None, max_length=40), k: int = Query(8, ge=1, le=20),
                 script: str | None = Query(None, max_length=20, pattern=r"^[a-z_]+$"), kind: str | None = Query(None, max_length=20, pattern=r"^[a-z_]+$"), user: dict = Depends(current_user)):
    try:
        return await knowledge.search(q, user["organization_id"], k=k, collection=collection, script=script, kind=kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/knowledge/private")
async def private_list(user: dict = Depends(current_user)):
    return await knowledge.list_private(user["organization_id"])


@router.post("/knowledge/private", dependencies=[Depends(user_limit("knowledge-private", 60, 3600))])
async def private_add(body: PrivateIn, user: dict = Depends(current_user)):
    try:
        out = await knowledge.add_private_text(user["organization_id"], body.title, body.text)
    except ValueError as exc:
        raise _http(exc) from exc
    await audit(user, "KNOWLEDGE_PRIVATE_ADD", detail=str(out["work_number"]))
    return out


@router.delete("/knowledge/private/{number}", dependencies=[Depends(user_limit("knowledge-private-delete", 120, 3600))])
async def private_delete(number: Annotated[int, Path(ge=-10**10, le=10**10)], user: dict = Depends(current_user)):
    try:
        await knowledge.delete_private(user["organization_id"], number)
    except LookupError as exc:
        raise _http(exc) from exc
    await audit(user, "KNOWLEDGE_PRIVATE_DELETE", detail=str(number))
    return {"ok": True}

@router.get("/knowledge/domains")
async def domains(user: dict = Depends(current_user)):
    return await knowledge.domains()


@router.get("/knowledge/films")
async def film_catalogue(user: dict = Depends(current_user)):
    from lib import films

    return films.catalogue()


@router.get("/knowledge/films/exercises")
async def film_exercises(user: dict = Depends(current_user)):
    from lib import films

    return films.exercises()
