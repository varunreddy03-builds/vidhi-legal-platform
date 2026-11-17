import asyncio
import time
import uuid
from datetime import timezone
from contextlib import asynccontextmanager
from fastapi import APIRouter, Depends, FastAPI
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import re
import logging
from pathlib import Path


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Error tracking: on only when SENTRY_DSN is set (messages are scrubbed; see lib/monitoring.py)
from lib.monitoring import init_sentry  # noqa: E402

init_sentry()

# MongoDB connection
from lib.db import client, db, ensure_indexes


# Startup runs before the yield, shutdown after it. Add your own setup/teardown here.
@asynccontextmanager
async def lifespan(app: FastAPI):
    from lib.library import sync_library
    from lib import migrations, startup_check
    from lib.stand_ins import refuse_on_live_site

    refuse_on_live_site()
    startup_check.enforce()
    await migrations.run_on_start()
    app.state.index_task = asyncio.create_task(ensure_indexes())
    app.state.warm_task = asyncio.create_task(authority_router.warm_case_source())  # the case dataset index loads in the background; startup does not wait for it
    try:
        logger.info("verified law library: %s", await sync_library())
    except Exception:  # noqa: BLE001 - a library problem must not stop the app; claims just stay unverified
        logger.exception("verified law library failed to load")
    try:
        from lib.hc_judgments import sync_judgments

        logger.info("high court judgments: %s", await sync_judgments())
    except Exception:  # noqa: BLE001 - a lookup aid: never stops the app
        logger.exception("high court judgments failed to load")  # background: a big index build must not block boot
    yield
    client.close()


# Interactive API docs are off unless explicitly enabled (ENABLE_DOCS=true) - never in production.
_docs_on = os.environ.get('ENABLE_DOCS', 'false').lower() == 'true'
app = FastAPI(
    lifespan=lifespan,
    docs_url='/docs' if _docs_on else None,
    redoc_url=None,
    openapi_url='/openapi.json' if _docs_on else None,
)

# Every API route passes through the role policy in lib/rbac.py (public routes are listed there explicitly).
from lib.auth import enforce_policy  # noqa: E402

api_router = APIRouter(prefix="/api", dependencies=[Depends(enforce_policy)])


@api_router.get("/health")
async def health():
    return {"status": "ok"}


JOB_MAX_AGE_HOURS = {"recovery-reminders": 36, "scheduled-statements": 36, "retention": 36, "upload-expiry": 36, "deadline-reminders": 3, "jobs": 3}


@api_router.get("/health/ready")
async def ready():
    """For uptime monitors: 503 if the database does not answer; "degraded" if a scheduled job is overdue or failing."""
    from fastapi.responses import JSONResponse

    from lib.auth import now

    try:
        await client.admin.command("ping")
    except Exception:  # noqa: BLE001
        logger.exception("readiness: database ping failed")
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    problems = []
    for name, max_hours in JOB_MAX_AGE_HOURS.items():
        if name in ("recovery-reminders", "scheduled-statements") and not recovery_mode.enabled():
            continue  # these two belong to Legal Recovery: while it is switched off they are not run, and not running is not a fault
        row = await db.job_runs.find_one({"_id": name})
        if not row:
            continue  # never run yet (fresh deploy): not a fault
        ok, bad = row.get("last_ok_at"), row.get("last_failed_at")
        ok = ok.replace(tzinfo=timezone.utc) if ok and ok.tzinfo is None else ok
        bad = bad.replace(tzinfo=timezone.utc) if bad and bad.tzinfo is None else bad
        if bad and (not ok or bad > ok):
            problems.append({"job": name, "problem": "last run failed"})
        elif ok and (now() - ok).total_seconds() > max_hours * 3600:
            problems.append({"job": name, "problem": "overdue"})
    return {"status": "degraded" if problems else "ok", "database": "up", "jobs": problems}

from fastapi import Depends  # noqa: E402

