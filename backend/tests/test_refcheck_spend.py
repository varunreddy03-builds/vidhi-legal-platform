"""The daily lookup limit per organisation: atomic, per organisation, per Indian calendar day."""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from lib.refcheck import spend
from lib.refcheck.lookup import LookupCapExceeded

IST = timezone(timedelta(hours=5, minutes=30))


def with_collection(body):
    async def main():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        coll = client[os.environ["DB_NAME"]][f"t_authority_spend_{uuid.uuid4().hex[:8]}"]
        try:
            return await body(coll)
        finally:
            await coll.drop()
            client.close()

    return asyncio.run(main())


@pytest.fixture(autouse=True)
def small_cap(monkeypatch):
    monkeypatch.setenv("AUTHORITY_DAILY_LOOKUP_CAP", "5")


def test_lookups_are_counted_and_the_limit_is_exact():
    async def body(c):
        for i in range(5):
            assert await spend.reserve(c, "org-a") == i + 1
        with pytest.raises(LookupCapExceeded):
            await spend.reserve(c, "org-a")
        assert await spend.used_today(c, "org-a") == 5  # the refused one was not counted

    with_collection(body)


def test_one_organisation_does_not_use_up_another_ones_allowance():
    async def body(c):
        for _ in range(5):
            await spend.reserve(c, "org-a")
        assert await spend.reserve(c, "org-b") == 1

    with_collection(body)


def test_the_limit_starts_again_on_the_next_indian_day():
    async def body(c):
        late = datetime(2026, 10, 26, 23, 0, tzinfo=IST)
        for _ in range(5):
            await spend.reserve(c, "org-a", now=late)
        with pytest.raises(LookupCapExceeded):
            await spend.reserve(c, "org-a", now=late)
        assert await spend.reserve(c, "org-a", now=late + timedelta(hours=2)) == 1

    with_collection(body)


def test_concurrent_checks_cannot_overshoot_the_limit():
    async def body(c):
        outcomes = await asyncio.gather(*(spend.reserve(c, "org-a") for _ in range(20)), return_exceptions=True)
        assert sum(1 for o in outcomes if isinstance(o, int)) == 5
        assert sum(1 for o in outcomes if isinstance(o, LookupCapExceeded)) == 15
        assert await spend.used_today(c, "org-a") == 5

    with_collection(body)
