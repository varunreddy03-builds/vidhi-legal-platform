"""Adds one invented court to the test database's judgment list and prints its name, so the browser test of the deadline-data screen has a court to match a calendar to.
    python scripts/e2e_seed_court.py <tag>
Test databases only: it refuses unless DB_NAME looks like a test database."""

import os
import sys

if not any(w in os.environ.get("DB_NAME", "") for w in ("e2e", "test")):
    sys.exit("Refusing to seed a court: DB_NAME is not a test database.")
if len(sys.argv) != 2 or not sys.argv[1].isalnum():
    sys.exit("usage: e2e_seed_court.py <alphanumeric tag>")

from pymongo import MongoClient  # noqa: E402

tag = sys.argv[1]
name = f"Invented High Court of Testland {tag}"
db = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[os.environ["DB_NAME"]]
db.hc_judgments.update_one({"id": f"e2e-court-{tag}"}, {"$set": {"id": f"e2e-court-{tag}", "court_code": f"TL{tag}", "court_name": name}}, upsert=True)
print(name)
