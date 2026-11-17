"""External legal sources: what VIDHI can and cannot connect to, stated honestly, and nothing that searches them.

Rules this module enforces (they follow the project rules in CLAUDE.md):
* Nothing fetched from outside is ever VERIFIED. Results are returned as unreviewed leads; only the reviewed library (lib/library.py) can verify law.
* Only PUBLIC material is ever loaded. Depositions, witness statements, cross-examination transcripts, sealed or in-camera records, juvenile records, records
  protected by an order, and any raw case file that is not a published judgment or order are refused by `ingest_allowed`, whatever the source says.
* An integration is "connected" only when it has been built AND tested against the real service. Today none has. Every entry says exactly what is missing.
* No address is written here for a service whose address was not checked (see docs/VIDHI_LEGAL_SOURCES.md for the hosts that were)."""

import os
import re

REVIEW_NOTICE = "Not verified. This is a lead from an outside service. Read the official text, and have a lawyer check it, before relying on it."

# document kinds that must never be loaded, whoever offers them
REFUSED_KINDS = {
    "deposition", "witness_statement", "cross_examination", "examination_in_chief", "transcript", "case_file", "raw_case_file", "chargesheet",
    "sealed", "in_camera", "juvenile", "witness_protection", "confidential", "strategy", "privileged",
}
PUBLIC_KINDS = {"act", "rule", "regulation", "notification", "gazette", "order", "judgment", "bill", "report", "circular", "constitution", "amendment"}


def ingest_allowed(document_kind: str | None) -> tuple[bool, str]:
    """(allowed, reason). Anything not clearly a published legal text or a published judgment/order is refused."""
    kind = re.sub(r"[\s\-]+", "_", (document_kind or "").strip().lower())
    if kind in REFUSED_KINDS:
        return False, "Records of this kind (depositions, witness statements, transcripts, sealed or protected material, raw case files) are not public legal texts and are never loaded."
    if kind not in PUBLIC_KINDS:
        return False, "Only published legal texts (Acts, rules, notifications, gazettes, bills, reports, judgments and orders) can be loaded. Say which kind this is."
    return True, ""


# status values: CLIENT_BUILT_OFF (code exists, needs a token, tested only with fakes) | MANUAL_INGEST (a person supplies the official file) |
# LINK_OUT (people are pointed to it; nothing is fetched) | NOT_INTEGRATED (nothing built; the blocker is stated)
REGISTRY = [
    dict(id="indiankanoon", name="Indian Kanoon API", kind="commercial-api", status="NOT_INTEGRATED", host=None,
         gives="Search over published judgments and some Acts; a search lead only.",
         blocked_by="Not used. Authority Check reads the free Supreme Court open dataset instead, and the old Indian Kanoon client was removed."),
    dict(id="ecourts_open_api", name="eCourts open API / BharatAPI exchange", kind="api", status="NOT_INTEGRATED", host=None,
         gives="Case status data, if an open API exists for the use.", blocked_by="No public API specification, terms or credentials were found or supplied; the eCourts hosts were not reachable from the build machine. Needs an agreement or documented API."),
    dict(id="njdg", name="National Judicial Data Grid (NJDG)", kind="statistics-portal", status="LINK_OUT", host=None,
         gives="Aggregate pendency statistics; not a source of legal text.", blocked_by="No documented API. Statistics only."),
    dict(id="clawlaw", name="Claw Law API", kind="commercial-api", status="NOT_INTEGRATED", host=None,
         gives="Unknown.", blocked_by="Commercial service: needs a contract, credentials and its documentation. None supplied."),
    dict(id="vlex", name="vLex / vLex Justis Indian law", kind="commercial-api", status="NOT_INTEGRATED", host=None,
         gives="Licensed case law and legislation.", blocked_by="Licensed content: needs a contract and credentials. Licence terms must allow the use."),
    dict(id="indiacode", name="India Code (central Acts and rules)", kind="official-portal", status="MANUAL_INGEST", host="indiacode.nic.in",
         gives="Official text of central Acts.", blocked_by="Terms not read; no API found. A person downloads the official file and registers it (lib/legal_store.py)."),
    dict(id="legislative_dept", name="Legislative Department", kind="official-portal", status="MANUAL_INGEST", host="legislative.gov.in",
         gives="Acts, bills, rules.", blocked_by="Terms not read. Manual supply."),
    dict(id="egazette", name="e-Gazette of India", kind="official-portal", status="MANUAL_INGEST", host="egazette.gov.in",
         gives="Notifications and gazettes.", blocked_by="Session-based search; terms not read. Manual supply."),
    dict(id="supreme_court", name="Supreme Court of India portal / judgment search", kind="official-portal", status="MANUAL_INGEST", host="www.sci.gov.in",
         gives="Published judgments and orders.", blocked_by="Search may need interactive steps or a CAPTCHA, which VIDHI will not bypass. Terms not read. Manual supply."),
    dict(id="e_scr", name="e-SCR (Supreme Court Reports)", kind="official-portal", status="NOT_INTEGRATED", host=None,
         gives="Reported Supreme Court judgments.", blocked_by="Address, terms and access method not checked."),
    dict(id="ecourts_services", name="eCourts Services", kind="official-portal", status="LINK_OUT", host="ecourts.gov.in",
         gives="Case status for the people involved.", blocked_by="Host was not reachable from the build machine; interactive, CAPTCHA-protected. VIDHI points people to it."),
    dict(id="law_ministry", name="Ministry of Law and Justice", kind="official-portal", status="NOT_INTEGRATED", host=None,
         gives="Policy pages.", blocked_by="Not a text source for this use."),
    dict(id="law_commission", name="Law Commission of India", kind="official-portal", status="MANUAL_INGEST", host=None,
         gives="Reports (not law).", blocked_by="Address and terms not checked. Reports are commentary, never verification."),
    dict(id="digital_sansad", name="Digital Sansad (Parliament)", kind="official-portal", status="NOT_INTEGRATED", host=None,
         gives="Bills and debates.", blocked_by="Address and terms not checked."),
    dict(id="nalsa", name="National Legal Services Authority (NALSA)", kind="referral", status="LINK_OUT", host=None,
         gives="Free legal aid for eligible people.", blocked_by="A referral, not data. Eligibility is NALSA's to decide."),
    dict(id="tele_law", name="Tele-Law", kind="referral", status="LINK_OUT", host=None,
         gives="Advice by phone or video through the government service.", blocked_by="A referral, not data."),
    dict(id="nch", name="National Consumer Helpline (NCH)", kind="referral", status="LINK_OUT", host=None,
         gives="Consumer complaints help.", blocked_by="A referral, not data."),
]


def registry() -> list[dict]:
    """The registry with a computed `configured` flag. Nothing here ever shows a token."""
    out = []
    for e in REGISTRY:
        row = dict(e)
        env = e.get("env")
        row["configured"] = bool(env and os.environ.get(env, "").strip())
        row["live_tested"] = False
        out.append(row)
    return out


def referrals() -> list[dict]:
    """Public help services people can be pointed to (names and purpose only)."""
    return [{"id": e["id"], "name": e["name"], "gives": e["gives"], "note": e["blocked_by"]} for e in REGISTRY if e["kind"] == "referral"]
