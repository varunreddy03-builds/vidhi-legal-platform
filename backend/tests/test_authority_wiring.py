"""The research route must take a citation's authority from the library entry's kind. (test_authority_level.py checks the rule; this checks the route uses it, so putting a fixed
"PRIMARY" back in routers/research.py fails a test.)"""

import asyncio

import pytest

from routers import research

TEXT = "the court held that a borrower must return the widget within thirty days of the demand"


def entry(kind):
    return {"id": f"e-{kind}", "citation": f"Sample {kind}", "kind": kind, "text_norm": TEXT}


@pytest.mark.parametrize("kind,level,has_note", [("STATUTE_SECTION", "PRIMARY", False), ("RULE", "PRIMARY", False), ("CASE", "UNKNOWN", True), ("OTHER", "UNKNOWN", True)])
def test_the_route_takes_authority_from_the_entry_kind(monkeypatch, kind, level, has_note):
    async def fake_resolve(ref):
        return entry(kind)

    monkeypatch.setattr(research, "resolve", fake_resolve)
    cit, ok, _, _ = asyncio.run(research._library_citation({"ref": "x", "quote": "must return the widget within thirty days"}))
    assert ok and cit.authority_level == level and bool(cit.authority_note) is has_note