from lib.auth import current_user  # noqa: E402
from lib.origins import allowed_origins, has_wildcard  # noqa: E402
from lib.native_bridge import native_token_bridge  # noqa: E402
from lib.ratelimit import SEARCH_LIMIT  # noqa: E402
from routers import admin as admin_router  # noqa: E402
from routers import auth as auth_router  # noqa: E402
from routers import cron as cron_router  # noqa: E402
from routers import deadlines as deadlines_router  # noqa: E402
from routers import clients as clients_router  # noqa: E402
from routers import templates as templates_router  # noqa: E402
from routers import draft_review as draft_review_router  # noqa: E402
from routers import authority as authority_router  # noqa: E402
from routers import katalyst_addin as katalyst_addin_router  # noqa: E402
from routers import datelist as datelist_router  # noqa: E402
from routers import defectcheck as defectcheck_router  # noqa: E402
from routers import oldcodecheck as oldcodecheck_router  # noqa: E402
from routers import deadlinerules as deadlinerules_router  # noqa: E402
from routers import portal as portal_router  # noqa: E402
from routers import conflicts as conflicts_router  # noqa: E402
from routers import directory as directory_router  # noqa: E402
from routers import demo as demo_router  # noqa: E402
from routers import knowledge as knowledge_router  # noqa: E402
from routers import analysis as analysis_router  # noqa: E402
from routers import legal as legal_router  # noqa: E402
from routers import legal_links as legal_links_router  # noqa: E402
from routers import documents as documents_router  # noqa: E402
from routers import evidence as evidence_router  # noqa: E402
from routers import images as images_router  # noqa: E402
from routers import library as library_router  # noqa: E402
from routers import judgments as judgments_router  # noqa: E402
from routers import legal_directory as legal_directory_router  # noqa: E402
from routers import matters as matters_router  # noqa: E402
from routers import org as org_router  # noqa: E402
from routers import org_data as org_data_router  # noqa: E402
from routers import payments as payments_router  # noqa: E402
from lib import recovery_mode  # noqa: E402
from routers import recovery as recovery_router  # noqa: E402
from routers import recovery_mail as recovery_mail_router  # noqa: E402
from routers import recovery_intake as recovery_intake_router  # noqa: E402
from routers import recovery_notice as recovery_notice_router  # noqa: E402
from routers import recovery_delivery as recovery_delivery_router  # noqa: E402
from routers import recovery_translation as recovery_translation_router  # noqa: E402
from routers import team as team_router  # noqa: E402
from routers import support as support_router  # noqa: E402
from routers import twofactor as twofactor_router  # noqa: E402
from routers import decide as decide_router  # noqa: E402
from routers import phone as phone_router  # noqa: E402
from routers import privacy as privacy_router  # noqa: E402
from routers import pilot_feedback as pilot_feedback_router  # noqa: E402
from routers import voice as voice_router  # noqa: E402
from routers import research as research_router  # noqa: E402


@api_router.get("/search", dependencies=[Depends(SEARCH_LIMIT)])
async def universal_search(q: str = "", user: dict = Depends(current_user)):
    """Tenant-scoped search across matters, documents, research and drafts."""
    term = q.strip()[:100]
    if len(term) < 2:
        return {"query": term, "groups": []}
    # Escape: the user's text is a literal search string, never a regex (avoids errors and regex DoS).
    rx = {"$regex": re.escape(term), "$options": "i"}
    org = user["organization_id"]
    groups = []
    matters = await db.matters.find(
        {"organization_id": org, "$or": [{"title": rx}, {"description": rx}, {"parties": rx}]}
    ).to_list(20)
    groups.append(
        {
            "type": "Matters",
            "items": [{"id": m["id"], "label": m["title"], "href": f"/matters/{m['id']}"} for m in matters],
        }
    )
    docs = await db.documents.find({"organization_id": org, "filename": rx}).to_list(20)
    groups.append(
        {
            "type": "Documents",
            "items": [
                {"id": d["id"], "label": d["filename"], "href": f"/matters/{d['matter_id']}?tab=documents"}
                for d in docs
            ],
        }
    )
    res = await db.research_results.find({"organization_id": org, "question": rx}).to_list(20)
    groups.append(
        {
            "type": "Research",
            "items": [{"id": r["id"], "label": r["question"], "href": "/research"} for r in res],
        }
    )
    drafts = await db.drafts.find({"organization_id": org, "$or": [{"title": rx}, {"body": rx}]}).to_list(20)
    groups.append(
        {
            "type": "Drafts",
            "items": [{"id": x["id"], "label": x["title"], "href": f"/drafts/{x['id']}"} for x in drafts],
        }
    )
    if recovery_mode.enabled():  # Legal Recovery is hidden while switched off: its cases and papers are not offered in search
        cases = await db.recovery_cases.find(
            {
                "organization_id": org,
                "$or": [{"creditor_name": rx}, {"debtor_name": rx}, {"description": rx}, {"intake.invoice_number": rx}, {"intake.supply_description": rx}],
            }
        ).to_list(20)
        groups.insert(
            0,
            {
                "type": "Money recoveries",
                "items": [{"id": c["id"], "label": f"{c['creditor_name']} → {c['debtor_name']}", "href": f"/recovery/cases/{c['id']}"} for c in cases],
            },
        )
        proofs = await db.recovery_proofs.find({"organization_id": org, "filename": rx}).to_list(20)
        groups.append(
            {
                "type": "Papers in recoveries",
                "items": [{"id": x["id"], "label": x["filename"], "href": f"/recovery/cases/{x['case_id']}"} for x in proofs],
            }
        )
    return {"query": term, "groups": [g for g in groups if g["items"]]}


