"""Lawyer directory: lawyers who choose to be listed, and people who send them a consultation request. No payment, no ranking, no endorsement.

OFF by default (DIRECTORY_ENABLED=false). Reason: rules on how advocates may advertise or solicit work are set by their professional bodies, and whether this kind of
listing is allowed, and in what form, is a question for a lawyer BEFORE it is switched on (see docs/DIRECTORY.md). While it is off the public pages answer 404.

What the public sees of a listing: the name, city and state, practice areas, languages and a short bio the lawyer wrote, and the enrolment number AS THE LAWYER STATES IT,
always labelled "not verified by VIDHI". Never an email address or phone number. Listings are opt-in and sorted by name (nothing is ranked or promoted).
A consultation request goes to the lawyer inside VIDHI; the lawyer's email gets only a notice that a request is waiting, never its content. A request is not
legal advice and does not create a lawyer-client relationship."""

import os

PRACTICE_AREAS = (
    "Civil", "Criminal", "Family", "Property", "Corporate and commercial", "Employment and labour", "Cheque bounce and recovery",
    "Consumer", "Tax", "Intellectual property", "Cyber and technology", "Other",
)
# English plus the 22 languages of the Eighth Schedule (the same codes the app uses)
LANGUAGES = ("en", "as", "bn", "brx", "doi", "gu", "hi", "kn", "ks", "kok", "mai", "ml", "mni", "mr", "ne", "or", "pa", "sa", "sat", "sd", "ta", "te", "ur")
STATUSES = ("NEW", "CONTACTED", "DECLINED", "ARCHIVED")
NOTICE = (
    "VIDHI does not check any lawyer's enrolment, qualifications or quality, and does not recommend anyone. Listings are chosen by the lawyers themselves and shown in alphabetical order. "
    "Sending a request does not make someone your lawyer and is not legal advice: do not put confidential details in it."
)


def enabled() -> bool:
    return os.environ.get("DIRECTORY_ENABLED", "false").lower() == "true"


def public_view(p: dict) -> dict:
    return {
        "id": p["id"], "display_name": p["display_name"], "city": p.get("city", ""), "state": p.get("state", ""), "practice_areas": p.get("practice_areas", []),
        "languages": p.get("languages", []), "bio": p.get("bio", ""), "enrolment_claim": p.get("enrolment_claim", ""), "verified_by_vidhi": False,
        "accepting_requests": bool(p.get("accepting_requests", True)),
    }