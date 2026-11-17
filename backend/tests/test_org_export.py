"""The organisation export must hold everything the organisation owns, and a new collection must not be forgotten. Invented text only."""

import io
import json
import uuid
import zipfile

from lib import purge
from routers import org_data
from tests.conftest import mongo


def test_every_collection_that_erasure_deletes_is_exported_or_excluded_with_a_reason():
    tagged = set(purge.ORG_TAGGED) | set(purge.MATTER_COLLECTIONS) | {"matters", "recovery_cases", "notice_versions", "notice_translations", "case_correspondence", "generated_images"}
    covered = set(org_data.EXPORT_COLLECTIONS) | set(org_data.EXPORT_EXCLUDED)
    assert tagged <= covered, f"not exported and not excluded: {sorted(tagged - covered)}"
    assert all(len(reason) > 20 for reason in org_data.EXPORT_EXCLUDED.values())
    assert not set(org_data.EXPORT_COLLECTIONS) & set(org_data.EXPORT_EXCLUDED)


def test_the_export_contains_the_rows_of_every_exported_collection(user_a):
    org_id = user_a.get("/auth/me").json()["organization_id"]
    marker = f"export-marker-{uuid.uuid4().hex[:8]}"
    db = mongo()
    wanted = ["deadlines", "portal_shares", "portal_updates", "authority_reports", "date_lists", "defect_checks", "old_code_checks", "support_tickets", "data_requests", "booking_requests", "directory_profiles"]
    try:
        for coll in wanted:
            db[coll].insert_one({"id": f"{marker}-{coll}", "organization_id": org_id, "note": marker})
        db.knowledge_works.insert_one({"id": f"{marker}-kw", "org_id": org_id, "title": marker})
        r = user_a.get("/org/export")
        assert r.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(z.namelist())
        for coll in org_data.EXPORT_COLLECTIONS:
            assert f"{coll}.json" in names, coll
        for coll in wanted:
            rows = json.loads(z.read(f"{coll}.json"))
            assert any(row.get("note") == marker for row in rows), f"{coll} rows are missing from the export"
        assert any(row.get("title") == marker for row in json.loads(z.read("knowledge_works.json")))
    finally:
        for coll in wanted:
            db[coll].delete_many({"note": marker})
        db.knowledge_works.delete_many({"title": marker})


def test_the_export_holds_no_secret_in_any_collection_even_after_an_invitation_and_a_sign_in(user_a):
    """Security audit SA9: an invitation keeps a hash of its link token and members keep a password hash and two-step data; none of them may leave in the export, under any collection."""
    import re

    from tests.conftest import verify_email

    verify_email(user_a)  # inviting someone emails a third party, which needs a confirmed address
    email = f"export-secret-{uuid.uuid4().hex[:8]}@example.com"
    assert user_a.post("/org/invites", json={"email": email, "role": "LAWYER"}).status_code == 200
    assert mongo().invites.find_one({"email": email}, {"token_hash": 1})["token_hash"]  # it is stored, so the export must be the thing that leaves it out
    r = user_a.get("/org/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    secret_key = re.compile(r'"(?:password_hash|token_hash|two_factor|two_factor_pending|phone_pending|google_sub|email_verification|logo_b64)"\s*:')
    for name in z.namelist():
        if name.endswith(".json"):
            assert not secret_key.search(z.read(name).decode("utf-8")), f"{name} leaks a secret field"
    assert any(row["email"] == email for row in json.loads(z.read("invites.json")))  # the invitation itself is there, without its hash
    mongo().invites.delete_many({"email": email})
