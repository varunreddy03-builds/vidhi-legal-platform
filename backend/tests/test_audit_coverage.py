"""Audit coverage guard: every route that changes data must leave an audit line, or be listed here with the reason it does not.

It reads the route files (no server needed): for each POST / PUT / PATCH / DELETE route it follows the calls inside the file (a route that hands the work to a
helper in the same file counts if the helper audits) and looks for `audit(`. A new route without an audit call, and without an entry below, fails this test, so
the gap has to be a conscious decision with a written reason."""

import ast
import pathlib

ROUTERS = pathlib.Path(__file__).resolve().parent.parent / "routers"
CHANGING = {"post", "put", "patch", "delete"}

# (file, function): why this route is not audited by a line in audit_events. Reasons are the real record that exists instead.
NOT_AUDITED = {
    ("analysis.py", "evidence_classify"): "a code-only screen of the text sent; it changes and stores nothing",
    ("templates.py", "check_draft"): "a code-only check of the text; it changes and stores nothing",
    ("decide.py", "question_kind"): "a code-only classification of the text sent; it changes and stores nothing",
    ("privacy.py", "erase_me"): "a person erasing their own account: the erasure removes their id and email from the audit trail on purpose, so a line naming them would defeat it; the erasure ledger (lib/erasure_ledger.py) records the id",
    ("auth.py", "logout"): "ends the caller's own session; the session record is deleted and there is no user object at this point",
    ("auth.py", "forgot_password"): "public, no signed-in user; the email goes through send_logged (email_log) and the reset itself is audited",
    ("auth.py", "request_verification"): "the email goes through send_logged (email_log); the confirmation itself is audited",
    ("cron.py", "recovery_reminders"): "system job with no user; every message it sends is in email_log and the job holds a database lock",
    ("cron.py", "scheduled_statements"): "system job with no user; every message it sends is in email_log and the job holds a database lock",
    ("cron.py", "deadline_reminders"): "system job with no user; every message it sends is in email_log and the job holds a database lock",
    ("cron.py", "run_background_jobs"): "system job with no user; each job keeps its own record in the jobs collection",
    ("cron.py", "upload_expiry_sweep"): "system job with no user; deletions are counted in the job's own result and the files' own records",
    ("cron.py", "retention_sweep"): "system job with no user; deletions are counted in the job's own result",
    ("directory.py", "send_request"): "public form (the directory is off unless DIRECTORY_ENABLED); the request is stored with its time and the lawyer's own list shows it",
    ("org_data.py", "erase_organization"): "erasing the organisation erases its audit trail too; lib/purge.py writes the erasure_log row (organisation id, date, counts) that proves it happened",
    ("payments.py", "paypal_webhook"): "signature-verified provider event; payment_transactions and refunds are the record",
    ("payments.py", "razorpay_webhook"): "signature-verified provider event; payment_transactions and refunds are the record",
    ("payments.py", "stripe_webhook"): "signature-verified provider event; payment_transactions and refunds are the record",
    ("phone.py", "twilio_inbound"): "provider callback with no user (STOP replies); the user's alert setting is the record",
    ("recovery_mail.py", "prepare_notice_email"): "a preview that sends nothing; the send itself is audited (RECOVERY_NOTICE_EMAIL)",
    ("recovery_mail.py", "consent_act"): "the accountant's own link; the answer is recorded on the case's contact row with its time",
    ("recovery_mail.py", "sendgrid_webhook"): "signature-verified provider event; email_log holds the delivery status",
    ("recovery_mail.py", "resend_webhook"): "signature-verified provider event; email_log holds the delivery status",
    ("research.py", "give_feedback"): "a thumbs up or down stored on the answer with the user id and time (answer_feedback)",
    ("support.py", "send_message"): "public form; the message is stored with its time and the email goes through send_logged",
    ("voice.py", "speak"): "paid speech is recorded in the AI spend ledger (provider, task, size, cost); no text is stored",
    ("deadlines.py", "push_test"): "sends one notification to the caller's own device; nothing is changed",
}


def _calls(node):
    return {n.func.id if isinstance(n.func, ast.Name) else n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}


def _routes():
    """[(file, function, 'POST /path', audited)] for every data-changing route."""
    out = []
    for f in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))}

        def audited(name, seen=()):
            if name in seen or name not in fns:
                return False
            c = _calls(fns[name])
            return "audit" in c or any(audited(x, seen + (name,)) for x in c if x in fns)

        for node in fns.values():
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in CHANGING:
                    path = ast.literal_eval(d.args[0]) if d.args and isinstance(d.args[0], ast.Constant) else ""
                    out.append((f.name, node.name, f"{d.func.attr.upper()} {path}", audited(node.name)))
    return out


def test_every_data_changing_route_is_audited_or_has_a_written_reason():
    rows = _routes()
    assert len(rows) > 150, "the scan found too few routes; the guard is broken"
    missing = [f"{f}: {fn} ({route})" for f, fn, route, ok in rows if not ok and (f, fn) not in NOT_AUDITED]
    assert not missing, "These routes change data but write no audit line. Add `await audit(user, ...)` or list them in NOT_AUDITED with the reason:\n" + "\n".join(missing)


def test_the_exemption_list_stays_honest():
    """An exemption for a route that no longer exists, or that now audits, is removed so the list never grows stale."""
    rows = {(f, fn): ok for f, fn, _, ok in _routes()}
    gone = [k for k in NOT_AUDITED if k not in rows]
    now_audited = [k for k in NOT_AUDITED if rows.get(k)]
    assert not gone, f"exempted routes that no longer exist: {gone}"
    assert not now_audited, f"exempted routes that now audit (remove them from the list): {now_audited}"
    assert all(len(reason) > 25 for reason in NOT_AUDITED.values()), "every exemption needs a real reason"


def _ops(c):
    return [e["operation"] for e in c.get("/audit").json()]


def test_the_newly_audited_actions_leave_a_line(user_a):
    c = user_a
    assert c.patch("/auth/preferences", json={"theme": "light"}).status_code == 200
    mid = c.post("/matters", json={"title": "Audit lines matter", "parties": "", "description": ""}).json()["id"]
    ev = c.post(f"/matters/{mid}/timeline", json={"event_date": "2026-01-02", "description": "an event"}).json()
    assert c.delete(f"/matters/{mid}/timeline/{ev['id']}").status_code == 200
    ops = _ops(c)
    assert "PREFERENCES_CHANGED" in ops and "TIMELINE_EVENT_DELETED" in ops
