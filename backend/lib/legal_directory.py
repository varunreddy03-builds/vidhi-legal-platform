"""The legal directory: where things are (courts, tribunals, revenue courts, official portals, Acts and gazettes, law reports, court rules, legal aid bodies). It POINTS; it never states what the law
says, never recommends a lawyer or a book, and never copies a court's or a publisher's text. Plain code, no model, no network call from the app.

Where the facts come from (backend/data/legal_directory):
- curated.json          short descriptions written for VIDHI. NOT reviewed by a lawyer: every answer says so.
- official_lists.json   the High Court websites (from the eCourts page that lists them) and each State's Legal Services Authority website and office phone (from NALSA's directory page), with the
                        page and the date they were read. Written by scripts/legal_directory_refresh.py.
- link_checks.json      the result of requesting every address, with the date. Written by the same script.

Rules enforced here:
- An address is shown only if the last check found it working. Otherwise the entry is shown without a link and says the address was not confirmed. A link is never shown unchecked.
- An address is shown only if it is on a government domain (.gov.in or .nic.in) or the check found it linked from an official government page (the page is recorded with the link).
- Every link carries the date it was checked; after STALE_DAYS it is marked as due for a re-check (it is still shown, with that warning).
- A private publication (SCC, AIR, a subscription database) is labelled as not official and gets no link."""

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from lib import court_hierarchy

DATA = Path(__file__).resolve().parent.parent / "data" / "legal_directory"
STALE_DAYS = 90
SECTIONS = (
    ("courts", "Courts"), ("revenue", "Revenue courts"), ("tribunals", "Tribunals and commissions"), ("high_court_websites", "High Court websites"), ("portals", "Official portals"),
    ("legislation", "Acts, rules and gazettes"), ("judgments_and_reporters", "Judgments and law reports"), ("rules_and_formats", "Court rules and filing formats"),
    ("legal_aid", "Legal aid"), ("reference_works", "Books and databases"),
)
NOT_REVIEWED = "These descriptions were written for VIDHI and have not been reviewed by a lawyer. Names, powers and money limits of subordinate and revenue courts differ from State to State. This is a directory, not legal advice."
LEGAL_AID_NOTE = "VIDHI is a tool for lawyers. It does not represent anyone or give legal advice. A person who needs a lawyer and cannot afford one can apply to the legal services authorities below."


def _read(name: str) -> dict:
    f = DATA / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


@lru_cache(maxsize=1)
def _load() -> dict:
    curated, lists, checks = _read("curated.json"), _read("official_lists.json"), _read("link_checks.json")
    return {"entries": curated.get("entries", []), "lists": lists, "checks": checks.get("results", {}), "checked_on": checks.get("checked_on"), "lists_on": lists.get("retrieved_on")}


def reset() -> None:
    _load.cache_clear()


def link_view(url: str | None, checks: dict, today: date | None = None) -> dict:
    """What may be shown for an address: the link only when the last check found it working AND it is on a government domain or the check found it linked from an official page."""
    if not url:
        return {"url": None, "link_status": "none"}
    c = checks.get(url)
    if not c or not c.get("ok"):
        return {"url": None, "link_status": "not_confirmed", "link_note": "The address could not be confirmed" + (f" on {c['checked_on']}" if c else "") + ", so it is not shown."}
    age = ((today or date.today()) - date.fromisoformat(c["checked_on"])).days
    if not (c.get("government_domain") or c.get("listed_on_official_page")):
        return {"url": None, "link_status": "not_official", "link_note": "The address is not on a government domain and was not found on an official page, so it is not shown."}
    out = {"url": c.get("final_url") or url, "link_status": "ok", "checked_on": c["checked_on"], "government_domain": bool(c.get("government_domain")), "listed_on": c.get("listed_on_official_page") or None}
    if age > STALE_DAYS:
        out["link_note"] = f"Last checked {age} days ago; it is due for a re-check."
    return out


def _entry_view(e: dict, checks: dict, today: date | None) -> dict:
    private = e.get("official") is False
    link = {"url": None, "link_status": "none"} if private else link_view(e.get("url"), checks, today)
    return {"id": e["id"], "section": e["section"], "name": e["name"], "what": e["what"], "law": e.get("law"), "note": e.get("note"), "official": not private, "app_link": e.get("app_link"),
            **link}


