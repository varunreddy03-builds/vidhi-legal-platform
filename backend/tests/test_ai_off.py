"""An organisation's owner can switch AI off. Off means nothing from that organisation reaches any AI service: every AI route is refused before it sends, a person with the AI
capability included, and other organisations are not affected. Invented text only."""

import asyncio

from lib import aibudget
from tests.conftest import ai_prompts, answer, new_matter, new_member, stub


def ask(c, title, mid):
    return c.post("/research", json={"question": f"What does it say? {title}", "matter_id": mid, "mode": "MATTER"})


def test_ai_is_on_by_default_and_only_an_owner_or_admin_can_switch_it(verified_a):
    user_a = verified_a
    assert user_a.get("/org/ai").json() == {"enabled": True}
    lawyer = new_member(user_a, "LAWYER")
    assert lawyer.put("/org/ai", json={"enabled": False}).status_code == 403
    assert user_a.get("/org/ai").json() == {"enabled": True}
    assert user_a.put("/org/ai", json={"enabled": False}).json() == {"enabled": False}
    assert user_a.get("/org/ai").json() == {"enabled": False}
    user_a.put("/org/ai", json={"enabled": True})


def test_when_off_every_ai_route_refuses_before_sending_anything_and_when_on_again_it_works(verified_a, user_b):
    user_a = verified_a
    mid, title = new_matter(user_a, "Switch")
    other_mid, other_title = new_matter(user_b, "Other")
    lawyer = new_member(user_a, "LAWYER")  # has the AI capability, but the owner said no
    assert user_a.put("/org/ai", json={"enabled": False}).status_code == 200
    try:
        stub("research", answer("Reply."), contains=title)
        for c in (user_a, lawyer):
            r = ask(c, title, mid)
            assert r.status_code == 403 and "switched off for your organisation" in r.json()["detail"] and "Retry-After" not in r.headers
        assert ai_prompts(title, "research") == []  # nothing was sent to the model
        stub("research", answer("Reply."), contains=other_title)
        assert ask(user_b, other_title, other_mid).status_code == 200  # another organisation is not affected
        # the other AI-spending entry points obey the same switch
        up = user_a.post(f"/matters/{mid}/synthesize")
        assert up.status_code == 403 and ai_prompts(title, "synthesize") == []
    finally:
        user_a.put("/org/ai", json={"enabled": True})
    assert ask(user_a, title, mid).status_code == 200  # on again: the scripted reply is used


def test_the_budget_itself_refuses_a_flagged_organisation_even_when_a_route_forgot_to_check():
    class Orgs:
        async def find_one(self, flt, proj=None):
            return {"ai_enabled": False} if flt["id"] == "org-off" else {}

    class Never:  # any use of the spending records would be a failure of the test
        def __getattr__(self, name):
            raise AssertionError("the budget touched its records before refusing")

    b = aibudget.Budget(Never(), Never(), orgs=Orgs())
    aibudget._CURRENT.set(("u1", "org-off", "pro"))
    try:
        try:
            asyncio.run(b.reserve(1.0))
        except aibudget.AiSwitchedOff as exc:
            assert exc.status_code == 403 and "switched off" in exc.public_message and exc.retry_after() == 0
        else:
            raise AssertionError("reserve did not refuse")
        assert asyncio.run(b.ai_off("org-on")) is False and asyncio.run(b.ai_off(None)) is False
    finally:
        aibudget._CURRENT.set(None)
