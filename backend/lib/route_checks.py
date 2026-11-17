"""Which legal route a payment case might need, and when an ordinary demand letter is probably not enough.

This module does NOT decide any legal question. It turns the owner's own answers into plain warnings and
pointers and says "ask an advocate" where judgment is needed. Project rule 1: it states no section number, no
time period and no eligibility conclusion; the one time-limit rule it can show is a lawyer-verified entry from
lib/limitation.py, and with none it only reports how old the debt is.

Levels: INFO (good to know), WARN (take care, consider an advocate), STOP (an ordinary letter may be the wrong
step: the owner must acknowledge before a notice is drafted).
"""

from datetime import date

from lib.limitation import assess as assess_limitation

OLD_DEBT_DAYS = 730  # a reminder threshold, not a legal period: "this is getting old", nothing more

MSME_QUESTIONS = [
    "Is your business registered as a micro or small enterprise (for example with an Udyam registration)? Since when?",
    "Did you supply the goods or services after that registration?",
    "Is the customer a business or organisation (not an ordinary consumer)?",
    "Is there a written agreement or invoice terms about when payment was due?",
]


QUESTIONS = [
    ("cheque_bounced", "did a cheque from the customer bounce?"),
    ("existing_proceedings", "is there already a case or complaint about this money?"),
    ("insolvency", "may the customer be in insolvency or closure proceedings?"),
]


def _flag(key: str, level: str, title: str, text: str, questions: list[str] | None = None) -> dict:
    out = {"key": key, "level": level, "title": title, "text": text}
    if questions:
        out["questions"] = questions
    return out


def check_routes(case: dict, today: date) -> dict:
    intake = case.get("intake") or {}
    route = intake.get("route") or {}
    disputes = intake.get("disputes") or {}
    flags: list[dict] = []

    if route.get("cheque_bounced") == "yes":
        flags.append(_flag(
            "cheque", "STOP", "A cheque from the customer bounced",
            "A dishonoured cheque can follow its own legal procedure, with a strict time limit that may start when you "
            "were told the cheque bounced. An ordinary demand letter might not be the right first step, and waiting "
            "could cost you that route. Please speak to an advocate straight away. VIDHI cannot tell you the deadline.",
        ))
    elif route.get("cheque_bounced") == "unsure" or route.get("cheque_given") == "yes":
        flags.append(_flag(
            "cheque", "WARN", "A cheque is involved",
            "If a cheque was given and it bounces, tell an advocate immediately: there may be a short time limit.",
        ))

    if route.get("existing_proceedings") == "yes":
        flags.append(_flag(
            "proceedings", "STOP", "There is already a case or complaint about this money",
            "Sending your own letter while a case is running can affect it. Ask your advocate before writing to the customer.",
        ))
    elif route.get("existing_proceedings") == "unsure":
        flags.append(_flag(
            "proceedings", "WARN", "You are not sure whether there is already a case about this money",
            "Find out before you write to the customer: a letter sent while a case is running can affect it. An advocate can help you check.",
        ))
    if route.get("insolvency") == "yes":
        flags.append(_flag(
            "insolvency", "STOP", "The customer may be in insolvency or closure proceedings",
            "Different rules can apply to claims against such a customer, and a demand letter may not be the right step. Please consult an advocate.",
        ))
    elif route.get("insolvency") == "unsure":
        flags.append(_flag(
            "insolvency", "WARN", "You are not sure whether the customer is in insolvency or closure proceedings",
            "Different rules can apply if they are, and a demand letter may not be the right step. An advocate can help you check.",
        ))

    unanswered = [label for key, label in QUESTIONS if route.get(key) in (None, "")]
    if unanswered:
        flags.append(_flag(
            "unanswered", "INFO", "Some questions are not answered yet",
            "VIDHI cannot say whether this looks like an ordinary unpaid invoice until these are answered: " + "; ".join(unanswered) + ".",
        ))

    disputed = [k for k in ("invoice", "quality", "delivery", "amount") if disputes.get(k)]
    if disputed:
        flags.append(_flag(
            "dispute", "WARN", "The customer disputes this claim",
            f"You told us the customer disputes: {', '.join(disputed)}. A letter that ignores a dispute can make things "
            "worse. The notice will describe the dispute neutrally; consider having an advocate review it first.",
        ))

    if route.get("msme") in ("yes", "unsure"):
        flags.append(_flag(
            "msme", "INFO", "You may be able to use the MSME delayed-payment route",
            "Small and micro enterprises can, in some cases, take delayed-payment claims against their customers to the "
            "MSE Facilitation Council through the government's MSME Samadhaan portal. Whether you qualify depends on facts "
            "(registration, dates, who the customer is). VIDHI has not checked your eligibility and has not verified the "
            "rules against its legal library: confirm with an advocate or the official portal. Answers that matter:",
            MSME_QUESTIONS,
        ))

    lim = assess_limitation(case.get("due_date"), today)
    if lim["mode"] == "NEEDS_DUE_DATE":
        flags.append(_flag("due_date", "WARN", "The due date is missing", "Without the date payment was due, VIDHI cannot show how old the debt is."))
    else:
        passed = [r for r in lim["rules"] if r["status"] == "PASSED"]
        if passed:
            flags.append(_flag(
                "limitation", "STOP", "A verified time limit appears to have passed",
                f"{passed[0]['applies_to']}: the deadline was {passed[0]['deadline']} (source: {passed[0]['citation']}). "
                "A lawyer must check whether anything extends it before you send anything.",
            ))
        elif (lim["age_days"] or 0) >= OLD_DEBT_DAYS:
            flags.append(_flag(
                "limitation", "WARN", f"This debt is {lim['age_text']} old",
                "Claims can be lost if they are brought too late. VIDHI does not know your deadline: see an advocate soon.",
            ))

    stops = [f for f in flags if f["level"] == "STOP"]
    warns = [f for f in flags if f["level"] == "WARN"]
    if not flags:
        flags.append(_flag(
            "ordinary", "INFO", "This looks like an ordinary unpaid invoice",
            "A polite, firm demand letter is a reasonable first step. VIDHI has not decided any legal question about your claim.",
        ))
    return {
        "flags": flags,
        "blocks_notice": bool(stops),
        "advocate_recommended": bool(stops or warns),
        "disclaimer": "VIDHI prepares documents. It is not a law firm and this is not legal advice; an advocate should "
        "decide the route for anything that is disputed, old, or involves a cheque, proceedings or insolvency.",
    }
