"""Sharing a matter's graph with a client: only a filtered snapshot, only what comes from documents already shared, never the firm's own reading of the matter."""

import uuid

from lib.graph_share import filter_graph
from tests.conftest import mongo, upload
from tests.test_portal import SECRET, firm, make_client, matter_with_secret  # noqa: F401  (fixtures and helpers)


def N(i, t, label="x", sub=None):
    return {"id": i, "label": label, "node_type": t, "sublabel": sub}


def E(a, b, r):
    return {"source": a, "target": b, "relation": r}


def test_the_filter_keeps_only_what_comes_from_shared_documents():
    nodes = [N("m", "MATTER", "Matter"), N("d1", "DOCUMENT", "shared.pdf", "CONTRACT"), N("d2", "DOCUMENT", "secret.pdf"), N("p1", "PERSON", "Asha", "adverse party"), N("p2", "PERSON", "Only in secret"),
             N("e1", "EVENT", "2026-01-01 filed"), N("e2", "EVENT", "2026-02-02 internal"), N("f1", "FACT", "our weak point"), N("c1", "CLAIM", "a claim"), N("ev", "EVIDENCE", "exhibit")]
    edges = [E("d1", "m", "PART_OF"), E("d2", "m", "PART_OF"), E("d1", "p1", "MENTIONS"), E("d2", "p2", "MENTIONS"), E("e1", "d1", "DERIVED_FROM"), E("e2", "d2", "DERIVED_FROM"),
             E("d1", "d2", "CONTRADICTS"), E("f1", "m", "PART_OF"), E("d1", "f1", "EVIDENCES"), E("c1", "m", "PART_OF"), E("ev", "d1", "DERIVED_FROM")]
    g = filter_graph(nodes, edges, "m", {"d1"})
    assert {n["id"] for n in g["nodes"]} == {"m", "d1", "p1", "e1"}
    assert {(e["source"], e["target"], e["relation"]) for e in g["edges"]} == {("d1", "m", "PART_OF"), ("d1", "p1", "MENTIONS"), ("e1", "d1", "DERIVED_FROM")}
    assert next(n for n in g["nodes"] if n["id"] == "p1")["sublabel"] is None  # no role or status labels
    assert filter_graph(nodes, edges, "m", set())["nodes"] == [N("m", "MATTER", "Matter")] and filter_graph(nodes, edges, "m", set())["edges"] == []
    assert filter_graph(nodes, edges, "m", {"p1", "f1"})["nodes"] == [N("m", "MATTER", "Matter")]  # a shared id that is not a document brings nothing in


def test_a_client_sees_only_the_published_snapshot_and_nothing_internal(firm):  # noqa: F811
    mid, title = matter_with_secret(firm)
    client = make_client(firm, mid)
    shared = upload(firm, mid, f"letter-{uuid.uuid4().hex[:6]}.txt", f"Dear client {uuid.uuid4().hex}")
    hidden = upload(firm, mid, f"internal-{uuid.uuid4().hex[:6]}.txt", f"Internal {uuid.uuid4().hex}")
    org = firm.user["organization_id"]
    db = mongo()
    db.entities.insert_one({"id": str(uuid.uuid4()), "matter_id": mid, "organization_id": org, "name": "Shared Person", "role": "adverse party", "appearances": [{"document_id": shared["id"]}]})
    db.entities.insert_one({"id": str(uuid.uuid4()), "matter_id": mid, "organization_id": org, "name": "Hidden Person", "role": "x", "appearances": [{"document_id": hidden["id"]}]})
    db.facts.insert_one({"id": str(uuid.uuid4()), "matter_id": mid, "organization_id": org, "value": SECRET, "status": "DISPUTED", "document_id": shared["id"]})
    assert firm.post(f"/matters/{mid}/portal/documents", json={"document_id": shared["id"]}).status_code == 200

    assert client.get(f"/portal/matters/{mid}/graph").json() == {"graph": None}  # nothing published yet
    pre = firm.get(f"/matters/{mid}/portal/graph").json()
    names = {n["label"] for n in pre["preview"]["nodes"]}
    assert title in names and shared["filename"] in names and "Shared Person" in names
    assert hidden["filename"] not in names and "Hidden Person" not in names and SECRET[:20] not in str(pre["preview"]) and pre["shared"] is None
    assert firm.put(f"/matters/{mid}/portal/graph").status_code == 200

    got = client.get(f"/portal/matters/{mid}/graph").json()["graph"]
    text = str(got)
    assert shared["filename"] in text and "Shared Person" in text
    assert hidden["filename"] not in text and "Hidden Person" not in text and SECRET[:20] not in text and "adverse party" not in text and "FACT" not in text and "CONTRADICTS" not in text
    assert any(e["operation"] == "PORTAL_GRAPH_VIEWED" and e["user_id"] == client.user["id"] for e in db.audit_events.find({"matter_id": mid}))

    # a snapshot does not change when the matter does; sharing another document does not reach the client until the lawyer republishes
    assert firm.post(f"/matters/{mid}/portal/documents", json={"document_id": hidden["id"]}).status_code == 200
    assert hidden["filename"] not in str(client.get(f"/portal/matters/{mid}/graph").json())
    assert firm.put(f"/matters/{mid}/portal/graph").status_code == 200
    assert hidden["filename"] in str(client.get(f"/portal/matters/{mid}/graph").json())

    assert firm.delete(f"/matters/{mid}/portal/graph").json() == {"withdrawn": 1}
    assert client.get(f"/portal/matters/{mid}/graph").json() == {"graph": None}


def test_only_people_who_may_share_can_publish_and_another_firm_sees_nothing(firm, user_b):  # noqa: F811
    mid, _ = matter_with_secret(firm)
    client = make_client(firm, mid)
    assert client.get(f"/matters/{mid}/portal/graph").status_code == 403 and client.put(f"/matters/{mid}/portal/graph").status_code == 403  # a client holds no firm capability
    assert user_b.get(f"/matters/{mid}/portal/graph").status_code in (403, 404) and user_b.put(f"/matters/{mid}/portal/graph").status_code in (403, 404)
    assert user_b.delete(f"/matters/{mid}/portal/graph").status_code in (403, 404)
    other, _ = matter_with_secret(firm, "Other")
    assert client.get(f"/portal/matters/{other}/graph").status_code == 404  # a matter not shared with this client


def test_the_snapshot_goes_when_its_matter_is_deleted(firm):  # noqa: F811
    mid, _ = matter_with_secret(firm)
    make_client(firm, mid)
    assert firm.put(f"/matters/{mid}/portal/graph").status_code == 200
    assert mongo().portal_graphs.count_documents({"matter_id": mid}) == 1
    assert firm.delete(f"/matters/{mid}").status_code in (200, 204)
    assert mongo().portal_graphs.count_documents({"matter_id": mid}) == 0
