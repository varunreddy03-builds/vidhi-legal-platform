"""What a client may see of a matter's graph.

The firm's graph (routers/matters.py) holds internal material: research claims, differences between sources, evidence labels, facts. A client must never receive it directly. A lawyer instead publishes a
SNAPSHOT made by this filter, which keeps only:
- the matter itself;
- documents the lawyer has already shared with the client (the same list the portal shows);
- people and dates that come from those shared documents (a person is kept only if a shared document mentions them; a date only if it was read from a shared document);
and only these links between kept items: part of the matter, mentions, derived from. No contradiction links, claims, sources, facts or evidence, and no role or status labels (they can be a
lawyer's own reading). A snapshot does not change when the matter does, so later work never reaches a client by accident; the lawyer republishes to update it, or withdraws it."""

KEEP_NODES = ("MATTER", "DOCUMENT", "PERSON", "EVENT")
KEEP_LINKS = ("PART_OF", "MENTIONS", "DERIVED_FROM")


def filter_graph(nodes: list[dict], edges: list[dict], matter_id: str, shared_document_ids: set[str]) -> dict:
    by_id = {n["id"]: n for n in nodes}
    keep = {matter_id} & set(by_id)
    keep |= {i for i in shared_document_ids if by_id.get(i, {}).get("node_type") == "DOCUMENT"}
    for e in edges:  # a person or a date comes in only through a shared document
        if e["relation"] == "MENTIONS" and e["source"] in keep and by_id.get(e["target"], {}).get("node_type") == "PERSON":
            keep.add(e["target"])
        if e["relation"] == "DERIVED_FROM" and e["target"] in keep and by_id.get(e["source"], {}).get("node_type") == "EVENT":
            keep.add(e["source"])
    out_nodes = [{"id": by_id[i]["id"], "label": by_id[i]["label"], "node_type": by_id[i]["node_type"], "sublabel": by_id[i].get("sublabel") if by_id[i]["node_type"] == "DOCUMENT" else None}
                 for i in keep if by_id[i]["node_type"] in KEEP_NODES]
    ids = {n["id"] for n in out_nodes}
    seen, out_edges = set(), []
    for e in edges:
        key = (e["source"], e["target"], e["relation"])
        if e["relation"] in KEEP_LINKS and e["source"] in ids and e["target"] in ids and key not in seen:
            seen.add(key)
            out_edges.append({"source": e["source"], "target": e["target"], "relation": e["relation"]})
    return {"nodes": sorted(out_nodes, key=lambda n: (n["node_type"], n["label"])), "edges": out_edges}
