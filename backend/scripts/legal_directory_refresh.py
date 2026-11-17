"""Refreshes the legal directory's facts from official pages and checks every address. Run it now and then (monthly is sensible): the app shows a link only when the last check found it working.

    C:\\vidhi-tools\\venv2\\Scripts\\python.exe -I -X utf8 backend/scripts/legal_directory_refresh.py [--lists-only] [--checks-only]

It makes ordinary page requests to public official sites, a second apart; it does not log in, fill a form or get past any CAPTCHA.
1. High Court websites: read from the eCourts page that lists them (HC_SOURCE).
2. State Legal Services Authorities: website and office phone of each State and Union Territory, read from NALSA's directory page (SLSA_SOURCE). Names of office holders and e-mail addresses are NOT kept
   (they change, and they are people's details).
3. Every address in data/legal_directory/curated.json and in the two lists is requested once. Result per address: working or not, the final address, whether the expected words are on the page, the date.
Writes data/legal_directory/official_lists.json and data/legal_directory/link_checks.json. An address that fails is kept in the files as failed, so the app can say "address not confirmed" instead of showing it."""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

DATA = Path(__file__).resolve().parent.parent / "data" / "legal_directory"
HC_SOURCE = "https://ecourts.gov.in/ecourts2.0/?p=about_us/highcourts"
SLSA_SOURCE = "https://nalsa.gov.in/directory/"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"  # several government sites refuse a request that does not look like a browser
STATES = ["ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR", "CHHATTISGARH", "GOA", "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JAMMU & KASHMIR", "JHARKHAND", "KARNATAKA", "KERALA", "MADHYA PRADESH",
          "MAHARASHTRA", "MANIPUR", "MEGHALAYA", "MIZORAM", "NAGALAND", "ODISHA", "PUNJAB", "RAJASTHAN", "SIKKIM", "TELANGANA", "TAMIL NADU", "TRIPURA", "UTTAR PRADESH", "UTTARAKHAND", "WEST BENGAL",
          "ANDAMAN & NICOBAR ISLANDS", "CHANDIGARH", "DADRA & NAGAR HAVELI", "DAMAN & DIU", "DELHI", "LADAKH", "LAKSHADWEEP", "PUDUCHERRY"]


def _curl(url: str, timeout: int) -> tuple[int, str, str] | None:
    """The same request made with the curl program, which several government sites answer when they refuse Python's own connection. None when curl is not installed."""
    exe = shutil.which("curl")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-s", "-L", "-m", str(timeout), "--max-filesize", "3000000", "-A", UA, "-w", "\n%{http_code} %{url_effective}", url], capture_output=True, timeout=timeout + 10, check=False)  # noqa: S603 - fixed program, address from our own data files
        body, _, tail = r.stdout.decode("utf-8", errors="replace").rpartition("\n")
        code, _, final = tail.partition(" ")
        return (int(code) if code.isdigit() else 0), (final.strip() or url), body[:600_000]
    except Exception:  # noqa: BLE001
        return 0, url, ""


