"""A canary check on the real server's own log: client words go through many features, including failing ones, and none of them may appear in the log afterwards.
The log is the file the test server writes to (VIDHI_SERVER_LOG, set by scripts/test-backend.ps1 and .sh); without it the test is skipped. Invented words only."""

import os
import uuid
from pathlib import Path

import httpx
import pytest

from tests.conftest import API_URL, answer, new_matter, stub, upload

LOG = os.environ.get("VIDHI_SERVER_LOG", "")
pytestmark = pytest.mark.skipif(not LOG or not Path(LOG).exists(), reason="the test server's log file is not available here")

TAG = uuid.uuid4().hex[:8]
NAME = f"Zorblax{TAG} Quillington"  # a client's name
WORDS = f"quillington{TAG}"  # what to search for (lower case)
OWES = f"owes Rs 7,31,{int(TAG, 16) % 900 + 100} to the landlord"
EMAIL_LOCAL = f"zq.{TAG}"


def log_size() -> int:
    return Path(LOG).stat().st_size


def log_since(offset: int) -> str:
    with open(LOG, "rb") as f:
        f.seek(offset)
        return f.read().decode("utf-8", errors="replace").replace("\x00", "")


def test_client_words_do_not_reach_the_server_log_through_normal_and_failing_paths(user_a):
    start = log_size()
    # a matter, a document, and AI features that work and that fail, all carrying the client's name
    mid, title = new_matter(user_a, f"{NAME} v State")
    upload(user_a, mid, f"{WORDS}-notes.txt", f"{NAME} {OWES} to the landlord. {title}")
    bad = user_a.post(f"/matters/{mid}/documents", files={"file": (f"{WORDS}.exe", b"MZ not a document")})  # a refused file with the name in it
    assert bad.status_code >= 400
    stub("research", answer(f"{NAME} {OWES}."), contains=title)
    assert user_a.post("/research", json={"question": f"What does {NAME} owe? {title}", "matter_id": mid, "mode": "MATTER"}).status_code == 200
    stub("research", "__FAIL__", contains=title)
    assert user_a.post("/research", json={"question": f"Again, {NAME}? {title}", "matter_id": mid, "mode": "MATTER"}).status_code >= 400  # the model fails
    assert user_a.post("/research", json={"question": f"No scripted reply for {NAME} {title}", "matter_id": mid, "mode": "MATTER"}).status_code >= 400  # nothing scripted
    user_a.post(f"/matters/{mid}/synthesize")
    user_a.post("/evidence/classify", json={"text": f"{NAME} {OWES}"})
    # messages and requests that carry the name
    user_a.post("/privacy/requests", json={"kind": "ACCESS", "details": f"Please send everything about {NAME}"})
    # sign-in paths with the person's email: wrong password, duplicate sign-up, reset, an invitation, a bad invitation token
    with httpx.Client(base_url=API_URL, timeout=30.0) as anon:
        email = f"{EMAIL_LOCAL}@example.com"
        sign = {"email": email, "password": f"Pw-{uuid.uuid4().hex}", "full_name": NAME, "organization_name": f"{NAME} Associates", "accept_privacy": True}
        assert anon.post("/auth/signup", json=sign).status_code == 200
        assert anon.post("/auth/signup", json=sign).status_code >= 400  # the same email twice: a duplicate-key error inside
        anon.post("/auth/login", json={"email": email, "password": "wrong-password-for-the-canary"})
        anon.post("/auth/forgot-password", json={"email": email})
        anon.post("/auth/accept-invite", json={"token": WORDS, "full_name": NAME, "password": "x" * 12, "accept_privacy": True})
    user_a.post("/org/invites", json={"email": f"{EMAIL_LOCAL}.invitee@example.com", "role": "LAWYER"})
    # a request the validator refuses, with the name in the body
    assert user_a.post("/matters", json={"title": NAME, "parties": 12345, "unknown": [NAME]}).status_code in (200, 422)
    user_a.get("/org/export")

    seen = log_since(start)
    assert "vidhi.access" in seen and len(seen) > 500, "the log did not grow, so this check proved nothing"
    lowered = seen.lower()
    assert WORDS not in lowered and "quillington" not in lowered and EMAIL_LOCAL not in lowered, "a client's words reached the server log"
    assert OWES.lower() not in lowered