def entries(today: date | None = None) -> list[dict]:
    d = _load()
    out = [_entry_view(e, d["checks"], today) for e in sorted(d["entries"], key=lambda e: (e.get("order", 999), e["name"]))]
    hc = d["lists"].get("high_courts", {})
    for h in hc.get("items", []):
        out.append({"id": "hc-site-" + "".join(ch for ch in h["name"].lower() if ch.isalnum()), "section": "high_court_websites", "name": h["name"],
                    "what": "The High Court's own website: judgments, orders, cause lists, rules and notices.", "law": None, "note": None, "official": True, "app_link": None,
                    "states": _states_for_court_name(h["name"]), **link_view(h["url"], d["checks"], today)})
    return out


_NAME_TO_CODE = {"allahabad": "9_13", "andhra pradesh": "28_2", "bombay": "27_1", "calcutta": "19_16", "chhattisgarh": "22_18", "delhi": "7_26", "gauhati": "18_6", "gujarat": "24_17", "orissa": "21_11",
                 "himachal pradesh": "2_5", "jammu & kashmir": "1_12", "jharkhand": "20_7", "karnataka": "29_3", "kerala": "32_4", "madhya pradesh": "23_23", "madras": "33_10", "manipur": "14_25",
                 "meghalaya": "17_21", "patna": "10_8", "punjab & haryana": "3_22", "rajasthan": "8_9", "sikkim": "11_24", "telangana": "36_29", "tripura": "16_20", "uttarakhand": "5_15"}


def _states_for_court_name(name: str) -> list[str]:
    low = name.lower().replace("high court of", "").replace("high court", "").strip()
    return court_hierarchy.states_served(_NAME_TO_CODE.get(low))


def search(q: str = "", section: str | None = None, state: str | None = None, today: date | None = None) -> dict:
    """Entries whose name, description or law contain every word of `q`; optionally one section; optionally the High Court site(s) serving one State."""
    if section and section not in dict(SECTIONS):
        raise ValueError(f"Unknown section '{section}'")
    words = [w for w in (q or "").lower().split() if w]
    items = []
    for e in entries(today):
        if section and e["section"] != section:
            continue
        if state and e["section"] == "high_court_websites" and state.strip().casefold() not in [s.casefold() for s in e.get("states", [])]:
            continue
        hay = " ".join(str(e.get(k) or "") for k in ("name", "what", "law", "note")).lower()
        if all(w in hay for w in words):
            items.append(e)
    d = _load()
    return {"items": items, "sections": [{"id": i, "title": t} for i, t in SECTIONS], "note": NOT_REVIEWED, "links_checked_on": d["checked_on"], "lists_read_on": d["lists_on"]}


def legal_aid(state: str | None = None, today: date | None = None) -> dict:
    """The national legal aid bodies and, for a State or Union Territory, its Legal Services Authority as listed in NALSA's directory."""
    d = _load()
    national = [e for e in entries(today) if e["section"] == "legal_aid"]
    slsa = d["lists"].get("state_legal_services", {})
    rows = slsa.get("items", [])
    names = [r["state"] for r in rows]
    chosen = None
    if state:
        want = state.strip().casefold().replace("&", "and")
        row = next((r for r in rows if r["state"].casefold() == want), None)
        if row is None:
            raise LookupError(f"No State or Union Territory called '{state}' in NALSA's directory.")
        chosen = {"state": row["state"], "name": f"{row['state']} State Legal Services Authority", "office_phone": row.get("office_phone"), "source": slsa.get("source"), "read_on": d["lists_on"],
                  **link_view(row.get("website"), d["checks"], today),
                  "district_note": "Each district has a District Legal Services Authority, usually at the district court complex. The State authority's website and office list them."}
        if not row.get("website"):
            chosen["link_note"] = "NALSA's directory lists no website for this authority."
    return {"note": LEGAL_AID_NOTE, "national": national, "state": chosen, "states": names, "source": slsa.get("source")}
