"""E-signing is an extension point only: nothing signs or stamps, and the product never claims it does."""

import asyncio
import os
import re

import pytest

from lib import esign

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_by_default_nothing_is_available_and_every_call_says_so():
    assert esign.available() is False and esign.active().name == "none"
    req = esign.SignRequest("lease.pdf", b"%PDF", (esign.Signer("A", "a@example.com"),))
    with pytest.raises(esign.ESignNotAvailable, match="not available"):
        asyncio.run(esign.active().create_request(req))
    with pytest.raises(esign.ESignNotAvailable):
        asyncio.run(esign.active().status("x"))


def test_a_provider_can_be_added_without_changing_callers(monkeypatch):
    class Fake:
        name = "fake"

        async def create_request(self, request):
            return "req-1"

        async def status(self, request_id):
            return esign.SignStatus(request_id, "pending")

    monkeypatch.setitem(esign.PROVIDERS, "none", Fake())
    assert esign.available() is True
    assert asyncio.run(esign.active().create_request(esign.SignRequest("d", b"x", ()))) == "req-1"


def test_no_route_pretends_to_sign_and_no_template_or_page_claims_a_signature():
    """Signing must not appear anywhere user-facing until a real provider exists: search the API routes and the shipped template text."""
    from server import app

    assert not [p for p in app.openapi()["paths"] if re.search(r"esign|e-sign|signature|stamp", p, re.I)]
    for root, _, files in os.walk(os.path.join(BACKEND, "data", "templates")):
        for f in files:
            text = open(os.path.join(root, f), encoding="utf-8").read().lower()
            assert "digitally signed" not in text and "e-signed" not in text and "electronically signed" not in text and "e-stamp" not in text