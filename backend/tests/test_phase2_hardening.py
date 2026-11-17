"""Phase 2 hardening: payment session records are unique, AI paths obey the role capability, voice needs the `ai` capability."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException

from lib import plans
from lib.rbac import POLICY, required_cap
from tests.conftest import mongo

LOOP = asyncio.new_event_loop()


def test_voice_routes_need_the_ai_capability():
    assert required_cap("POST", "/api/voice/transcribe") == "ai"
    assert required_cap("POST", "/api/voice/speak") == "ai"
    assert required_cap("GET", "/api/voice/status") == "read"


def test_a_role_without_ai_cannot_pass_the_plan_gate_even_on_a_route_that_does_not_list_it():
    member = {"id": "u", "organization_id": "o", "role": "MEMBER"}
    with pytest.raises(HTTPException) as e:
        LOOP.run_until_complete(plans.gate_ai(member, "ocr"))
    assert e.value.status_code == 403 and "AI" in e.value.detail


def test_two_payment_records_cannot_share_a_checkout_session():
    from pymongo.errors import DuplicateKeyError

    db = mongo()
    sid = f"cs_test_{uuid.uuid4().hex}"
    db.payment_transactions.insert_one({"session_id": sid, "payment_status": "initiated"})
    try:
        with pytest.raises(DuplicateKeyError):
            db.payment_transactions.insert_one({"session_id": sid, "payment_status": "initiated"})
    finally:
        db.payment_transactions.delete_many({"session_id": sid})
