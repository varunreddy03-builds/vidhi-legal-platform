"""States, Union Territories and High Courts of India, so a law can say WHERE it applies (central "IN" = everywhere; "IN-TG" = Telangana only).

HONESTY NOTE: this list is general knowledge, NOT yet confirmed against the Ministry of Home Affairs or Supreme Court lists
(docs/VIDHI_JURISDICTION_REGISTRY.md section 2). Every entry therefore carries `confirmed: False`, and every source row is `not_checked`:
no State or UT source has been verified. A missing source never means that no law exists. Codes follow ISO 3166-2:IN."""

STATES = {
    "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam", "BR": "Bihar", "CG": "Chhattisgarh", "GA": "Goa", "GJ": "Gujarat", "HR": "Haryana",
    "HP": "Himachal Pradesh", "JH": "Jharkhand", "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh", "MH": "Maharashtra", "MN": "Manipur",
    "ML": "Meghalaya", "MZ": "Mizoram", "NL": "Nagaland", "OD": "Odisha", "PB": "Punjab", "RJ": "Rajasthan", "SK": "Sikkim", "TN": "Tamil Nadu",
    "TG": "Telangana", "TR": "Tripura", "UP": "Uttar Pradesh", "UK": "Uttarakhand", "WB": "West Bengal",
}
UNION_TERRITORIES = {
    "AN": "Andaman and Nicobar Islands", "CH": "Chandigarh", "DH": "Dadra and Nagar Haveli and Daman and Diu", "DL": "Delhi",
    "JK": "Jammu and Kashmir", "LA": "Ladakh", "LD": "Lakshadweep", "PY": "Puducherry",
}
# High Court -> the territories it serves (general knowledge, unconfirmed)
HIGH_COURTS = {
    "Allahabad": ["UP"], "Andhra Pradesh": ["AP"], "Bombay": ["MH", "GA", "DH"], "Calcutta": ["WB", "AN"], "Chhattisgarh": ["CG"], "Delhi": ["DL"],
    "Gauhati": ["AS", "NL", "MZ", "AR"], "Gujarat": ["GJ"], "Himachal Pradesh": ["HP"], "Jammu & Kashmir and Ladakh": ["JK", "LA"], "Jharkhand": ["JH"],
    "Karnataka": ["KA"], "Kerala": ["KL", "LD"], "Madhya Pradesh": ["MP"], "Madras": ["TN", "PY"], "Manipur": ["MN"], "Meghalaya": ["ML"], "Orissa": ["OD"],
    "Patna": ["BR"], "Punjab & Haryana": ["PB", "HR", "CH"], "Rajasthan": ["RJ"], "Sikkim": ["SK"], "Telangana": ["TG"], "Tripura": ["TR"], "Uttarakhand": ["UK"],
}
SOURCE_CATEGORIES = ("legislation", "gazette", "rules_and_notifications", "high_court", "district_courts", "tribunals", "local_bodies")
CENTRAL = "IN"


def _code(code: str) -> str:
    return f"IN-{code}"


def all_codes() -> set[str]:
    return {CENTRAL} | {_code(c) for c in {**STATES, **UNION_TERRITORIES}}


def valid_code(code: str | None) -> bool:
    return code in all_codes()


def name_of(code: str) -> str:
    if code == CENTRAL:
        return "India (central law)"
    short = code.removeprefix("IN-")
    return STATES.get(short) or UNION_TERRITORIES.get(short) or code


def applies_in(instrument_jurisdiction: str | None, territory: str | None) -> bool:
    """Central law ("IN", or no jurisdiction recorded on an older record) applies everywhere; a State or UT law only in its own territory.
    With no territory asked for, nothing is excluded (the caller then shows every record and its jurisdiction)."""
    if not territory or instrument_jurisdiction in (None, "", CENTRAL):
        return True
    return instrument_jurisdiction == territory


def high_court_of(territory: str) -> list[str]:
    short = territory.removeprefix("IN-")
    return [hc for hc, serves in HIGH_COURTS.items() if short in serves]


def registry() -> list[dict]:
    """Every territory with its kind, its High Court(s) and the honest state of its sources: `not_checked` for all categories until a person verifies them."""
    rows = [{"code": CENTRAL, "name": name_of(CENTRAL), "kind": "country", "high_courts": [], "confirmed": False,
             "sources": {"legislation": "partially_covered", "gazette": "temporarily_unavailable", "high_court": "not_applicable"}}]
    for kind, table in (("state", STATES), ("union_territory", UNION_TERRITORIES)):
        for short, name in table.items():
            code = _code(short)
            rows.append({"code": code, "name": name, "kind": kind, "high_courts": high_court_of(code), "confirmed": False, "sources": {c: "not_checked" for c in SOURCE_CATEGORIES}})
    return rows
