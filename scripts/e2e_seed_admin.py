"""Creates the operator account used by the browser tests straight in the database (confirmed email, two-step on) and prints ONLY a fresh session token for it.
Used by frontend/e2e/legal-review.e2e.ts and pilot.e2e.ts. Test databases only: it refuses unless DB_NAME looks like a test database. Needs pymongo and the backend's own packages,
nothing else (no test framework), so it also runs in CI."""

import hashlib
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

ADMIN_EMAIL = "platform-admin-test@example.com"  # listed in PLATFORM_ADMIN_EMAILS by the browser-test configuration

if not any(w in os.environ.get("DB_NAME", "") for w in ("e2e", "test")):
    sys.exit("Refusing to seed an operator account: DB_NAME is not a test database.")

from pymongo import MongoClient  # noqa: E402

from lib.auth import hash_password  # noqa: E402

db = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[os.environ["DB_NAME"]]
now = datetime.now(timezone.utc)
org_id = str(uuid.uuid4())
db.users.update_one({"email": ADMIN_EMAIL}, {"$setOnInsert": {
    "id": str(uuid.uuid4()), "email": ADMIN_EMAIL, "full_name": "Platform Admin", "password_hash": hash_password(secrets.token_urlsafe(24)), "role": "OWNER",
    "organization_id": org_id, "organization_name": "Operator", "plan": "PRO", "email_verified": True, "created_at": now,
    "two_factor": {"enabled": True, "secret": "unused-in-tests", "last_step": 0, "recovery": []}}}, upsert=True)
row = db.users.find_one({"email": ADMIN_EMAIL})
db.organizations.update_one({"id": row["organization_id"]}, {"$setOnInsert": {"id": row["organization_id"], "name": "Operator", "created_at": now}}, upsert=True)
token = secrets.token_urlsafe(32)
db.sessions.insert_one({"id": str(uuid.uuid4()), "token_hash": hashlib.sha256(token.encode()).hexdigest(), "user_id": row["id"], "created_at": now, "expires_at": now + timedelta(days=1)})
print(token)
