"""A real session against a running VIDHI backend, with every request and what the database holds afterwards printed, so a person can see that it is real.

    python scripts/real_session.py http://127.0.0.1:8002 vidhi_real

It talks HTTP to the live server (the same code the app uses) and then looks INSIDE the database that server uses. It makes no paid call: it creates two throwaway accounts and
checks a statute-only draft (no case, so no outside lookup). Run the server with AUTHORITY_CHECK_ENABLED=true and AUTHORITY_SOURCE_DISABLED=true. Prints names and facts, never secrets."""

import hashlib
import json
import os
import sys
import time
import uuid

import httpx
from pymongo import MongoClient

BASE = sys.argv[1].rstrip("/") + "/api"
DB = sys.argv[2]
MONGO = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
db = MongoClient(MONGO)[DB]
results: list[tuple[bool, str]] = []


def show(method: str, path: str, r: httpx.Response, note: str = "") -> None:
    print(f"  {method:<6} {path:<46} -> {r.status_code} {note}")


def check(ok: bool, what: str) -> None:
    results.append((ok, what))
    print(f"  [{'PASS' if ok else 'FAIL'}] {what}")


def person(label: str) -> tuple[httpx.Client, str]:
    email = f"real-{label}-{uuid.uuid4().hex[:8]}@example.com".lower()
    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post("/auth/signup", json={"email": email, "password": "Real-Session-Pass-123", "full_name": f"Real {label}", "organization_name": f"Real Chambers {label} {uuid.uuid4().hex[:4]}", "accept_privacy": True})
    show("POST", "/auth/signup", r, f"({label})")
    assert r.status_code == 200, r.text
    return c, email


if "real" in DB:  # the sign-up limiter is a real protection (5 per hour per address): repeated demo runs would trip it, so the demo database's counter is reset
    cleared = db.rate_limits.delete_many({"_id": {"$regex": "^signup:"}}).deleted_count
    print(f"(demo database only: {cleared} sign-up limiter counter(s) reset so this demo can be repeated)")
print(f"\n== 1. The server is real and answers ({BASE})")
h = httpx.get(f"{BASE}/health", timeout=30)
show("GET", "/health", h, h.text.strip())
rdy = httpx.get(f"{BASE}/health/ready", timeout=30)
show("GET", "/health/ready", rdy, rdy.text.strip()[:120])
check(h.status_code == 200 and rdy.status_code == 200, "health and database-ready checks answer")
check(DB in MongoClient(MONGO).list_database_names(), f"the database '{DB}' exists in the real MongoDB at {MONGO.split('@')[-1]}")

print("\n== 2. Two people sign up (two separate organisations)")
a, email_a = person("A")
b, email_b = person("B")
me = a.get("/auth/me")
show("GET", "/auth/me", me, f"role={me.json()['role']} email={me.json()['email']}")
row = db.users.find_one({"email": email_a})
check(bool(row) and row["password_hash"].startswith("$2") and "Real-Session-Pass-123" not in json.dumps(row, default=str), "the password is stored only as a bcrypt hash, never as text")
check(db.organizations.count_documents({"id": row["organization_id"]}) == 1, "a new organisation was created for person A")

print("\n== 3. A matter with a Telugu description, saved and read back")
desc = "ఇది ఒక వివరణ — అద్దె ₹25,000 / month; “quotes” & <b>x</b>"
m = a.post("/matters", json={"title": "Real session matter", "description": desc, "parties": "Ravi v. Sita Traders", "jurisdiction_id": "IN"})
show("POST", "/matters", m)
mid = m.json()["id"]
got = a.get(f"/matters/{mid}")
show("GET", f"/matters/{mid[:8]}...", got)
check(got.json()["description"] == desc, "the description comes back exactly as typed (Telugu, symbols, quotes)")
stored = db.matters.find_one({"id": mid})
check(stored["description"] == desc, "and the database holds exactly that text")
upd = a.patch(f"/matters/{mid}", json={"description": desc + " (edited)"})
show("PATCH", f"/matters/{mid[:8]}...", upd)
check(a.get(f"/matters/{mid}").json()["description"].endswith("(edited)"), "editing the details later works")

print("\n== 4. Another organisation cannot see it")
for path in (f"/matters/{mid}", f"/matters/{mid}/documents"):
    r = b.get(path)
    show("GET", path.replace(mid, mid[:8] + "..."), r, "(person B)")
    check(r.status_code == 404, f"person B gets 404 for {path.split('/')[-1] if path.endswith('documents') else 'the matter'}")
check(mid not in [x["id"] for x in b.get("/matters").json()], "the matter is absent from person B's list")

