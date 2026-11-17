"""Organisation-separation guard (structural): a function that reads or changes customer data must be anchored to the caller's organisation or user.

This reads the code, not a server. For every function in routers/ and lib/ that queries a customer-data collection it asks: does the function name
`organization_id`, the caller's user id or `created_by`, or call a getter that checks the organisation first (get_matter, _get_case, ...)? If not, the
function must be listed in NOT_ANCHORED with the reason it is still safe (a helper whose caller already checked, global reference data, a system job,
a signature- or token-checked public route). A NEW function that queries customer data with no anchor and no written reason fails this test.

This is a ratchet, not a proof: it cannot show that every query is right, only that none is added without a person deciding. The behavioural proof is the
cross-organisation tests (test_tenancy.py and the per-feature files), which log in as a second organisation and must be refused."""

import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parent.parent
OPS = {"find", "find_one", "update_one", "update_many", "delete_one", "delete_many", "count_documents", "aggregate", "replace_one", "find_one_and_update", "distinct"}
# getters that look the record up WITH the caller's organisation (each is itself covered by cross-organisation tests)
GETTERS = {"get_matter", "_get_case", "get_case", "_mine", "_need_current", "_need", "require_org", "get_document", "_get_doc", "_matter_for", "_live_invite"}
ANCHOR = re.compile(r'organization_id|\borg_id\b|user\["id"\]|user\[.id.\]|"user_id"|created_by')
EXTRA_COLLECTIONS = {"matters", "recovery_cases", "facts", "timeline_events", "evidence_items", "people", "document_differences", "documents", "research_results", "drafts"}

HELPER = "a helper: every caller has already fetched the record with the caller's organisation (or checked the id against an organisation-scoped parent) before it runs"
GLOBAL = "global reference data, not customer data: shared works and public listings are meant to be read by everyone"
SYSTEM = "a system job with no user; it works across all organisations on purpose and runs only behind the cron secret"
NOT_ANCHORED = {
    **{("lib/knowledge.py", fn): GLOBAL + " (private works carry scope 'org' and org_id, and every private query names both)" for fn in (
        "import_registry", "_canonical", "set_status", "record_rights", "dashboard", "domains")},
    ("routers/knowledge.py", "works"): GLOBAL + " (private ones are excluded by the query)",
    ("lib/notice_workflow.py", "_event"): HELPER,
    ("lib/notice_workflow.py", "current_version"): HELPER,
    ("lib/notice_workflow.py", "approve"): HELPER,
    ("lib/notice_workflow.py", "set_state"): HELPER,
    ("lib/purge.py", "purge_document"): HELPER + " (the delete routes, the retention job and organisation erasure)",
    ("lib/purge.py", "purge_matter"): HELPER + " (the delete routes, the retention job and organisation erasure)",
    ("lib/purge.py", "purge_case"): HELPER + " (the delete routes, the retention job and organisation erasure)",
    ("lib/auth.py", "destroy_session"): "a sign-in session is found by the hash of its own secret token: the token is the anchor, and a person only ever holds their own",
    ("lib/auth.py", "renew_session"): "a sign-in session is found by the hash of its own secret token: the token is the anchor, and a person only ever holds their own",
    ("routers/auth.py", "me"): "reads and refreshes the signed-in person's own session, found by the hash of their own token",
    **{("routers/admin.py", fn): "platform-admin console only (require_platform_admin); it reads across organisations on purpose" for fn in ("overview", "support", "set_support_status")},
    ("lib/retention.py", "purge_operational"): SYSTEM + " (it deletes the platform's own records past their period, never a customer's matter)",
    ("lib/reminders.py", "run_deadline_reminders"): SYSTEM,
    ("routers/admin_weekly.py", "wrong_result_reports"): "platform-admin console only (require_platform_admin); it counts answers marked down and results marked wrong across organisations on purpose and returns numbers, never a comment",
    ("lib/product_stats.py", "report"): "platform-admin console only (the route has the admin guard); it counts, across organisations on purpose, how many wrong-result reports were made, and returns numbers only: the rows it reads hold no organisation or person (see docs/privacy/PRODUCT_NUMBERS.md)",
    ("routers/admin.py", "signals"): "platform-admin console only (require_platform_admin); it reads counts across organisations on purpose",
    ("routers/directory.py", "list_lawyers"): GLOBAL + " (only profiles their owners chose to list, and only when DIRECTORY_ENABLED is on)",
    ("routers/directory.py", "read_lawyer"): GLOBAL + " (only a profile its owner chose to list)",
    ("routers/documents.py", "_matter_brief"): HELPER,
    ("routers/evidence.py", "_document_in_matter"): HELPER + "; the document must also belong to that matter",
    ("routers/matters.py", "_check_document_link"): HELPER + "; the document must also belong to that matter",
    ("routers/recovery.py", "_sync_paid"): HELPER,
    ("routers/recovery.py", "advance_status"): HELPER,
    ("routers/recovery_delivery.py", "_replies"): HELPER,
    ("routers/recovery_intake.py", "_proofs"): HELPER,
    ("routers/recovery_mail.py", "consent_act"): "public page for an accountant: the signed, expiring link names the case, and the token is checked before anything is read or changed",
    ("routers/team.py", "_live_invite"): "looks an invitation up by its secret one-time token; an invitation is meant to be found by the person who holds the token",
}


