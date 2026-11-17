"""Removes the invented Acts a browser test loaded, so they do not stay in the shared browser-test database and match other tests' searches.

    python scripts/e2e_cleanup_legal.py <text that appears in the test's source, document and Act names>

Test databases only (DB_NAME must contain 'e2e' or 'test'). It deletes only records whose source name, document title or Act title contains the given text, and the records hanging off
them. It prints how many it removed."""

import os
import re
import sys

from pymongo import MongoClient

if len(sys.argv) != 2 or len(sys.argv[1]) < 6:
    sys.exit("Give a distinctive piece of text (at least 6 characters) that identifies this test's data.")
needle = re.escape(sys.argv[1])
name = os.environ.get("DB_NAME", "")
if not any(w in name for w in ("e2e", "test")):
    sys.exit("Refusing: DB_NAME is not a test database.")
db = MongoClient(os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))[name]
rx = {"$regex": needle}

sources = [s["id"] for s in db.legal_sources.find({"name": rx}, {"id": 1})]
docs = [d["id"] for d in db.legal_documents.find({"$or": [{"title": rx}, {"source_id": {"$in": sources}}]}, {"id": 1})]
insts = [i["id"] for i in db.instruments.find({"title": rx}, {"id": 1})]
versions = [v["id"] for v in db.instrument_versions.find({"$or": [{"instrument_id": {"$in": insts}}, {"document_id": {"$in": docs}}]}, {"id": 1})]
provs = [p["id"] for p in db.provisions.find({"$or": [{"instrument_version_id": {"$in": versions}}, {"instrument_id": {"$in": insts}}]}, {"id": 1})]
removed = {
    "provision_chunks": db.provision_chunks.delete_many({"parent_id": {"$in": provs}}).deleted_count,
    "provisions": db.provisions.delete_many({"id": {"$in": provs}}).deleted_count,
    "instrument_versions": db.instrument_versions.delete_many({"id": {"$in": versions}}).deleted_count,
    "instruments": db.instruments.delete_many({"id": {"$in": insts}}).deleted_count,
    "legal_documents": db.legal_documents.delete_many({"id": {"$in": docs}}).deleted_count,
    "legal_sources": db.legal_sources.delete_many({"id": {"$in": sources}}).deleted_count,
}
removed["provision_refs"] = db.provision_refs.delete_many({"from_version_id": {"$in": versions}}).deleted_count  # cross-reference edges built at ingestion (lib/legal_graph.py)
print(removed)