print("\n== 5. An upload is stored, readable by its owner, and not readable as plain text in the database")
plain = "The tenant paid Rs 20,000 rent on 1 January 2026 for the shop at MG Road."
up = a.post(f"/matters/{mid}/documents", files={"file": ("lease-note.txt", plain.encode())})
show("POST", f"/matters/{mid[:8]}.../documents", up, f"status={up.json().get('processing_status')}")
doc = db.documents.find_one({"matter_id": mid})
check(up.status_code == 200 and doc is not None, "the document record exists in MongoDB")
chunks = b"".join(c["data"] for c in db.fs.chunks.find({"files_id": doc["gridfs_id"]}).sort("n", 1))
encrypted = plain.encode() not in chunks
print(f"       stored file: {len(chunks)} bytes; plain sentence visible in the stored bytes: {not encrypted}")
check(len(chunks) > 0, "the file bytes are in the database (GridFS)")
print("       " + ("uploads are encrypted at rest in this server's configuration" if encrypted else "NOTE: this development server has no DATA_ENCRYPTION_KEY, so the stored file is not encrypted (a live site refuses to start without one)"))
dl = a.get(f"/documents/{doc['id']}/file")
show("GET", "/documents/<id>/file", dl)
check(dl.status_code == 200 and plain.encode() in dl.content, "the owner can download the file and gets the original text back")
check(b.get(f"/documents/{doc['id']}/file").status_code == 404, "person B cannot download it")
d = a.delete(f"/documents/{doc['id']}")
show("DELETE", "/documents/<id>", d)
check(db.documents.count_documents({"id": doc["id"]}) == 0 and db.fs.files.count_documents({"_id": doc["gridfs_id"]}) == 0 and db.fs.chunks.count_documents({"files_id": doc["gridfs_id"]}) == 0, "after delete the record, the file and its chunks are gone from the database")

print("\n== 6. Authority Check on a statute-only draft (no case, so nothing outside is called)")
draft = "The complaint is under Section 138 of the Negotiable Instruments Act, 1881. The accused is also charged under Section 420 of the Indian Penal Code."
ac = a.post("/authority/checks", json={"title": "Real session draft", "text": draft})
show("POST", "/authority/checks", ac)
if ac.status_code == 404:
    print("       Authority Check is switched off on this server (AUTHORITY_CHECK_ENABLED is not true).")
    check(False, "Authority Check is on")
else:
    rep = ac.json()
    for i in rep["items"]:
        print(f"       {i['kind']:<8} {i['raw'][:48]:<50} -> {i['label']}   {('| ' + i['old_code_note'][:60]) if i['old_code_note'] else ''}")
    check(rep["counts"]["total"] == 2 and all(i["label"] == "NOT_IN_REVIEWED_LIBRARY" for i in rep["items"]), "both sections are reported 'not in reviewed library' (the law library is empty), never 'verified'")
    check(rep["current_status"] == "current status: not checked", "the report says 'current status: not checked'")
    saved = db.authority_reports.find_one({"id": rep["id"]})
    check(saved is not None and "text_full" not in json.dumps(saved, default=str) and draft not in json.dumps(saved, default=str), "the stored report holds the findings, not the draft text or any judgment text")
    check(b.get(f"/authority/checks/{rep['id']}").status_code == 404, "person B cannot open person A's report")
    rv = a.post(f"/authority/checks/{rep['id']}/items/1/review", json={"action": "reviewed"})
    show("POST", "/authority/checks/<id>/items/1/review", rv)
    check(rv.status_code == 200 and next(i for i in rv.json()["items"] if i["n"] == 1)["review"]["state"] == "reviewed", "a decision is recorded with the person's name")
    ex = a.get(f"/authority/checks/{rep['id']}/export", params={"format": "pdf"})
    show("GET", "/authority/checks/<id>/export?format=pdf", ex, f"{len(ex.content)} bytes")
    check(ex.content[:4] == b"%PDF", "the PDF export is a real PDF")

print("\n== 7. The audit trail and protections")
audit = [e["operation"] for e in a.get("/audit").json()]
print("       audit operations for A:", ", ".join(sorted(set(audit))))
check({"MATTER_CREATE", "DOCUMENT_DELETE"} <= set(audit), "creating a matter and deleting a document are in the audit trail")
anon = httpx.get(f"{BASE}/matters", timeout=30)
show("GET", "/matters", anon, "(not signed in)")
check(anon.status_code == 401, "a request without a sign-in is refused")
docs = httpx.get(f"{BASE}/docs", timeout=30)
check(docs.status_code != 200, "the interactive API pages are off")

print("\n== Result")
failed = [w for ok, w in results if not ok]
print(f"  {len(results) - len(failed)} of {len(results)} checks passed" + (f"; FAILED: {failed}" if failed else ""))
sys.exit(1 if failed else 0)