def fetch(url: str, timeout: int = 20) -> tuple[int, str, str]:
    """(status, final address, page text). Status 0 = no answer. Certificates are always checked."""
    got = _curl(url, timeout)
    if got is not None:
        return got
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - addresses come from our own data files
            return r.status, r.geturl(), r.read(600_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception:  # noqa: BLE001 - DNS, TLS, timeout: all mean "not confirmed"
        return 0, url, ""


def flat(page: str) -> str:
    """The page as text, with each link's address in square brackets before its words and tags turned into bars."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    t = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>', r" [\1] ", t)
    return re.sub(r"\|[\s|]*", "| ", html.unescape(re.sub(r"<[^>]+>", "|", t)))


def parse_high_courts(page: str) -> list[dict]:
    out, seen = [], set()
    for url, name in re.findall(r'<a[^>]*href="(https?://[^"]+)"[^>]*>\s*([^<]*High Court[^<]*)<', page, flags=re.I):
        name = " ".join(html.unescape(name).split())
        if "njdg" in url.lower() or name.lower() in seen:
            continue  # the first address listed for a court is kept
        seen.add(name.lower())
        out.append({"name": name, "url": url.strip()})
    return sorted(out, key=lambda r: r["name"])


def parse_slsa(page: str) -> list[dict]:
    t = flat(page)
    start = t.find("State Legal Services Authorities.")
    if start < 0:
        return []
    out, cur = [], None
    for tok in (x.strip() for x in t[start:].split("|")):
        if tok.startswith("[https://nalsa.gov.in/feedback"):
            break
        norm = " ".join(tok.upper().replace(" AND ", " & ").split())
        head = next((s for s in STATES if norm == s or norm.startswith(s + " (") or (s == "JAMMU & KASHMIR" and norm == "JAMMU")), None)
        if head and (cur is None or head.title().replace("&", "and") != cur["state"]) and len(tok) <= len(head) + 22:
            cur = {"state": head.title().replace("&", "and"), "website": None, "office_phone": None}
            out.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r"(web|website)\s*:", tok, re.I) and cur["website"] is None:
            m = re.search(r"\[(https?://[^\]]+)\]", tok)
            cur["website"] = m.group(1).strip() if m else None
        m = re.match(r"\(?O\)?\s*:?\s*([0-9][0-9 ,/\-]{5,60})", tok)
        if m and cur["office_phone"] is None:
            cur["office_phone"] = m.group(1).strip(" ,")
    return out


def official_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith(".gov.in") or host.endswith(".nic.in")


def check(url: str, expect: list[str] | None) -> dict:
    status, final, text = fetch(url)
    if status != 200 and url.startswith("http://"):  # an official list may still give the old http address: the same host over https is the same site
        status, final, text = fetch("https://" + url[len("http://"):])
    if status == 0:  # one more try: government sites drop a first connection now and then
        time.sleep(3)
        status, final, text = fetch(url)
    has = None if not expect else any(w.lower() in text.lower() for w in expect)
    gov = official_host(final or url)
    # The expected words guard against a parked or taken-over address. Many government sites build their page in the browser, so the words are not in what a program receives: a site on a
    # government domain that answers normally is accepted without them; any other site must show them.
    ok = status == 200 and (has is not False or gov)
    return {"ok": ok, "status": status, "final_url": final, "expected_words_found": has, "government_domain": official_host(final or url), "listed_on_official_page": None, "checked_on": date.today().isoformat()}


_pages: dict[str, str] = {}


def listed_on(url: str, official_page: str) -> bool:
    """True when `official_page` is on a government domain and its HTML contains the host of `url` (so a government page really links to it)."""
    if not official_host(official_page):
        return False
    if official_page not in _pages:
        _pages[official_page] = fetch(official_page)[2]
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return bool(host) and host in _pages[official_page].lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lists-only", action="store_true")
    ap.add_argument("--checks-only", action="store_true")
    a = ap.parse_args()
    lists_file, checks_file = DATA / "official_lists.json", DATA / "link_checks.json"
    if not a.checks_only:
        s1, _, p1 = fetch(HC_SOURCE)
        s2, _, p2 = fetch(SLSA_SOURCE)
        hcs, slsas = parse_high_courts(p1), parse_slsa(p2)
        if len(hcs) < 20 or len(slsas) < 30:  # a changed page layout must not silently empty the directory
            print(f"refusing to write the lists: {len(hcs)} High Courts (status {s1}) and {len(slsas)} State authorities (status {s2}) were read; the pages may have changed", file=sys.stderr)
            return 1
        body = {"retrieved_on": date.today().isoformat(), "high_courts": {"source": HC_SOURCE, "items": hcs}, "state_legal_services": {"source": SLSA_SOURCE, "items": slsas}}
        lists_file.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        print(f"lists: {len(hcs)} High Courts, {len(slsas)} State authorities ({sum(1 for s in slsas if s['website'])} with a website)")
    if a.lists_only:
        return 0
    lists = json.loads(lists_file.read_text(encoding="utf-8"))
    curated = json.loads((DATA / "curated.json").read_text(encoding="utf-8"))["entries"]
    todo: dict[str, list[str] | None] = {}
    voucher: dict[str, str] = {}  # address -> the official page said to link to it
    for e in curated:
        if e.get("url"):
            todo[e["url"]] = e.get("expect")
            if e.get("vouched_by"):
                voucher[e["url"]] = e["vouched_by"]
    for h in lists["high_courts"]["items"]:
        todo.setdefault(h["url"], ["Court"])
        voucher.setdefault(h["url"], lists["high_courts"]["source"])
    for s in lists["state_legal_services"]["items"]:
        if s["website"]:
            todo.setdefault(s["website"], ["Legal"])
            voucher.setdefault(s["website"], lists["state_legal_services"]["source"])
    results = {}
    for i, (url, expect) in enumerate(todo.items(), 1):
        results[url] = check(url, expect)
        if url in voucher and listed_on(url, voucher[url]):
            results[url]["listed_on_official_page"] = voucher[url]
        print(f"[{i}/{len(todo)}] {'ok  ' if results[url]['ok'] else 'FAIL'} {results[url]['status']} {url}", flush=True)
        time.sleep(1)
    checks_file.write_text(json.dumps({"checked_on": date.today().isoformat(), "results": results}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    bad = [u for u, r in results.items() if not r["ok"]]
    print(f"checked {len(results)} addresses: {len(results) - len(bad)} working, {len(bad)} not confirmed")
    for u in bad:
        print("  not confirmed:", u, results[u]["status"], "expected words found:", results[u]["expected_words_found"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
