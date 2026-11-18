"""The legal directory (lib/legal_directory.py): it points to courts, official portals, law reports, rules and legal aid bodies. A link is shown only when the last check found it working and it is on a
government domain or was found on an official page; a private publication never gets a link; nothing here states the law or recommends a lawyer."""

import importlib.util
import json
import re
from datetime import date
from pathlib import Path

import pytest

from lib import legal_directory as D

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 13)


def refresh_module():
    spec = importlib.util.spec_from_file_location("legal_directory_refresh", ROOT / "scripts" / "legal_directory_refresh.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def check(ok=True, gov=True, listed=None, on="2026-11-13", final=None):
    return {"ok": ok, "status": 200 if ok else 0, "final_url": final, "expected_words_found": True, "government_domain": gov, "listed_on_official_page": listed, "checked_on": on}


def test_a_link_is_shown_only_when_it_was_checked_works_and_is_official():
    u = "https://example.gov.in/"
    assert D.link_view(None, {}) == {"url": None, "link_status": "none"}
    assert D.link_view(u, {}, TODAY)["url"] is None and D.link_view(u, {}, TODAY)["link_status"] == "not_confirmed"  # never checked: not shown
    failed = D.link_view(u, {u: check(ok=False)}, TODAY)
    assert failed["url"] is None and failed["link_status"] == "not_confirmed" and "2026-11-13" in failed["link_note"]
    good = D.link_view(u, {u: check(final="https://www.example.gov.in/home")}, TODAY)
    assert good == {"url": "https://www.example.gov.in/home", "link_status": "ok", "checked_on": "2026-11-13", "government_domain": True, "listed_on": None}
    private = D.link_view("https://example.org/", {"https://example.org/": check(gov=False)}, TODAY)
    assert private["url"] is None and private["link_status"] == "not_official"  # works, but not a government domain and no official page links to it
    vouched = D.link_view("https://example.org/", {"https://example.org/": check(gov=False, listed="https://nalsa.gov.in/directory/")}, TODAY)
    assert vouched["url"] == "https://example.org/" and vouched["listed_on"] == "https://nalsa.gov.in/directory/" and vouched["government_domain"] is False


def test_an_old_check_is_still_shown_but_marked_as_due():
    u = "https://example.gov.in/"
    fresh = D.link_view(u, {u: check(on="2026-08-20")}, TODAY)  # 85 days
    old = D.link_view(u, {u: check(on="2026-08-01")}, TODAY)  # 104 days
    assert "link_note" not in fresh and old["url"] == u and "due for a re-check" in old["link_note"] and "104" in old["link_note"]


def test_the_curated_file_is_well_formed_and_private_publications_get_no_address():
    entries = json.loads((ROOT / "data" / "legal_directory" / "curated.json").read_text(encoding="utf-8"))["entries"]
    ids = [e["id"] for e in entries]
    sections = {s for s, _ in D.SECTIONS}
    assert len(ids) == len(set(ids)) and len(entries) >= 60
    for e in entries:
        assert e["section"] in sections and e["name"].strip() and 20 <= len(e["what"]) <= 420, e["id"]
        if e.get("official") is False:
            assert "url" not in e, e["id"]  # SCC, AIR, subscription databases: named, never linked
        if e.get("url"):
            assert e["url"].startswith("https://") and e.get("expect"), e["id"]
            host = re.sub(r"^https://([^/]+).*$", r"\1", e["url"])
            assert host.endswith((".gov.in", ".nic.in")) or e.get("vouched_by", "").startswith("https://"), e["id"]  # a non-government address must name the official page that links to it
    text = json.dumps(entries)
    assert not re.search(r"\b(section|s\.)\s*\d", text, re.I)  # the directory names Acts; it never quotes a section number (only three Articles of the Constitution)
    assert set(re.findall(r"Article (\d+)", text)) == {"124", "214", "233"}
    assert not re.search(r"\(\d{4}\) \d+ SCC \d+|AIR \d{4} SC \d+|\d{4} INSC \d+", text)  # citation FORMS only, never a citation
    for word in ("lied", "fraud", "best lawyer", "recommended lawyer", "guarantee"):
        assert word not in text.lower()


def test_every_court_and_body_the_owner_named_has_an_entry():
    names = " | ".join(e["name"] for e in json.loads((ROOT / "data" / "legal_directory" / "curated.json").read_text(encoding="utf-8"))["entries"]).lower()
    for wanted in ("supreme court", "high courts", "district and sessions", "civil judge (senior division)", "civil judge (junior division)", "munsif", "chief judicial magistrate", "first class", "second class",
                   "small cause", "lok adalat", "board of revenue", "commissioner", "collector", "tehsildar", "naib tehsildar", "tribunal", "nalsa", "state legal services", "district legal services",
                   "supreme court rules, 2013", "supreme court cases (scc)", "all india reporter (air)", "india code", "gazette"):
        assert wanted in names, wanted
    third = next(e for e in json.loads((ROOT / "data" / "legal_directory" / "curated.json").read_text(encoding="utf-8"))["entries"] if e["id"] == "court-jmsc")
    assert "Third Class" in third["note"] and "no such class today" in third["note"]  # the owner asked for a third class: the directory says plainly that it no longer exists


HC_PAGE = """<ul><li><a href="http://bombayhighcourt.nic.in/" target="_blank">Bombay High Court</a></li><li><a href="https://njdg.ecourts.gov.in/hcnjdg_v2/">High Court NJDG</a></li>
<li><a href="http://thc.nic.in/">Tripura High Court</a></li><li><a href="http://old.example/">Tripura High Court</a></li><li><a href="http://allahabadhighcourt.in/">Allahabad High Court</a></li></ul>"""
SLSA_PAGE = """<main>List of Names and Addresses Executive Chairmen and Members Secretaries of State Legal Services Authorities.<table>
<tr><td>BIHAR</td><td>Hon'ble Mr. Justice A. Person<br>Executive Chairman,<br>Sh. Some Body<br>Member Secretary,<br>PATNA - 800 001.</td><td>O: 0612-2508943, 2508390<br>F:2201390<br>E-mail: ms[dot]x[at]gov[dot]in<br>
Web: <a href="http://www.patnahighcourt.gov.in/bslsa">www.patnahighcourt.gov.in/bslsa</a></td></tr>
<tr><td>ODISHA</td><td>Sh. Another Person<br>Member Secretary,</td><td>O: 0671-2307678<br>E-mail: o[at]gmail[dot]com</td></tr>
<tr><td>CHANDIGARH (UNIONTERRITORY)</td><td>UT of Chandigarh.<br>CHANDIGARH - 160009</td><td>(O) 0172-2742999<br>Web: <a href="https://chandigarh.nalsa.gov.in/">chandigarh.nalsa.gov.in</a></td></tr>
</table></main><a href="https://nalsa.gov.in/feedback/">Feedback</a><p>DELHI</p>"""


def test_the_official_pages_are_read_into_plain_facts_without_peoples_names_or_emails():
    m = refresh_module()
    hcs = m.parse_high_courts(HC_PAGE)
    assert hcs == [{"name": "Allahabad High Court", "url": "http://allahabadhighcourt.in/"}, {"name": "Bombay High Court", "url": "http://bombayhighcourt.nic.in/"}, {"name": "Tripura High Court", "url": "http://thc.nic.in/"}]
    slsa = m.parse_slsa(SLSA_PAGE)
    assert slsa == [{"state": "Bihar", "website": "http://www.patnahighcourt.gov.in/bslsa", "office_phone": "0612-2508943, 2508390"}, {"state": "Odisha", "website": None, "office_phone": "0671-2307678"},
                    {"state": "Chandigarh", "website": "https://chandigarh.nalsa.gov.in/", "office_phone": "0172-2742999"}]  # a city line ("CHANDIGARH - 160009") is not a new heading; text after the footer is ignored
    kept = json.dumps(slsa)
    assert "Person" not in kept and "Body" not in kept and "[at]" not in kept and "gmail" not in kept
    assert m.parse_slsa("<p>nothing here</p>") == [] and m.parse_high_courts("") == []


def test_a_non_government_address_counts_only_if_a_government_page_really_links_to_it(monkeypatch):
    m = refresh_module()
    pages = {"https://nalsa.gov.in/": '<a href="https://nalsa15100.in/">Helpline</a>', "https://evil.example/": '<a href="https://nalsa15100.in/">x</a>'}
    monkeypatch.setattr(m, "fetch", lambda url, timeout=30: (200, url, pages.get(url, "")))
    assert m.listed_on("https://nalsa15100.in/", "https://nalsa.gov.in/") is True
    assert m.listed_on("https://other.in/", "https://nalsa.gov.in/") is False  # the official page does not mention it
    assert m.listed_on("https://nalsa15100.in/", "https://evil.example/") is False  # the vouching page must itself be a government page
    assert m.official_host("https://x.gov.in/a") and m.official_host("http://y.nic.in") and not m.official_host("https://gov.in.example.com/") and not m.official_host("https://fakegov.in/")


@pytest.fixture
def small(tmp_path, monkeypatch):
    curated = {"entries": [
        {"id": "court-supreme", "section": "courts", "order": 1, "name": "Supreme Court of India", "what": "The highest court of India, for this test only.", "law": "Constitution of India, Article 124", "url": "https://www.sci.gov.in/", "expect": ["x"], "official": True},
        {"id": "jud-scc", "section": "judgments_and_reporters", "name": "Supreme Court Cases (SCC)", "what": "A private law report, named here for this test only.", "official": False},
        {"id": "aid-nalsa", "section": "legal_aid", "order": 1, "name": "National Legal Services Authority (NALSA)", "what": "The national body for free legal aid, for this test.", "url": "https://nalsa.gov.in/", "expect": ["x"], "official": True},
        {"id": "portal-dead", "section": "portals", "name": "A portal whose address failed", "what": "An entry whose address did not answer when checked.", "url": "https://dead.gov.in/", "expect": ["x"], "official": True},
    ]}
    lists = {"retrieved_on": "2026-11-13", "high_courts": {"source": "https://ecourts.gov.in/list", "items": [{"name": "Bombay High Court", "url": "http://bombayhighcourt.nic.in/"}, {"name": "Patna High Court", "url": "http://patnahighcourt.gov.in/"}]},
             "state_legal_services": {"source": "https://nalsa.gov.in/directory/", "items": [{"state": "Goa", "website": "http://goa.nalsa.gov.in", "office_phone": "0832-2492614"}, {"state": "Odisha", "website": None, "office_phone": "0671-2307678"},
                                                                                              {"state": "Jharkhand", "website": "http://www.jhalsa.org/", "office_phone": "0651-2481520"}]}}
    checks = {"checked_on": "2026-11-13", "results": {
        "https://www.sci.gov.in/": check(), "https://nalsa.gov.in/": check(), "https://dead.gov.in/": check(ok=False), "http://bombayhighcourt.nic.in/": check(final="https://bombayhighcourt.nic.in/"),
        "http://patnahighcourt.gov.in/": check(), "http://goa.nalsa.gov.in": check(), "http://www.jhalsa.org/": check(gov=False, listed="https://nalsa.gov.in/directory/")}}
    for name, body in (("curated.json", curated), ("official_lists.json", lists), ("link_checks.json", checks)):
        (tmp_path / name).write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(D, "DATA", tmp_path)
    D.reset()
    yield
    D.reset()


def ids(**kw):
    return [i["id"] for i in D.search(today=TODAY, **kw)["items"]]


def test_the_directory_can_be_searched_by_words_section_and_state(small):
    everything = D.search(today=TODAY)
    by_id = {i["id"]: i for i in everything["items"]}
    assert set(by_id) == {"court-supreme", "jud-scc", "aid-nalsa", "portal-dead", "hc-site-bombayhighcourt", "hc-site-patnahighcourt"}
    assert "not been reviewed by a lawyer" in everything["note"] and everything["links_checked_on"] == "2026-11-13" and [s["id"] for s in everything["sections"]][0] == "courts"
    assert by_id["court-supreme"]["url"] == "https://www.sci.gov.in/" and by_id["court-supreme"]["checked_on"] == "2026-11-13"
    assert by_id["jud-scc"]["url"] is None and by_id["jud-scc"]["official"] is False  # a private publication: named, no link
    assert by_id["portal-dead"]["url"] is None and by_id["portal-dead"]["link_status"] == "not_confirmed"  # shown without its address
    assert by_id["hc-site-bombayhighcourt"]["url"] == "https://bombayhighcourt.nic.in/" and "Goa" in by_id["hc-site-bombayhighcourt"]["states"]
    assert ids(q="highest court") == ["court-supreme"] and ids(section="legal_aid") == ["aid-nalsa"] and ids(q="zzznothing") == []
    assert ids(section="high_court_websites", state="goa") == ["hc-site-bombayhighcourt"]
    with pytest.raises(ValueError):
        D.search(section="nonsense")


def test_legal_aid_gives_the_national_bodies_and_the_states_own_authority(small):
    top = D.legal_aid(today=TODAY)
    assert "does not represent anyone" in top["note"] and [n["id"] for n in top["national"]] == ["aid-nalsa"] and top["state"] is None and top["states"] == ["Goa", "Odisha", "Jharkhand"]
    goa = D.legal_aid("goa", TODAY)["state"]
    assert goa["name"] == "Goa State Legal Services Authority" and goa["url"] == "http://goa.nalsa.gov.in" and goa["office_phone"] == "0832-2492614" and goa["source"] == "https://nalsa.gov.in/directory/" and "District Legal Services Authority" in goa["district_note"]
    odisha = D.legal_aid("Odisha", TODAY)["state"]
    assert odisha["url"] is None and "lists no website" in odisha["link_note"] and odisha["office_phone"] == "0671-2307678"  # nothing is made up for a missing website
    jh = D.legal_aid("Jharkhand", TODAY)["state"]
    assert jh["url"] == "http://www.jhalsa.org/" and jh["government_domain"] is False and jh["listed_on"] == "https://nalsa.gov.in/directory/"  # not a government domain, but NALSA's own page lists it
    with pytest.raises(LookupError):
        D.legal_aid("Atlantis", TODAY)


def test_the_api_serves_the_real_directory_and_refuses_unknown_sections_and_states(user_a):
    got = user_a.get("/legal-directory", params={"q": "supreme court of india", "section": "courts"}).json()
    assert [i["id"] for i in got["items"]] == ["court-supreme"] and "not been reviewed by a lawyer" in got["note"]
    assert len(user_a.get("/legal-directory", params={"section": "high_court_websites"}).json()["items"]) == 25
    assert [i["name"] for i in user_a.get("/legal-directory", params={"section": "high_court_websites", "state": "Goa"}).json()["items"]] == ["Bombay High Court"]
    assert user_a.get("/legal-directory", params={"section": "nonsense"}).status_code == 422
    aid = user_a.get("/legal-directory/legal-aid", params={"state": "Telangana"}).json()
    assert aid["state"]["name"] == "Telangana State Legal Services Authority" and "does not represent anyone" in aid["note"] and any(n["id"] == "aid-nalsa" for n in aid["national"])
    assert user_a.get("/legal-directory/legal-aid", params={"state": "Atlantis"}).status_code == 404


def test_the_directory_needs_a_signed_in_user_and_the_app_code_makes_no_network_call(client):
    assert client.get("/legal-directory").status_code in (401, 403) and client.get("/legal-directory/legal-aid").status_code in (401, 403)
    text = (ROOT / "lib" / "legal_directory.py").read_text(encoding="utf-8") + (ROOT / "routers" / "legal_directory.py").read_text(encoding="utf-8")
    for banned in ("urllib", "requests", "httpx", "aiohttp", "socket", "lib.ai", "ask_json", "lib.db"):
        assert banned not in text, banned  # the app only reads the files; the checking is done by the script, by a person, on purpose


def test_the_real_data_files_load_and_nothing_unchecked_is_ever_shown():
    D.reset()
    try:
        got = D.search()
        raw = json.loads((ROOT / "data" / "legal_directory" / "link_checks.json").read_text(encoding="utf-8"))["results"]
        ok_addresses = {r.get("final_url") or u for u, r in raw.items() if r["ok"]} | {u for u, r in raw.items() if r["ok"]}
        shown = [i for i in got["items"] if i["url"]]
        assert len(got["items"]) >= 90 and len(shown) >= 40
        assert all(i["url"] in ok_addresses and i["link_status"] == "ok" and i["checked_on"] for i in shown)
        assert sum(1 for i in got["items"] if i["section"] == "high_court_websites") == 25
        aid = D.legal_aid()
        assert len(aid["states"]) >= 36 and D.legal_aid("Telangana")["state"]["name"] == "Telangana State Legal Services Authority"
    finally:
        D.reset()


def test_law_commission_reports_are_listed_as_recommendations_with_checked_official_links(user_a):
    got = user_a.get("/legal-directory", params={"section": "law_commission"}).json()
    items = got["items"]
    assert len(items) >= 25 and all(i["section"] == "law_commission" for i in items)
    assert {"lci-278", "lci-279", "lci-289"} <= {i["id"] for i in items}
    for i in items:
        assert "is not law" in i["what"] and "does not copy the report's text" in (i.get("note") or ""), i["id"]  # a recommendation, never a statement of the law
        assert i["link_status"] == "ok" and i["url"].startswith("https://") and i["government_domain"] is True, i["id"]  # shown only because the app's own check found it working
    scans = [i for i in items if "could not be read by the program" in i["what"]]
    assert {i["id"] for i in scans} == {"lci-265", "lci-278"}  # a title that is only what the file name says is marked as such, not dressed up
    assert not re.search(r"\b(section|s\.)\s*\d", json.dumps(items), re.I)
