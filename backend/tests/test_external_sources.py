"""External legal sources: the honest registry, the refusal of non-public records, and the free help referrals."""

import pytest

from lib import external_sources as ext
from tests.test_admin import admin  # noqa: F401  (fixture)


# ---- what may be loaded ----
@pytest.mark.parametrize("kind", ["deposition", "witness_statement", "cross-examination", "Cross Examination", "transcript", "raw case file", "sealed", "in_camera", "juvenile",
                                  "witness protection", "chargesheet", "privileged", "strategy", "confidential"])
def test_non_public_records_are_always_refused(kind):
    ok, why = ext.ingest_allowed(kind)
    assert not ok and "never loaded" in why


@pytest.mark.parametrize("kind", ["act", "rule", "notification", "gazette", "order", "judgment", "bill", "report", "constitution", "amendment", "Act", " JUDGMENT "])
def test_published_legal_texts_are_allowed(kind):
    assert ext.ingest_allowed(kind) == (True, "")


@pytest.mark.parametrize("kind", [None, "", "misc", "video", "anything else"])
def test_an_unknown_kind_is_refused_rather_than_guessed(kind):
    ok, why = ext.ingest_allowed(kind)
    assert not ok and "Say which kind" in why


# ---- the registry never claims more than is true ----
def test_every_service_that_was_asked_about_is_listed_with_a_status():
    names = " ".join(e["name"] for e in ext.registry()).lower()
    for needle in ("indian kanoon", "ecourts", "njdg", "claw", "vlex", "india code", "legislative", "supreme court", "e-scr", "law commission", "sansad", "nalsa", "tele-law", "consumer helpline", "ministry of law"):
        assert needle in names or needle.replace("-", " ") in names, needle


def test_nothing_is_marked_live_tested_and_no_service_is_marked_connected():
    for e in ext.registry():
        assert e["live_tested"] is False
        assert e["status"] in {"CLIENT_BUILT_OFF", "MANUAL_INGEST", "LINK_OUT", "NOT_INTEGRATED"}
        assert e["blocked_by"].strip()


def test_the_registry_never_contains_a_token(monkeypatch):
    monkeypatch.setenv("INDIANKANOON_API_TOKEN", "super-secret-token-value")
    blob = str(ext.registry())
    assert "super-secret-token-value" not in blob
    assert next(e for e in ext.registry() if e["id"] == "indiankanoon")["configured"] is False  # nothing reads that token any more


def test_referrals_are_names_and_purpose_only():
    ids = {r["id"] for r in ext.referrals()}
    assert ids == {"nalsa", "tele_law", "nch"}
    assert all(set(r) == {"id", "name", "gives", "note"} for r in ext.referrals())


# ---- the routes ----
def test_the_registry_and_search_routes_are_for_the_platform_operator_only(user_a, admin):  # noqa: F811
    refused = user_a.get("/admin/overview").status_code  # however the project hides admin routes from ordinary users
    assert refused in (401, 403, 404)
    assert user_a.get("/admin/legal/external-sources").status_code == refused
    r = admin.get("/admin/legal/external-sources")
    assert r.status_code == 200 and "never loaded" in r.json()["policy"] and len(r.json()["sources"]) >= 15


def test_a_source_that_offers_depositions_cannot_be_registered(admin):  # noqa: F811
    body = {"name": "Some court archive", "publisher": "Example", "document_types": ["judgment", "deposition"], "access_method": "manual-supplied"}
    r = admin.post("/admin/legal/sources", json=body)
    assert r.status_code == 422 and "never loaded" in r.json()["detail"]


def test_a_document_of_a_refused_kind_cannot_be_loaded(admin):  # noqa: F811
    ok = admin.post("/admin/legal/sources", json={"name": "Fictional Gazette", "publisher": "Example", "document_types": ["act"], "access_method": "manual-supplied"})
    assert ok.status_code == 201, ok.text
    bad = admin.post("/admin/legal/documents", json={"source_id": ok.json()["id"], "title": "Witness statement PW-3", "document_kind": "witness_statement", "pages": ["text"]})
    assert bad.status_code == 422 and "never loaded" in bad.json()["detail"]


def test_any_signed_in_user_can_see_the_free_help_services(user_a):
    r = user_a.get("/legal/resources")
    assert r.status_code == 200 and {x["id"] for x in r.json()["resources"]} == {"nalsa", "tele_law", "nch"} and "decide" in r.json()["note"]
