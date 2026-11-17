"""What evidence and facts a payment-demand case still lacks. Deterministic: it looks at what the owner typed and
how the uploaded files were labelled, and says plainly what is missing. It never guesses what a file contains
and never invents a document."""

PROOF_KINDS = ("INVOICE", "PURCHASE_ORDER", "AGREEMENT", "DELIVERY_PROOF", "PAYMENT_RECORD", "COMMUNICATION", "OTHER")

KIND_LABELS = {
    "INVOICE": "Invoice or bill",
    "PURCHASE_ORDER": "Purchase order",
    "AGREEMENT": "Agreement or quotation",
    "DELIVERY_PROOF": "Delivery or completion proof",
    "PAYMENT_RECORD": "Payment record",
    "COMMUNICATION": "Messages or emails",
    "OTHER": "Other",
}

# (key, label, kinds that satisfy it, why it matters)
_CHECKLIST = [
    ("invoice", "The invoice or bill", {"INVOICE"}, "It shows what was charged, when and to whom."),
    ("delivery", "Proof the goods were delivered or the work was done", {"DELIVERY_PROOF"}, "A signed challan, courier receipt, completion message or similar. Customers most often dispute delivery."),
    ("order", "The order, quotation or agreement", {"PURCHASE_ORDER", "AGREEMENT"}, "It shows what the customer agreed to, including the price and payment terms."),
    ("communication", "Messages or emails with the customer about the payment", {"COMMUNICATION"}, "Reminders you sent, and any reply or promise to pay."),
]


def check_evidence(case: dict, proofs: list[dict]) -> dict:
    intake = case.get("intake") or {}
    by_kind: dict[str, list[str]] = {}
    for p in proofs:
        by_kind.setdefault(p.get("kind") or "OTHER", []).append(p.get("filename", ""))

    items = []
    for key, label, kinds, why in _CHECKLIST:
        files = [f for k in kinds for f in by_kind.get(k, [])]
        need = "required" if key in ("invoice", "delivery") else "recommended"
        items.append({"key": key, "label": label, "need": need, "why": why, "status": "PRESENT" if files else "MISSING", "files": files})
    if case.get("payments") or case.get("credits"):
        files = by_kind.get("PAYMENT_RECORD", [])
        items.append({
            "key": "payments", "label": "Records of the payments or credits you entered", "need": "recommended",
            "why": "Bank entries, receipts or credit notes let the customer see the balance is fair.",
            "status": "PRESENT" if files else "MISSING", "files": files,
        })
    promise = intake.get("promise_to_pay") or {}
    if (promise.get("text") or "").strip() and not by_kind.get("COMMUNICATION"):
        items.append({
            "key": "promise", "label": "The message or email in which the customer promised to pay", "need": "recommended",
            "why": "You said there is a written promise. Upload it so it can be listed with the notice.",
            "status": "MISSING", "files": [],
        })

    facts = [
        ("amount", "Invoice amount", float(case.get("amount") or 0) > 0),
        ("invoice_number", "Invoice number", bool((intake.get("invoice_number") or "").strip())),
        ("invoice_date", "Invoice date", bool(intake.get("invoice_date"))),
        ("supply_description", "What was supplied (goods or services)", bool((intake.get("supply_description") or "").strip())),
        ("due_date", "Date the payment was due", bool(case.get("due_date"))),
        ("payment_terms", "Agreed payment terms", bool((intake.get("payment_terms") or "").strip())),
        ("creditor_address", "Your business address", bool((case.get("creditor_address") or "").strip())),
        ("debtor_address", "The customer's address", bool((case.get("debtor_address") or "").strip())),
    ]
    facts_missing = [{"key": k, "label": l} for k, l, ok in facts if not ok]
    required_missing = [i for i in items if i["need"] == "required" and i["status"] == "MISSING"]
    return {
        "items": items,
        "facts_missing": facts_missing,
        "required_missing": [i["label"] for i in required_missing],
        "complete": not required_missing and not facts_missing,
        "note": "Missing evidence does not stop you drafting a notice, but a customer who disputes the claim will ask for it. "
        "VIDHI lists only what you uploaded; it does not decide whether a document proves anything.",
    }


def enclosures(proofs: list[dict], picked: list[str] | None = None) -> list[str]:
    """Names of the uploaded documents, in a stable order, as a numbered enclosure list. `picked` limits it to ids."""
    rows = [p for p in proofs if picked is None or p.get("id") in picked]
    order = {k: i for i, k in enumerate(PROOF_KINDS)}
    rows.sort(key=lambda p: (order.get(p.get("kind") or "OTHER", 99), p.get("filename", "")))
    return [f"{KIND_LABELS.get(p.get('kind') or 'OTHER', 'Document')}: {p.get('filename', '')}" for p in rows]
