"""Adds a member to an existing organisation straight in the test database (confirmed email) and prints ONLY a fresh session token for them.
    python scripts/e2e_seed_member.py <email of someone already in the organisation> <ROLE> <full name>
Used by frontend/e2e/draft-review.e2e.ts. Test databases only: it refuses unless DB_NAME looks like a test database."""

import hashlib
import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

if not any(w in os.environ.get("DB_NAME", "") for w in ("e2e", "test")):
    sys.exit("Refusing to seed a member: DB_NAME is not a test database.")
if len(sys.argv) != 4 or sys.argv[2] not in ("ADMIN", "LAWYER", "MEMBER"):
    sys.exit("usage: e2e_seed_member.py <existing member email> <ADMIN|LAWYER|MEMBER> <full name>")

from pymongo import MongoClient  # noqa: E402

from lib.auth import hash_password  # noqa: E402

db = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[os.environ["DB_NAME"]]
owner = db.users.find_one({"email": sys.argv[1].lower()})
if not owner:
    sys.exit("No such user.")
now = datetime.now(timezone.utc)
email = f"seed-{sys.argv[2].lower()}-{uuid.uuid4().hex[:8]}@example.com"
user = {"id": str(uuid.uuid4()), "email": email, "full_name": sys.argv[3], "password_hash": hash_password(secrets.token_urlsafe(24)), "role": sys.argv[2],
        "organization_id": owner["organization_id"], "organization_name": owner.get("organization_name", ""), "plan": "FREE", "email_verified": True, "privacy_accepted_at": now, "created_at": now}
db.users.insert_one(user)
token = secrets.token_urlsafe(32)
db.sessions.insert_one({"id": str(uuid.uuid4()), "token_hash": hashlib.sha256(token.encode()).hexdigest(), "user_id": user["id"], "created_at": now, "expires_at": now + timedelta(days=1)})
print(token)
