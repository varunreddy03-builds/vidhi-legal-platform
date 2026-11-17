"""Background jobs (leased, retried a limited number of times, safe to repeat), scanned law PDFs, and the rule that a claim resting on an uncertain page is never VERIFIED."""

import time
import os
from datetime import datetime, timedelta, timezone

import httpx

from tests.conftest import API_URL, answer, mongo, new_matter, stub, upload
from tests.legal_fixtures import FICTIONAL_PENAL_ACT
from tests.test_admin import admin  # noqa: F401  (fixture)
from tests.test_legal_data import find, source, tag
from tests.test_ocr import scanned_pdf
from tests.test_truth_engine import claim, doc_cite, research

CRON = {"Authorization": f"Bearer {os.environ.get('WEBHOOK_CRON_SECRET', 'test-cron-secret-not-real')}"}


def marked(pages: list[str]) -> str:
    return "\n".join(f"=====PAGE {i}=====\n{p}" for i, p in enumerate(pages, 1))


def upload_scan(admin_c, src, name="scan.pdf", title="Scanned invented Act", salt=b"", content=None):
    # the PDF library stamps every file it makes with a random id, so "the same file" must be built once and sent twice
    return admin_c.post("/admin/legal/documents/upload", data={"source_id": src["id"], "title": title, "source_page_url": "https://example.invalid/the-scanned-act"}, files={"file": (name, content if content is not None else scanned_pdf(3) + salt)})


def run_jobs(admin_c, limit=5):
    r = admin_c.post("/admin/legal/jobs/run", params={"limit": limit})
    assert r.status_code == 200, r.text
    return r.json()


def job(job_id):
    return mongo().jobs.find_one({"id": job_id})


# ---- the queue ----

def test_the_cron_trigger_needs_the_secret(anon):
    assert anon.post("/cron/jobs").status_code == 401 and anon.post("/cron/jobs", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = httpx.post(f"{API_URL}/cron/jobs", headers=CRON)
    assert r.status_code == 200 and r.json()["status"] in ("accepted", "already_running")
    for _ in range(100):  # the batch runs in the background; let it finish so it cannot claim the next test's job
        if not mongo().cron_locks.find_one({"_id": "jobs"}):
            break
        time.sleep(0.1)


def test_only_the_operator_sees_or_runs_jobs(user_a):
    expected = user_a.get("/admin/overview")
    for method, path in (("get", "/admin/legal/jobs"), ("post", "/admin/legal/jobs/run")):
        r = getattr(user_a, method)(path)
        assert r.status_code == 404 and r.json() == expected.json()


def test_a_scanned_law_pdf_is_queued_then_read_and_registered_with_per_page_metadata(admin):  # noqa: F811
    src = source(admin)
    stub("ocr", {"text": marked(FICTIONAL_PENAL_ACT)}, contains=f"legal-scan-{src['id']}")
    r = upload_scan(admin, src)
    assert r.status_code == 202 and r.json()["queued"] is True
    jid = r.json()["job_id"]
    assert job(jid)["state"] == "queued" and job(jid)["attempts"] == 0
    assert "payload" not in next(j for j in admin.get("/admin/legal/jobs").json() if j["id"] == jid)  # listings never show payloads
    run_jobs(admin)
    done = job(jid)
    assert done["state"] == "done" and done["result"]["ocr_status"] == "machine-read" and done["result"]["pages"] == 3 and done["result"]["duplicate"] is False
    doc = mongo().legal_documents.find_one({"id": done["result"]["document_id"]})
    assert doc["ocr_status"] == "machine-read" and len(doc["page_meta"]) == 3 and {m["engine"] for m in doc["page_meta"]} == {"hosted-vision"} and all(m["confidence"] is None for m in doc["page_meta"])
    assert doc["pages"][0].startswith("THE FICTIONAL PENAL ACT, 1901")


def test_machine_read_text_needs_an_explicit_acknowledgement_before_it_can_be_reviewed(admin, user_a):  # noqa: F811
    src = source(admin)
    t = tag()
    stub("ocr", {"text": marked(FICTIONAL_PENAL_ACT)}, contains=f"legal-scan-{src['id']}")
    upload_scan(admin, src)
    run_jobs(admin)
    doc_id = mongo().jobs.find_one({"payload.source_id": src["id"]})["result"]["document_id"]
    title = f"Fictional Penal Act {t}"
    ing = admin.post("/admin/legal/ingest", json={"document_id": doc_id, "instrument": {"title": title, "short_names": []}, "version_label": "original"})
    assert ing.status_code == 201 and ing.json()["provisions"] == 6
    view = find(user_a, "3", title)["exact"][0]["provisions"][0]
    assert view["reading"]["machine_read"] is True and "Read from a scan by a machine" in view["reading"]["warning"]
    no = admin.post(f"/admin/legal/provisions/{view['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"})
    assert no.status_code == 422 and "Compare it word by word with the official page" in no.json()["detail"]
    yes = admin.post(f"/admin/legal/provisions/{view['id']}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20", "acknowledge_machine_read": True})
    assert yes.status_code == 200 and yes.json()["review_status"] == "reviewed"


