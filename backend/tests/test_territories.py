"""The State/UT model: central law applies everywhere, a State law only in its own territory, and nothing about coverage is overstated."""

import uuid

from lib import territories
from tests.conftest import mongo


def test_the_registry_has_every_state_and_union_territory_and_claims_no_coverage():
    rows = territories.registry()
    kinds = [r["kind"] for r in rows]
    assert kinds.count("state") == 28 and kinds.count("union_territory") == 8 and kinds.count("country") == 1
    assert len({r["code"] for r in rows}) == len(rows)
    for r in rows:
        assert r["confirmed"] is False  # general knowledge, not yet confirmed against an official list
        if r["kind"] != "country":
            assert set(r["sources"].values()) == {"not_checked"}  # nothing has been looked at for any State or UT
    assert territories.high_court_of("IN-GA") == ["Bombay"] and territories.high_court_of("IN-TG") == ["Telangana"]


def test_every_territory_has_a_high_court_and_every_high_court_serves_known_territories():
    known = {c.removeprefix("IN-") for c in territories.all_codes() if c != "IN"}
    served = {t for ts in territories.HIGH_COURTS.values() for t in ts}
    assert served == known  # no territory is left without a High Court in the model, and none is invented


def test_applicability():
    assert territories.applies_in("IN", "IN-TG") and territories.applies_in(None, "IN-TG")
    assert territories.applies_in("IN-TG", "IN-TG") and not territories.applies_in("IN-TG", "IN-KA")
    assert territories.applies_in("IN-TG", None)  # no territory asked for: nothing is hidden
    assert territories.valid_code("IN-TG") and territories.valid_code("IN") and not territories.valid_code("IN-XX") and not territories.valid_code("UK")


def test_a_lookup_for_one_territory_does_not_show_another_states_law(user_a):
    tag = uuid.uuid4().hex[:8]
    number = f"{6000 + int(tag, 16) % 3000}ZQ"  # a provision number nothing else uses (the reader takes up to four digits and three letters)

    def seed():
        for code in ("IN", "IN-TG", "IN-KA"):
            iid, vid = f"i-{tag}-{code}", f"v-{tag}-{code}"
            mongo().instruments.insert_one({"id": iid, "title": f"Fixture Act {tag} {code}", "title_norm": f"fixture act {tag} {code}", "short_names": [], "kind": "act", "jurisdiction": code, "year": 2000})
            mongo().instrument_versions.insert_one({"id": vid, "instrument_id": iid, "document_id": f"d-{vid}", "label": "fixture", "created_at": "2000-01-01"})
            mongo().provisions.insert_one({"id": f"p-{vid}", "instrument_version_id": vid, "number": number, "number_norm": number, "kind": "section", "heading": "Fixture", "text_full": "TEST FIXTURE ONLY.", "text": "TEST FIXTURE ONLY.", "components": [{"kind": "rule", "label": "", "text": "TEST FIXTURE ONLY."}]})

    def clean():
        for coll in ("instruments", "instrument_versions", "provisions"):
            mongo()[coll].delete_many({"id": {"$regex": tag}})

    def found(**params):
        r = user_a.get("/legal/search", params={"q": f"Section {number}", **params})
        assert r.status_code == 200, r.text
        return {e["instrument"].split()[-1] for e in r.json()["exact"]}

    seed()
    try:
        everywhere, tg = found(), found(territory="IN-TG")
        bad = user_a.get("/legal/search", params={"q": "x", "territory": "IN-XX"})
    finally:
        clean()
    assert everywhere == {"IN", "IN-TG", "IN-KA"}
    assert tg == {"IN", "IN-TG"}  # Karnataka's law is not offered as the law in Telangana
    assert bad.status_code == 422  # an unknown territory is refused, not silently ignored