def _collections() -> set[str]:
    cols = set(EXTRA_COLLECTIONS)
    purge = ast.parse((BACKEND / "lib" / "purge.py").read_text(encoding="utf-8"))
    for n in ast.walk(purge):
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "coll" and isinstance(n.iter, ast.Tuple):
            cols |= {e.value for e in n.iter.elts if isinstance(e, ast.Constant)}
    for n in purge.body:  # collections named once in a module-level tuple that the loops use (ORG_TAGGED, MATTER_COLLECTIONS): found the same way as a literal tuple in the loop
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple) and any(isinstance(t, ast.Name) and t.id in ("ORG_TAGGED", "MATTER_COLLECTIONS") for t in n.targets):
            cols |= {e.value for e in n.value.elts if isinstance(e, ast.Constant)}
    return cols


def _unanchored() -> set[tuple[str, str]]:
    cols = _collections()
    out = set()
    for f in sorted(list((BACKEND / "routers").glob("*.py")) + list((BACKEND / "lib").rglob("*.py"))):
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]:
            queries = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in OPS and isinstance(n.func.value, ast.Attribute)
                and isinstance(n.func.value.value, ast.Name) and n.func.value.value.id == "db" and n.func.value.attr in cols
            ]
            if not queries:
                continue
            seg = ast.get_source_segment(src, fn) or ""
            calls = {c.func.id if isinstance(c.func, ast.Name) else c.func.attr for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, (ast.Name, ast.Attribute))}
            if not (ANCHOR.search(seg) or calls & GETTERS):
                out.add((f.relative_to(BACKEND).as_posix(), fn.name))
    return out


def test_collections_were_found():
    assert len(_collections()) > 30, "the scan found too few customer-data collections; the guard is broken"


def test_no_new_function_reads_customer_data_without_an_anchor_or_a_written_reason():
    new = sorted(_unanchored() - set(NOT_ANCHORED))
    assert not new, (
        "These functions query customer data but name no organization_id / user id and use no organisation-scoped getter. Scope the query, or add the "
        "function to NOT_ANCHORED with the reason it is safe:\n" + "\n".join(f"  {f}: {fn}" for f, fn in new)
    )


def test_the_exemption_list_stays_honest():
    now = _unanchored()
    stale = sorted(k for k in NOT_ANCHORED if k not in now)
    assert not stale, f"exempted functions that no longer exist or are now anchored (remove them): {stale}"
    assert all(len(r) > 25 for r in NOT_ANCHORED.values())