def test_a_text_file_is_not_machine_read_and_reviews_without_the_acknowledgement(admin, user_a):  # noqa: F811
    from tests.test_legal_data import load, prov_id

    t = load(admin)
    assert mongo().legal_documents.find_one({"id": t["doc"]["id"]})["ocr_status"] == "not-needed"
    pid = prov_id(user_a, "3", t["title"])
    assert find(user_a, "3", t["title"])["exact"][0]["provisions"][0]["reading"] == {"machine_read": False, "uncertain_page": False, "warning": None}
    assert admin.post(f"/admin/legal/provisions/{pid}/review", json={"reviewed_by": "Adv Invented Reviewer", "on": "2026-10-20"}).status_code == 200


def test_a_job_that_keeps_failing_is_retried_a_limited_number_of_times_with_a_delay_then_given_up(admin):  # noqa: F811
    src = source(admin)
    stub("ocr", "__FAIL__", contains=f"legal-scan-{src['id']}")
    jid = upload_scan(admin, src, salt=b"%fail").json()["job_id"]
    assert run_jobs(admin) == {"done": 0, "failed": 1}
    j = job(jid)
    assert j["state"] == "queued" and j["attempts"] == 1 and j["available_at"].replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + timedelta(seconds=20) and j["last_error"]
    assert run_jobs(admin) == {"done": 0, "failed": 0}  # not due yet: nothing runs
    for expected in (2, 3):
        stub("ocr", "__FAIL__", contains=f"legal-scan-{src['id']}")
        mongo().jobs.update_one({"id": jid}, {"$set": {"available_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        run_jobs(admin)
        assert job(jid)["attempts"] == expected
    final = job(jid)
    assert final["state"] == "failed" and "document" not in final["last_error"].lower() and len(final["last_error"]) <= 300
    mongo().jobs.update_one({"id": jid}, {"$set": {"available_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert run_jobs(admin) == {"done": 0, "failed": 0} and job(jid)["attempts"] == 3  # a failed job is never picked up again


def test_a_job_whose_worker_died_is_picked_up_again_after_its_lease_expires_and_runs_once(admin):  # noqa: F811
    src = source(admin)
    stub("ocr", {"text": marked(FICTIONAL_PENAL_ACT)}, contains=f"legal-scan-{src['id']}")
    jid = upload_scan(admin, src, salt=b"%lease").json()["job_id"]
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    mongo().jobs.update_one({"id": jid}, {"$set": {"state": "running", "attempts": 1, "lease_until": future}})  # another worker holds it
    assert run_jobs(admin) == {"done": 0, "failed": 0}  # leased: not taken
    mongo().jobs.update_one({"id": jid}, {"$set": {"lease_until": datetime.now(timezone.utc) - timedelta(seconds=1)}})  # that worker died; the lease ran out
    assert run_jobs(admin) == {"done": 1, "failed": 0}
    assert job(jid)["state"] == "done" and job(jid)["attempts"] == 2
    assert run_jobs(admin) == {"done": 0, "failed": 0}
    assert mongo().legal_documents.count_documents({"source_id": src["id"]}) == 1


def test_queuing_the_same_scan_twice_registers_one_document(admin):  # noqa: F811
    src = source(admin)
    stub("ocr", {"text": marked(FICTIONAL_PENAL_ACT)}, contains=f"legal-scan-{src['id']}")
    stub("ocr", {"text": marked(FICTIONAL_PENAL_ACT)}, contains=f"legal-scan-{src['id']}")
    same = scanned_pdf(3)
    a = upload_scan(admin, src, content=same).json()["job_id"]
    b = upload_scan(admin, src, content=same).json()["job_id"]
    run_jobs(admin)
    assert job(a)["result"]["duplicate"] is False and job(b)["result"]["duplicate"] is True and job(a)["result"]["document_id"] == job(b)["result"]["document_id"]
    assert mongo().legal_documents.count_documents({"source_id": src["id"]}) == 1


def test_unreadable_non_pdf_uploads_are_still_refused_not_queued(admin):  # noqa: F811
    src = source(admin)
    r = admin.post("/admin/legal/documents/upload", data={"source_id": src["id"], "title": "Blank"}, files={"file": ("blank.txt", b"   ")})
    assert r.status_code == 422 and mongo().jobs.count_documents({"payload.source_id": src["id"]}) == 0


# ---- matter documents: an uncertain page cannot back a VERIFIED claim ----

SCAN = marked(["Receipt for goods. Total Rs 40,000 paid on 4 June 2026.", "Signed by [illegible] Singh. Payment terms: 30 days."])


def test_a_claim_on_a_page_with_unreadable_words_is_never_verified_but_a_clean_page_still_is(user_a):
    mid, title = new_matter(user_a, "Uncertain")
    stub("ocr", {"text": SCAN}, contains=f"doc-scan-{mid}")
    doc = upload(user_a, mid, "scan.pdf", scanned_pdf(2))
    assert doc["uncertain_pages"] == [1, 2] and [m["page"] for m in doc["page_meta"] if m["uncertain"]] == [1, 2]  # a hosted reader gives no confidence, so every page it read is uncertain
    assert doc["page_meta"][0]["engine"] == "hosted-vision" and doc["page_meta"][0]["confidence"] is None
    stub("research", answer("Terms.", [claim("The total was Rs 40,000", cites=[doc_cite("DOC-01", "Total Rs 40,000 paid on 4 June 2026", page=1)]),
                                       claim("Payment is due in 30 days", cites=[doc_cite("DOC-01", "Payment terms: 30 days", page=2)])]), contains=title)
    out = research(user_a, mid).json()
    first, second = out["claims"]
    assert first["verification_status"] == "PARTIALLY_VERIFIED" and "low confidence or unreadable words" in first["note"]
    assert second["verification_status"] == "PARTIALLY_VERIFIED" and "low confidence or unreadable words" in second["note"] and second["human_review_required"] is True


def test_an_absence_claim_is_not_verified_while_a_document_has_uncertain_pages(user_a):
    mid, title = new_matter(user_a, "Absence")
    stub("ocr", {"text": SCAN}, contains=f"doc-scan-{mid}")
    upload(user_a, mid, "scan.pdf", scanned_pdf(2))
    stub("research", answer("None.", [{"text": "No guarantee is mentioned", "claim_kind": "ABSENCE", "search_terms": ["guarantee"], "supports": "YES", "citations": [], "conflicts": []}]), contains=title)
    c = research(user_a, mid).json()["claims"][0]
    assert c["verification_status"] == "PARTIALLY_VERIFIED" and "not certain" in c["note"]


def test_an_ordinary_text_document_has_no_page_metadata_and_nothing_uncertain(user_a):
    mid, _ = new_matter(user_a, "Plain")
    doc = upload(user_a, mid, "note.txt", "A plain note with a clear sentence about delivery.")
    assert doc["page_meta"] == [] and doc["uncertain_pages"] == []