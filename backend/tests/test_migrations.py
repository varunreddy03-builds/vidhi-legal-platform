"""Migrations: run once and in order, safe when several servers start together, a failure stops the line and is retried after it is fixed."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from lib import migrations as mg
from lib.db import db
from tests.inproc import run


@pytest.fixture
def coll():
    c = db[f"test_schema_migrations_{uuid.uuid4().hex[:8]}"]
    yield c
    run(c.drop())


def make(log, fail=()):
    def one(mid):
        async def fn():
            log.append(mid)
            if mid in fail:
                raise RuntimeError("boom")
        return mg.Migration(mid, f"test {mid}", fn)
    return [one("0001_a"), one("0002_b"), one("0003_c")]


def test_pending_migrations_run_once_in_order(coll):
    log = []
    ms = make(log)
    assert run(mg.run_pending(ms, coll)) == {"applied": ["0001_a", "0002_b", "0003_c"], "skipped": [], "failed": []}
    assert log == ["0001_a", "0002_b", "0003_c"]
    assert run(mg.run_pending(ms, coll)) == {"applied": [], "skipped": ["0001_a", "0002_b", "0003_c"], "failed": []}
    assert log == ["0001_a", "0002_b", "0003_c"]  # nothing ran twice
    assert [s["state"] for s in run(mg.status(ms, coll))] == ["applied"] * 3


def test_a_new_migration_added_later_runs_alone(coll):
    log = []
    ms = make(log)
    run(mg.run_pending(ms[:2], coll))
    log.clear()
    assert run(mg.run_pending(ms, coll))["applied"] == ["0003_c"] and log == ["0003_c"]


def test_a_failure_stops_the_line_is_recorded_and_retried_after_the_fix(coll):
    log = []
    broken = make(log, fail={"0002_b"})
    r = run(mg.run_pending(broken, coll))
    assert r == {"applied": ["0001_a"], "skipped": [], "failed": ["0002_b"]} and log == ["0001_a", "0002_b"]  # 0003 never ran
    st = {s["id"]: s for s in run(mg.status(broken, coll))}
    assert st["0002_b"]["state"] == "failed" and "boom" in st["0002_b"]["error"] and st["0003_c"]["state"] == "pending"
    log.clear()
    fixed = make(log)  # same ids, now working
    assert run(mg.run_pending(fixed, coll)) == {"applied": ["0002_b", "0003_c"], "skipped": ["0001_a"], "failed": []}


def test_servers_starting_together_run_each_migration_once(coll):
    log = []
    ms = make(log)

    async def both():
        return await asyncio.gather(mg.run_pending(ms, coll), mg.run_pending(ms, coll))

    run(both())
    assert sorted(log) == ["0001_a", "0002_b", "0003_c"] and len(log) == 3  # claimed by insert: no migration ran in both
    assert [s["state"] for s in run(mg.status(ms, coll))].count("applied") == 3


def test_a_migration_left_running_by_a_dead_server_is_taken_over_only_when_stale(coll):
    log = []
    ms = make(log)
    run(coll.insert_one({"_id": "0001_a", "status": "running", "started_at": datetime.now(timezone.utc)}))
    r = run(mg.run_pending(ms, coll))
    assert r["applied"] == [] and r["skipped"] == ["0001_a"] and log == []  # another server is probably running it: wait, do not race ahead
    run(coll.update_one({"_id": "0001_a"}, {"$set": {"started_at": datetime.now(timezone.utc) - timedelta(minutes=mg.STALE_MINUTES + 1)}}))
    assert run(mg.run_pending(ms, coll))["applied"] == ["0001_a", "0002_b", "0003_c"]


def test_ids_must_be_unique_and_in_order(coll):
    async def fn():
        return None

    with pytest.raises(ValueError):
        run(mg.run_pending([mg.Migration("0002_x", "x", fn), mg.Migration("0001_y", "y", fn)], coll))
    with pytest.raises(ValueError):
        run(mg.run_pending([mg.Migration("0001_x", "x", fn), mg.Migration("0001_x", "y", fn)], coll))


def test_the_shipped_list_is_valid_and_the_server_applied_the_baseline():
    ids = [m.id for m in mg.MIGRATIONS]
    assert ids == sorted(ids) and len(set(ids)) == len(ids) and ids[0] == "0001_baseline"
    from tests.conftest import mongo

    assert mongo().schema_migrations.find_one({"_id": "0001_baseline"})["status"] == "applied"
