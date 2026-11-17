"""The operator's genuine business and privacy details, configured later by the owner.

NOTHING here is invented: every field comes from an environment variable and is None until the owner sets it. The legal pages show an obvious
"not configured yet" marker for anything missing, and the admin console lists what is still to be filled in. Whether a placeholder is legally
sufficient, and whether GST registration or any other registration is required, is for the owner and a qualified adviser to decide.

  BUSINESS_LEGAL_NAME           the legal entity that runs the service
  BUSINESS_REGISTERED_ADDRESS   its registered address
  BUSINESS_REGISTRATION_NUMBER  company / LLP / firm registration number, if any
  BUSINESS_GSTIN                GST number, only if the business is registered (format-checked, never verified)
  GRIEVANCE_OFFICER_NAME / GRIEVANCE_OFFICER_EMAIL / GRIEVANCE_OFFICER_ADDRESS   the grievance / privacy contact
  PRIVACY_CONTACT_EMAIL         for data-rights requests (defaults to the grievance officer's email)
  SUPPORT_EMAIL                 where support messages go
  SUPPORT_WHATSAPP              optional; leave empty until there is a genuine business number
  DATA_REQUEST_RESPONSE_DAYS    our own target for answering a data request (default 30). It is a service target, not a statement of any legal deadline."""

import os
import re

FIELDS = {
    "legal_name": "BUSINESS_LEGAL_NAME",
    "registered_address": "BUSINESS_REGISTERED_ADDRESS",
    "registration_number": "BUSINESS_REGISTRATION_NUMBER",
    "gstin": "BUSINESS_GSTIN",
    "grievance_name": "GRIEVANCE_OFFICER_NAME",
    "grievance_email": "GRIEVANCE_OFFICER_EMAIL",
    "grievance_address": "GRIEVANCE_OFFICER_ADDRESS",
    "privacy_email": "PRIVACY_CONTACT_EMAIL",
    "support_email": "SUPPORT_EMAIL",
    "support_whatsapp": "SUPPORT_WHATSAPP",
}
REQUIRED_FOR_LAUNCH = ("legal_name", "registered_address", "grievance_name", "grievance_email", "support_email")  # GSTIN and registration are decisions for the owner
_GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get(key: str) -> str | None:
    value = (os.environ.get(FIELDS[key]) or "").strip()
    if key == "privacy_email" and not value:
        value = (os.environ.get(FIELDS["grievance_email"]) or "").strip()
    if not value:
        return None
    if key == "gstin" and not _GSTIN.match(value.upper()):
        return None  # a malformed number is never shown; the admin console flags it
    if key.endswith("_email") and not _EMAIL.match(value):
        return None
    return value.upper() if key == "gstin" else value


def public_config() -> dict[str, str | None]:
    return {k: get(k) for k in FIELDS}


def missing() -> list[str]:
    """Launch details still to be provided (GSTIN and registration number are optional and not listed)."""
    return [k for k in REQUIRED_FOR_LAUNCH if get(k) is None]


def problems() -> list[str]:
    """Settings that are present but unusable, so the owner is told instead of silently losing them."""
    out = []
    if (os.environ.get(FIELDS["gstin"]) or "").strip() and get("gstin") is None:
        out.append("BUSINESS_GSTIN is set but is not in the format of a GST number")
    for k in ("grievance_email", "privacy_email", "support_email"):
        if (os.environ.get(FIELDS[k]) or "").strip() and get(k) is None:
            out.append(f"{FIELDS[k]} is set but is not a valid email address")
    return out


def response_days() -> int:
    try:
        return max(1, int(os.environ.get("DATA_REQUEST_RESPONSE_DAYS", "30")))
    except ValueError:
        return 30