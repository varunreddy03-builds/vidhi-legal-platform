"""Shared Mongo handle — import `client`/`db` from here (server.py, routers, seed.py)."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from lib import fieldcrypt

load_dotenv(Path(__file__).parent.parent / ".env")

_missing = [k for k in ("MONGO_URL", "DB_NAME") if not os.environ.get(k)]
if _missing:
    raise RuntimeError(f"Missing setting(s): {', '.join(_missing)}. Put them in backend/.env (see .env.example) or start with scripts/dev-backend.ps1.")
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)


class _OpenPagesCursor:
    """A cursor over document rows that opens their encrypted pages as they are read. Everything else is the plain cursor."""

    def __init__(self, cursor):
        self._c = cursor

    def __getattr__(self, name):
        attr = getattr(self._c, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            out = attr(*args, **kwargs)
            return self if out is self._c else out  # sort(), limit(), skip() ... keep returning this wrapper

        return call

    async def to_list(self, length=None):
        return [fieldcrypt.open_doc(d) for d in await self._c.to_list(length)]

    def __aiter__(self):
        return self

    async def __anext__(self):
        return fieldcrypt.open_doc(await self._c.__anext__())


class EncryptedDocuments(AsyncIOMotorCollection):
    """The `documents` collection: the extracted text (`pages`) is encrypted when written and opened when read, in this one place, so no route can forget it (lib/fieldcrypt.py).
    `raw` is the same collection without that, for the migration and the tools that must see what is really stored."""

    @property
    def raw(self):
        return AsyncIOMotorCollection(self.database, self.name)

    async def find_one(self, *args, **kwargs):
        return fieldcrypt.open_doc(await super().find_one(*args, **kwargs))

    def find(self, *args, **kwargs):
        return _OpenPagesCursor(super().find(*args, **kwargs))

    async def insert_one(self, document, *args, **kwargs):
        if "pages" not in document:
            return await super().insert_one(document, *args, **kwargs)
        result = await super().insert_one({**document, "pages": fieldcrypt.seal_pages(document["pages"])}, *args, **kwargs)
        document["_id"] = result.inserted_id
        return result

    async def insert_many(self, documents, *args, **kwargs):
        return await super().insert_many([{**d, "pages": fieldcrypt.seal_pages(d["pages"])} if "pages" in d else d for d in documents], *args, **kwargs)

    @staticmethod
    def _seal_update(update):
        if isinstance(update, dict) and isinstance(update.get("$set"), dict) and "pages" in update["$set"]:
            return {**update, "$set": {**update["$set"], "pages": fieldcrypt.seal_pages(update["$set"]["pages"])}}
        return update

    async def update_one(self, flt, update, *args, **kwargs):
        return await super().update_one(flt, self._seal_update(update), *args, **kwargs)

    async def update_many(self, flt, update, *args, **kwargs):
        return await super().update_many(flt, self._seal_update(update), *args, **kwargs)


class VidhiDatabase(AsyncIOMotorDatabase):
    def __getitem__(self, name):
        return EncryptedDocuments(self, name) if name == "documents" else super().__getitem__(name)


db = VidhiDatabase(client, os.environ["DB_NAME"])

logger = logging.getLogger(__name__)

# One entry per collection: every field a route filters, sorts, or dedupes on. Applied by ensure_indexes() at startup.
INDEXES: dict[str, list[IndexModel]] = {
    "status_checks": [IndexModel([("timestamp", DESCENDING)], name="timestamp_desc")],
    "users": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("email", ASCENDING)], name="email", unique=True),
    ],
    "sessions": [
        IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0),
    ],
    "email_log": [
        IndexModel([("case_id", ASCENDING), ("created_at", DESCENDING)], name="case_created"),
        IndexModel([("provider_id", ASCENDING)], name="provider_id"),
    ],
    "email_suppressions": [IndexModel([("email", ASCENDING)], name="email", unique=True)],
    "email_confirmations": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0),
    ],
    "email_outbox": [IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=604800)],
    "legal_sources": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("keys", ASCENDING)], name="keys")],
    "library_entries": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("keys", ASCENDING)], name="keys")],
    "hc_judgments": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("court_code", ASCENDING), ("decision_date", ASCENDING)], name="court_date"),
        IndexModel([("decision_date", DESCENDING), ("id", ASCENDING)], name="newest_first"),  # the default list: without it the sort scans every record
        IndexModel([("court_code", ASCENDING), ("decision_date", DESCENDING), ("id", ASCENDING)], name="court_newest_first"),
        IndexModel([("case_title", "text"), ("text", "text")], name="judgment_text", weights={"case_title": 10, "text": 1}, default_language="english"),
    ],
    "judgment_relations": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("from_id", ASCENDING), ("relation", ASCENDING), ("quote_sha256", ASCENDING)], name="statement", unique=True),
        IndexModel([("target_id", ASCENDING)], name="target"),
        IndexModel([("status", ASCENDING), ("created_at", ASCENDING)], name="queue"),
    ],
    "legal_source_candidates": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("act_id", ASCENDING)], name="act"),
        IndexModel([("citation", "text"), ("heading", "text"), ("text", "text")], name="draft_text", weights={"citation": 10, "heading": 8, "text": 1}, default_language="english"),
    ],
    "evidence_items": [IndexModel([("matter_id", ASCENDING), ("created_at", ASCENDING)], name="matter_created"), IndexModel([("document_id", ASCENDING)], name="document")],
    "entities": [IndexModel([("matter_id", ASCENDING)], name="matter")],
    "inconsistencies": [IndexModel([("matter_id", ASCENDING)], name="matter")],
    "ai_calls": [IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=604800)],
    "ai_ledger": [IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=34560000)],  # cost records kept 400 days; no prompts or answers
    "ai_stub": [IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=604800)],
    "cron_locks": [IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0)],
    "oauth_flows": [IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0), IndexModel([("state_hash", ASCENDING)], name="state_hash", unique=True)],
    "sms_outbox": [IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=604800)],
    "google_stub": [IndexModel([("code", ASCENDING)], name="code")],
    "payment_stub": [IndexModel([("session_id", ASCENDING)], name="session")],
    "invites": [
        IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True),
        IndexModel([("organization_id", ASCENDING), ("email", ASCENDING)], name="org_email"),
        IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=2592000),
    ],
    "password_resets": [
        IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True),
        IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=86400),
    ],
    "rate_limits": [IndexModel([("expires_at", ASCENDING)], name="expires_ttl", expireAfterSeconds=0)],
    "matters": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("organization_id", ASCENDING), ("created_at", DESCENDING)], name="org_created"),
    ],
    "documents": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("matter_id", ASCENDING), ("created_at", DESCENDING)], name="matter_created"),
        IndexModel([("organization_id", ASCENDING)], name="org"),
    ],
    "facts": [IndexModel([("matter_id", ASCENDING), ("created_at", DESCENDING)], name="matter_created")],
    "timeline_events": [IndexModel([("matter_id", ASCENDING), ("event_date", ASCENDING)], name="matter_date")],
    "research_results": [
        IndexModel([("organization_id", ASCENDING), ("created_at", DESCENDING)], name="org_created"),
        IndexModel([("matter_id", ASCENDING)], name="matter"),
    ],
    "drafts": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("organization_id", ASCENDING), ("updated_at", DESCENDING)], name="org_updated"),
    ],
    "deadlines": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("organization_id", ASCENDING), ("starts_at", ASCENDING)], name="org_starts"),
        IndexModel([("status", ASCENDING), ("starts_at", ASCENDING)], name="due_scan"),
    ],
    "push_subscriptions": [IndexModel([("user_id", ASCENDING)], name="user")],
    "portal_access": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("user_id", ASCENDING), ("matter_id", ASCENDING)], name="user_matter"),
        IndexModel([("matter_id", ASCENDING)], name="matter"),
    ],
    "directory_profiles": [
        IndexModel([("user_id", ASCENDING)], name="user", unique=True),
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("listed", ASCENDING), ("display_name_sort", ASCENDING)], name="listed_name"),
    ],
    "booking_requests": [IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)], name="user_created"), IndexModel([("id", ASCENDING)], name="id", unique=True)],
    "jobs": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("state", ASCENDING), ("available_at", ASCENDING)], name="state_due"), IndexModel([("created_at", DESCENDING)], name="created")],
    "payment_transactions": [IndexModel([("session_id", ASCENDING)], name="session_unique", unique=True, partialFilterExpression={"session_id": {"$type": "string"}})],  # one record per checkout session: a replayed webhook cannot create a second
    "product_stats": [IndexModel([("day", ASCENDING), ("tool", ASCENDING)], name="day_tool", unique=True)],
    "clients": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("organization_id", ASCENDING), ("name_key", ASCENDING)], name="org_name")],
    "refunds": [IndexModel([("session_id", ASCENDING)], name="session"), IndexModel([("created_at", DESCENDING)], name="created")],
    "legal_documents": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("source_id", ASCENDING), ("sha256", ASCENDING)], name="source_hash", unique=True)],
    "instruments": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("title_norm", ASCENDING), ("jurisdiction", ASCENDING)], name="title_jur", unique=True)],
    "instrument_versions": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("instrument_id", ASCENDING), ("document_id", ASCENDING)], name="inst_doc", unique=True)],
    "provisions": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("instrument_version_id", ASCENDING), ("number_norm", ASCENDING)], name="version_number"),
        IndexModel([("heading", "text"), ("text_full", "text")], name="provision_text", default_language="none"),
    ],
    "provision_chunks": [IndexModel([("parent_id", ASCENDING), ("ordinal", ASCENDING)], name="parent_ordinal")],
    "provision_refs": [IndexModel([("from_provision_id", ASCENDING)], name="from_prov"), IndexModel([("to_provision_ids", ASCENDING)], name="to_prov"), IndexModel([("from_version_id", ASCENDING)], name="from_version")],
    "forums": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("name", ASCENDING)], name="name")],
    "decisions": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("citation_norm", ASCENDING)], name="citation", unique=True)],
    "treatments": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("to_decision_id", ASCENDING)], name="to_decision"), IndexModel([("from_decision_id", ASCENDING)], name="from_decision")],
    "code_mappings": [IndexModel([("id", ASCENDING)], name="id", unique=True), IndexModel([("legacy.provision_id", ASCENDING)], name="legacy_prov"), IndexModel([("new.provision_id", ASCENDING)], name="new_prov")],
    "addin_keys": [IndexModel([("token_hash", ASCENDING)], name="token_hash", unique=True), IndexModel([("user_id", ASCENDING)], name="user")],
    "portal_updates": [IndexModel([("matter_id", ASCENDING), ("created_at", DESCENDING)], name="matter_created")],
    "portal_shares": [IndexModel([("matter_id", ASCENDING), ("document_id", ASCENDING)], name="matter_doc", unique=True)],
    "push_outbox": [IndexModel([("created_at", ASCENDING)], name="created_ttl", expireAfterSeconds=604800)],
    "audit_events": [
        IndexModel([("organization_id", ASCENDING), ("created_at", DESCENDING)], name="org_created")
    ],
    "recovery_cases": [
        IndexModel([("id", ASCENDING)], name="id", unique=True),
        IndexModel([("organization_id", ASCENDING), ("created_at", DESCENDING)], name="org_created"),
    ],
    "notice_translations": [IndexModel([("case_id", ASCENDING), ("created_at", DESCENDING)], name="case_created")],
    "case_correspondence": [IndexModel([("case_id", ASCENDING), ("occurred_on", ASCENDING)], name="case_date")],
    "notice_versions": [
        IndexModel([("case_id", ASCENDING), ("number", DESCENDING)], name="case_number", unique=True),
        IndexModel([("id", ASCENDING)], name="id", unique=True),
    ],
    "recovery_proofs": [
        IndexModel([("case_id", ASCENDING), ("created_at", DESCENDING)], name="case_created"),
    ],
}


async def ensure_indexes() -> None:
    # Sessions used to store the raw token under a unique "token" index; new documents have no such
    # field, so that index must go first or the second login would collide on null.
    try:
        await db.sessions.drop_index("token")
    except Exception:  # noqa: BLE001 — already gone / collection not created yet
        pass
    for collection, models in INDEXES.items():
        for model in models:  # one at a time so a bad spec skips only itself
            try:
                await db[collection].create_indexes([model])
            except Exception as exc:  # never block boot on an index; the log line names what to fix
                logger.error("ensure_indexes(%s.%s): %s", collection, model.document["name"], exc)