api_router.include_router(auth_router.router)
api_router.include_router(twofactor_router.router)
api_router.include_router(admin_router.router)
api_router.include_router(support_router.router)
api_router.include_router(deadlines_router.router)
api_router.include_router(templates_router.router)
api_router.include_router(draft_review_router.router)
api_router.include_router(authority_router.router)
api_router.include_router(katalyst_addin_router.router)
api_router.include_router(clients_router.router)
api_router.include_router(datelist_router.router)
api_router.include_router(defectcheck_router.router)
api_router.include_router(oldcodecheck_router.router)
api_router.include_router(deadlinerules_router.router)
api_router.include_router(portal_router.router)
api_router.include_router(conflicts_router.router)
api_router.include_router(directory_router.router)
api_router.include_router(demo_router.router)
api_router.include_router(knowledge_router.router)
api_router.include_router(analysis_router.router)
api_router.include_router(legal_router.router)
api_router.include_router(legal_links_router.router)
api_router.include_router(voice_router.router)
api_router.include_router(phone_router.router)
api_router.include_router(privacy_router.router)
api_router.include_router(pilot_feedback_router.router)
api_router.include_router(decide_router.router)
api_router.include_router(images_router.router)
api_router.include_router(phone_router.public)
api_router.include_router(matters_router.router)
api_router.include_router(documents_router.router)
api_router.include_router(evidence_router.router)
api_router.include_router(library_router.router)
api_router.include_router(judgments_router.router)
api_router.include_router(legal_directory_router.router)
api_router.include_router(research_router.router)
_RECOVERY_ON = [Depends(recovery_mode.require_enabled)]  # every Legal Recovery route answers 404 while RECOVERY_ENABLED is off
api_router.include_router(recovery_router.router, dependencies=_RECOVERY_ON)
api_router.include_router(recovery_intake_router.router, dependencies=_RECOVERY_ON)
api_router.include_router(recovery_notice_router.router, dependencies=_RECOVERY_ON)
api_router.include_router(recovery_delivery_router.router, dependencies=_RECOVERY_ON)
api_router.include_router(recovery_translation_router.router, dependencies=_RECOVERY_ON)
api_router.include_router(recovery_mail_router.router, dependencies=_RECOVERY_ON)
api_router.include_router(recovery_mail_router.public)  # the two consent routes carry the switch themselves; the e-mail delivery webhooks serve every kind of e-mail and stay
api_router.include_router(payments_router.router)
api_router.include_router(cron_router.router)
api_router.include_router(org_router.router)
api_router.include_router(org_data_router.router)
api_router.include_router(team_router.router)

# Include the router in the main app
app.include_router(api_router)

_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
access_log = logging.getLogger("vidhi.access")


@app.middleware("http")
async def request_context(request, call_next):
    """Give every request an id, log one line per request WITHOUT personal data, and turn crashes into a clean 500."""
    from fastapi.responses import JSONResponse

    from lib.auth import route_template

    rid = request.headers.get("x-request-id", "")
    rid = rid if _REQUEST_ID.match(rid) else uuid.uuid4().hex
    request.state.request_id = rid
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001 - last line of defence; details go to the log, never to the client
        import sys

        from lib.monitoring import error_label, where

        exc = sys.exc_info()[1]
        # the kind of error and where in our code it happened; never its message or traceback text (a database or validation message can repeat a value from the request)
        access_log.error("unhandled error rid=%s %s %s %s at %s", rid, request.method, route_template(request), error_label(exc), where(exc))
        response = JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong on our side. If it keeps happening, quote this reference when you contact us.", "reference": rid},
        )
    response.headers["X-Request-ID"] = rid
    # route TEMPLATE, never the raw path or query string: those can hold tokens, ids and search terms
    elapsed_ms = (time.perf_counter() - started) * 1000
    access_log.info("rid=%s method=%s route=%s status=%s ms=%d", rid, request.method, route_template(request), response.status_code, elapsed_ms)
    from lib import product_stats

    await product_stats.record(request.method, route_template(request), response.status_code, elapsed_ms)  # anonymous counters per tool (lib/product_stats.py); never raises
    return response


app.middleware("http")(native_token_bridge)  # the Android app signs in with a bearer token instead of cookies (lib/native_bridge.py)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
    # The API returns JSON/PDF/images only: nothing here should ever execute or be framed.
    if request.url.path not in ("/docs", "/openapi.json"):
        h.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")  # authenticated data must not sit in shared caches
    if os.environ.get("COOKIE_SECURE", "true").lower() != "false":
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Credentialed CORS only for explicitly listed origins (CORS_ORIGINS + APP_URL); "*" is ignored.
if has_wildcard():
    logger.warning("CORS_ORIGINS contains '*': ignoring it - list your real origins explicitly.")
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization", "X-VIDHI-App"],
    expose_headers=["X-VIDHI-Token"],
)
