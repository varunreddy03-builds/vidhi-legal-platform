"""What is, and is not, known about whether a notice reached the customer.

Pure functions over the records VIDHI keeps (the email log with provider events, postal entries the owner typed in,
replies the owner logged). Nothing here claims legal service: "sent" means a provider accepted an email; "delivered"
means the provider says the recipient's mail server accepted it; neither proves the customer read it."""

import re
from datetime import datetime, timezone

STATUS_DRAFT = "Draft"
STATUS_AWAITING = "Awaiting Approval"
STATUS_APPROVED = "Approved"
STATUS_SENT = "Sent"
STATUS_DELIVERED = "Delivery Confirmed by Provider"
STATUS_BOUNCED = "Bounced"
STATUS_RESPONSE = "Response Received"
STATUS_POSTAL = "Postal Tracking Updated"

LEGAL_NOTE = (
    "VIDHI cannot tell you whether this notice has been legally served. Whether email, post or something else is enough "
    "depends on the situation: ask an advocate, especially before relying on the notice in a dispute."
)


_NOT_RECEIPT = {
    "not", "never", "undelivered", "fail", "failed", "unable", "attempt", "attempted", "attempts", "return", "returned", "refused", "yet", "will", "would", "tomorrow", "expected",
    "pending", "awaiting", "back", "rto", "without", "cannot", "soon", "be", "being", "before", "if", "once", "when", "until", "sender", "origin", "hub", "depot", "warehouse",
    "office", "branch", "facility", "centre", "center", "wrong", "misdelivered", "redirected", "held", "hold",
}


def _says_delivered(text) -> bool:
    """Only an update that plainly says it was delivered counts as receipt evidence. "Out for delivery", "not delivered", "yet to be delivered", "will be delivered
    tomorrow", "delivered back to sender", "delivered to the sorting hub" and the like do not."""
    s = str(text).lower().replace("\u2019", "'")
    words = re.findall(r"[a-z']+", s)
    return "delivered" in words and not any(w in _NOT_RECEIPT or w.endswith("n't") for w in words)


def _aware(dt) -> datetime:
    if isinstance(dt, str):  # an ISO date the owner typed (for example the posting date)
        try:
            dt = datetime.fromisoformat(dt[:10])
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _day(dt) -> str:
    return _aware(dt).strftime("%d %b %Y")


def display_status(state: str, email_rows: list[dict], postal: list[dict], replies: list[dict]) -> str:
    """One label, using the app's own vocabulary, for where the notice stands now."""
    if state in ("DRAFT", "CHANGES_REQUESTED"):
        return STATUS_DRAFT
    if state == "ADVOCATE_REVIEW_REQUESTED":
        return STATUS_AWAITING
    if state == "APPROVED":
        return STATUS_APPROVED
    events: list[tuple[datetime, str]] = []
    for r in email_rows:
        label = {"DELIVERED": STATUS_DELIVERED, "BOUNCED": STATUS_BOUNCED, "COMPLAINED": STATUS_BOUNCED}.get(r.get("status"), STATUS_SENT)
        events.append((_aware(r.get("updated_at") or r.get("created_at")), label))
    for p in postal:
        last = (p.get("updates") or [None])[-1]
        events.append((_aware((last or {}).get("at") or p.get("at")), STATUS_POSTAL if p.get("updates") else STATUS_SENT))
    if any(x.get("is_response") for x in replies):
        return STATUS_RESPONSE
    if not events:
        return STATUS_SENT
    return max(events, key=lambda e: e[0])[1]


def evidence_summary(email_rows: list[dict], postal: list[dict], replies: list[dict]) -> dict:
    have: list[str] = []
    missing: list[str] = []
    for r in email_rows:
        to, when = r.get("to", ""), _day(r.get("created_at"))
        st = r.get("status")
        if st == "DELIVERED":
            have.append(f"Email to {to} on {when}: the email provider reports it was delivered to the recipient's mail server. This does not show the customer opened or read it.")
        elif st in ("BOUNCED", "COMPLAINED"):
            have.append(f"Email to {to} on {when}: it {'bounced' if st == 'BOUNCED' else 'was marked as spam'}. It did not reach the customer by email.")
        elif st == "FAILED":
            have.append(f"Email to {to} on {when}: it could not be sent.")
        else:
            have.append(f"Email to {to} on {when}: accepted by the email provider for delivery. No delivery confirmation has been received.")
    for p in postal:
        line = f"Posted on {_day(p.get('sent_on') or p.get('at'))} via {p.get('service', 'post')}, tracking no. {p.get('tracking_no') or '(none recorded)'}."
        ups = p.get("updates") or []
        if ups:
            line += f" Latest update: {ups[-1].get('status')} ({_day(ups[-1].get('at'))})."
        else:
            line += " No tracking update has been recorded yet."
        have.append(line)
    for x in replies:
        if x.get("direction") == "IN":
            have.append(f"A message from the customer was logged for {x.get('occurred_on')} ({x.get('channel', '').replace('_', ' ').lower()}). Keep the original message as evidence.")
    got_receipt = any(r.get("status") == "DELIVERED" for r in email_rows) or any(
        any(_says_delivered(u.get("status", "")) for u in (p.get("updates") or [])) for p in postal
    ) or any(x.get("direction") == "IN" and x.get("is_response") for x in replies)  # a message only counts when the owner marked it as a reply to the notice
    if not got_receipt:
        missing.append("There is no confirmation that the customer received the notice.")
    missing.append("There is no proof that the customer read it.")
    missing.append(LEGAL_NOTE)
    return {"what_we_have": have, "not_confirmed": missing}
