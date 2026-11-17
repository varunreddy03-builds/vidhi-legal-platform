"""Looks one case citation up in a source and says what was found, using only these labels:

  FOUND_MATCHES          one case was found and its names, year, court and (where the draft gave them) neutral and report citations all agree
  DETAILS_DIFFER         a case was found but something the draft says differs from the source (the differences are listed, in neutral words)
  COULD_NOT_CHECK        the check could not be completed or could not be made with confidence: source down or limited, a daily cap reached, a citation that
                         has only an SCC or AIR number, more than one possible case, or a case found whose report number the source does not show
  NOT_FOUND_FULL_SEARCH  see FULL_SEARCH below: the only way a case is ever reported as not found

(QUOTE_NOT_FOUND and MAY_NOT_SUPPORT belong to the quote and proposition steps (quotes.py, propositions.py) and are not produced here.)

FULL_SEARCH, defined in code and nowhere else: the case was searched by neutral citation, by case name with year, and by party names, and EVERY one of those
searches reached the source and got a definitive reply that was empty. If the draft has no neutral citation, or only an SCC/AIR number, or names no parties,
those searches cannot all be made, so the answer is COULD_NOT_CHECK, never "not found". A false "not found" is the most dangerous mistake this tool can make.

Nothing returned here contains judgment text: only the citation, the label, the reason, the source URL, the queries and the times."""

import re
from dataclasses import dataclass, field

from lib.refcheck.citations import Reference
from lib.refcheck.sources import Attempt, Candidate, SourceDown, cost_per_lookup_inr, now_iso

FOUND_MATCHES = "FOUND_MATCHES"
DETAILS_DIFFER = "DETAILS_DIFFER"
COULD_NOT_CHECK = "COULD_NOT_CHECK"
NOT_FOUND_FULL_SEARCH = "NOT_FOUND_FULL_SEARCH"
FULL_SEARCH = ("neutral", "name_year", "parties")

_STOP = frozenset("vs versus and the of ors anr others another ltd limited pvt private co company shri smt mr mrs dr".split())
_COURTS = {  # what a court code in a citation stands for, as the source words it
    "SC": "supreme court", "INSC": "supreme court", "DEL": "delhi", "DHC": "delhi", "BOM": "bombay", "BHC": "bombay", "CAL": "calcutta", "MAD": "madras", "KAR": "karnataka",
    "KER": "kerala", "ALL": "allahabad", "P&H": "punjab", "PUNJ": "punjab", "GUJ": "gujarat", "RAJ": "rajasthan", "PAT": "patna", "ORI": "orissa", "MP": "madhya pradesh",
    "AP": "andhra pradesh", "TELANGANA": "telangana", "TS": "telangana", "GAU": "gauhati", "HP": "himachal", "J&K": "jammu", "JHAR": "jharkhand", "UTT": "uttarakhand",
}
_TITLE = re.compile(r"^(?P<a>.+?)\s+(?:vs\.?|versus|v\.)\s+(?P<b>.+?)\s+on\s+\d{1,2}\s+\w+,?\s+(?P<year>(?:19|20)\d{2})\s*$", re.I)


class LookupCapExceeded(Exception):
    pass


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]{3,}", s.lower()) if t not in _STOP}


def _side_matches(a: str, b: str) -> bool:
    x, y = _tokens(a), _tokens(b)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= 0.6


def _title_parts(title: str) -> tuple[str, str, int | None]:
    m = _TITLE.match(title.strip())
    if m:
        return m.group("a"), m.group("b"), int(m.group("year"))
    y = re.search(r"\b((?:19|20)\d{2})\b\s*$", title)
    parts = re.split(r"\s+(?:vs\.?|versus|v\.)\s+", title, maxsplit=1, flags=re.I)
    return (parts[0], re.sub(r"\s+on\s+.*$", "", parts[1]) if len(parts) > 1 else "", int(y.group(1)) if y else None)


def party_relation(ref: Reference, cand_title: str) -> str:
    """'same' | 'reversed' | 'differ' | 'unknown' (the draft named no parties)."""
    a, b = ref.parties
    if not (a and b):
        return "unknown"
    ca, cb, _ = _title_parts(cand_title)
    if _side_matches(a, ca) and _side_matches(b, cb):
        return "same"
    if _side_matches(a, cb) and _side_matches(b, ca):
        return "reversed"
    return "differ"


def court_ok(ref: Reference, cand_court: str) -> bool | None:
    """True/False, or None when the draft's court code is not one VIDHI can read (then the court is not compared, and that is said)."""
    want = _COURTS.get(ref.court.upper().replace(" ", ""))
    if not want:
        return None
    return want in cand_court.lower()


def plan(ref: Reference) -> list[tuple[str, str]]:
    """The searches that can be made for this reference, in order. Searches that need something the draft did not give are simply not in the list."""
    out: list[tuple[str, str]] = []
    if ref.neutral:
        out.append(("neutral", f'"{ref.neutral.replace(":", " ")}"'))
    a, b = ref.parties
    if a and b and ref.year:
        out.append(("name_year", f"{a} vs {b} {ref.year}"))
    if a and b:
        out.append(("parties", f"{a} vs {b}"))
    if ref.report:
        out.append(("report", f'"{ref.report}"'))  # informational: a source may not index report numbers, so this never counts towards "not found"
    return out


@dataclass
class Result:
    label: str
    reason: str
    attempts: list[Attempt] = field(default_factory=list)
    differences: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    source_url: str = ""
    matched_title: str = ""
    confirmed: dict = field(default_factory=dict)  # which details the source itself confirmed: neutral, report, names, year, court
    full_search: bool = False
    cost_inr: float = 0.0
    checked_at: str = field(default_factory=now_iso)
    doc_blocks: list = field(default_factory=list, repr=False)  # the matched judgment's paragraphs, IN MEMORY for the quote check only: report.build empties it, nothing stores it


def is_full_search(ref: Reference, attempts: list[Attempt]) -> bool:
    """The definition of a full search (see the module note). True only if every one of FULL_SEARCH was made and each was reachable and definitively empty."""
    by = {a.strategy: a for a in attempts if a.strategy in FULL_SEARCH}
    return all(s in by and by[s].status == "empty" for s in FULL_SEARCH) and bool(ref.neutral and ref.parties[0] and ref.parties[1] and ref.year)


def _report_cites(text: str, reporter: str) -> set[str]:
    """Citations of the same reporter shown near the top of a judgment (where a source prints its 'equivalent citations'), reduced to digits so spelling does not matter."""
    head = text[:4000]
    found: set[str] = set()
    if reporter == "SCC":
        for m in re.finditer(r"(?:\((\d{4})\)\s*(\d{1,3})|(\d{4})\s*\((\d{1,3})\))\s*SCC\s*(?!OnLine)(\d{1,5})", head):
            found.add(f"{m.group(1) or m.group(3)} {m.group(2) or m.group(4)} {m.group(5)}")
    elif reporter == "AIR":
        for m in re.finditer(r"AIR\s*(\d{4})\s*([A-Za-z]{2,8})\s*(\d{1,5})", head):
            found.add(f"{m.group(1)} {m.group(2).upper()} {m.group(3)}")
    elif reporter == "SCC OnLine":
        for m in re.finditer(r"(\d{4})\s*SCC\s*OnLine\s*([A-Za-z]{2,8})\s*(\d{1,6})", head):
            found.add(f"{m.group(1)} {m.group(2).upper()} {m.group(3)}")
    elif reporter == "SCR":
        for m in re.finditer(r"[\[(](\d{4})[\])]\s*(\d{1,3}|Supp\.?)\s*SCR\s*(\d{1,5})", head):
            found.add(f"{m.group(1)} {m.group(2).lower()} {m.group(3)}")
    return found


def _report_key(ref: Reference) -> str:
    n = re.findall(r"[A-Za-z]+|\d+", ref.report)
    if ref.reporter == "SCC":
        return f"{ref.year} {ref.volume} {ref.start_page}"
    if ref.reporter in ("AIR", "SCC OnLine"):
        return f"{ref.year} {ref.court.upper()} {ref.start_page}"
    if ref.reporter == "SCR":
        return f"{ref.year} {ref.volume.lower()} {ref.start_page}"
    return " ".join(n)


async def check_case(ref: Reference, source, *, reserve=None) -> Result:
    """`source` is an adapter (search, fetch, url_for, name). `reserve` is an optional async function called before EVERY request to the source; it raises LookupCapExceeded when the
    organisation's daily lookup limit is used up."""
    attempts: list[Attempt] = []
    cands: dict[str, Candidate] = {}
    spent = 0.0

    async def ask(strategy: str, query: str) -> list[Candidate] | None:
        nonlocal spent
        try:
            if reserve:
                await reserve(1)
            found = await source.search(query)
        except LookupCapExceeded:
            attempts.append(Attempt(strategy, query, source.name, now_iso(), "down", error="The daily lookup limit for your organisation has been reached."))
            return None
        except SourceDown as exc:
            attempts.append(Attempt(strategy, query, source.name, now_iso(), "down", error=exc.reason, cost_inr=0.0))
            return None
        spent += cost_per_lookup_inr()
        attempts.append(Attempt(strategy, query, source.name, now_iso(), "results" if found else "empty", n=len(found), cost_inr=cost_per_lookup_inr()))
        return found

    searches = plan(ref)
    if not searches:
        return Result(COULD_NOT_CHECK, "The citation was too incomplete to search for: it names no parties and has no neutral citation.", attempts)
    covers = getattr(source, "covers", None)  # a local dataset knows how recent its newest judgment is
    if covers and not covers(ref.year):
        return Result(COULD_NOT_CHECK, f"The draft cites {ref.year}, which is later than the newest judgment in {source.name} (data as of {source.as_of.isoformat()}), so this source cannot check it.", attempts)

    anchor_via = ""
    anchor: tuple[Candidate, str, list] | None = None  # (candidate, fetched judgment text, its paragraph blocks)
    fetch_down = ""
    for strategy, query in searches:
        found = await ask(strategy, query)
        if not found:
            continue
        for c in found:
            cands.setdefault(c.doc_id, c)
        if anchor:
            break
        # a candidate is "confident" when the neutral citation is in its own text, or (otherwise) when its parties match the draft's
        by_report = strategy == "report" and ref.reporter in getattr(source, "report_series", ())  # a report number of a series this source really indexes identifies one judgment
        if strategy == "neutral" or by_report:
            pool = found[:3]
        else:
            pool = [c for c in found if party_relation(ref, c.title) in ("same", "reversed")]
            consistent = [c for c in pool if not ref.year or (_title_parts(c.title)[2] in (ref.year, ref.year - 1))]  # a decision year the report year can follow
            # several cases share these names and none fits the year: that is ambiguity, not a mismatch to report
            pool = consistent[:3] if consistent else (pool if len(pool) == 1 else [])
        for c in pool:
            try:
                if reserve:
                    await reserve(1)
                doc = await source.fetch(c.doc_id)
            except LookupCapExceeded:
                fetch_down = "The daily lookup limit for your organisation has been reached."
                break
            except SourceDown as exc:
                fetch_down = exc.reason
                continue
            spent += cost_per_lookup_inr()
            head = doc["text"][:4000]
            if strategy == "neutral":
                n = re.sub(r"\D+", " ", ref.neutral).split()
                if re.search(r"\b" + r"\D{0,6}".join(n) + r"\b", head):
                    anchor = (c, doc["text"], doc.get("blocks") or [])
                    anchor_via = strategy
                    break
            elif by_report:
                if _report_key(ref) in _report_cites(doc["text"], ref.reporter):  # only if the fetched record itself carries that report number
                    anchor = (c, doc["text"], doc.get("blocks") or [])
                    anchor_via = strategy
                    break
            else:
                anchor = (c, doc["text"], doc.get("blocks") or [])
                anchor_via = strategy
                break
        if anchor:
            break

    cost = round(spent, 2)
    if anchor:
        c, text, blocks = anchor
        diffs: list[str] = []
        confirmed: dict = {}
        rel = party_relation(ref, c.title)
        if rel == "differ":
            diffs.append(f"the draft names the parties as “{ref.parties[0]} v. {ref.parties[1]}”; the source has “{c.title}”")
        elif rel == "reversed":
            diffs.append("the parties are in the opposite order to the source")
        confirmed["names"] = rel == "same"
        _, _, dec_year = _title_parts(c.title)
        if ref.year and dec_year:
            ok = ref.year == dec_year if ref.reporter == "neutral" else ref.year in (dec_year, dec_year + 1)
            confirmed["year"] = ok
            if not ok:
                diffs.append(f"the draft says {ref.year}; the source shows the decision in {dec_year}")
        co = court_ok(ref, c.court)
        confirmed["court"] = co
        if co is False:
            diffs.append(f"the draft's citation is for “{ref.court}”; the source lists the court as “{c.court}”")
        if ref.neutral:
            if anchor_via == "neutral":
                confirmed["neutral"] = True  # the anchor was only accepted because the neutral citation is in its own text
            else:
                # found by names/year/report: the neutral citation the draft gives has NOT been proved by the search, so compare it with the ones the record itself shows
                shown_neutral = {re.sub(r"\D+", " ", m.group(0)).strip() for m in re.finditer(r"\b(?:19|20)\d{2}\s*INSC\s*\d{1,6}\b", text[:4000])}
                mine = re.sub(r"\D+", " ", ref.neutral).strip()
                if mine in shown_neutral:
                    confirmed["neutral"] = True
                elif shown_neutral:
                    confirmed["neutral"] = False
                    diffs.append(f"the draft cites {ref.neutral}; the source shows a different neutral citation for this case")
                else:
                    confirmed["neutral"] = None
        if ref.report and ref.reporter in ("SCC", "AIR", "SCR", "SCC OnLine"):
            shown = _report_cites(text, ref.reporter)
            if not shown:
                confirmed["report"] = None
            elif _report_key(ref) in shown:
                confirmed["report"] = True
            else:
                confirmed["report"] = False
                diffs.append(f"the draft cites {ref.report}; the source shows a different {ref.reporter} citation for this case")
        base = dict(attempts=attempts, source_url=c.url, matched_title=c.title, confirmed=confirmed, cost_inr=cost, doc_blocks=blocks)
        if diffs and anchor_via == "parties" and confirmed.get("year") is False and dec_year and ref.year and ref.year > dec_year:
            # found only by party names, and decided EARLIER than the year the draft cites: many cases share names and a later case of the same parties may simply be missing, so this
            # may be another case. Not reported as a mismatch. (A draft year EARLIER than the found decision cannot be a reporting delay and stays a mismatch.)
            return Result(COULD_NOT_CHECK, f"A case with similar parties was found ({c.title}), but its details differ from the draft's ({'; '.join(diffs)}). It may be a different case with similar names, so this is not reported as a mismatch. Check it by hand.", **base)
        if diffs == ["the parties are in the opposite order to the source"] and anchor_via in ("name_year", "parties"):
            # found only by party names, and nothing else differs: the same names in the other order is often a cross-appeal or a different party listed first, so it proves nothing wrong
            return Result(COULD_NOT_CHECK, f"A case with the same parties in the other order was found ({c.title}), but nothing in it confirms or contradicts the draft's citation. It may be a different case or a cross-appeal. Check it by hand." + (" Report number not verifiable from this source." if ref.reporter in ("SCC", "AIR", "SCC OnLine") and ref.reporter not in getattr(source, "report_series", (ref.reporter,)) else ""), **base)
        if diffs:
            return Result(DETAILS_DIFFER, "A case was found, but these details differ: " + "; ".join(diffs) + ".", differences=diffs, **base)
        if confirmed.get("report") is None and ref.report and not ref.neutral:
            return Result(COULD_NOT_CHECK, f"A case with these parties was found, but the source does not show its {ref.reporter} number, so “{ref.report}” was not confirmed. Check it against the report." + (" Report number not verifiable from this source." if ref.reporter not in getattr(source, "report_series", (ref.reporter,)) else ""), **base)
        if ref.neutral and confirmed.get("neutral") is None:
            return Result(COULD_NOT_CHECK, f"A case with these parties was found, but the source does not show a neutral citation, so “{ref.neutral}” was not confirmed. Check it by hand.", **base)
        if rel == "unknown" and not ref.neutral:
            return Result(COULD_NOT_CHECK, "A case was found, but the draft names no parties to compare.", **base)
        return Result(FOUND_MATCHES, "The case was found and the details checked agree.", **base)

    listing = [{"title": c.title, "court": c.court, "url": c.url} for c in list(cands.values())[:5]]
    full = is_full_search(ref, attempts)
    complete = getattr(source, "complete_for", None)
    if full and not cands and not fetch_down and complete is not None and not complete(ref.year):
        # every search ran and found nothing, but this source is not known to hold every judgment of that year: an absence here proves nothing
        return Result(COULD_NOT_CHECK, f"Nothing was found in {source.name} by any of the searches, but this source is not known to hold every judgment of {ref.year or 'that year'}, so this is not reported as 'not found'.", attempts=attempts, full_search=False, cost_inr=cost)
    if full and not cands and not fetch_down:
        return Result(NOT_FOUND_FULL_SEARCH, f"Not found in {source.name}: searched by neutral citation, by case name with year and by party names, and each search reached the source and returned nothing. This does not prove that no such case exists.", attempts=attempts, full_search=True, cost_inr=cost)
    down = [a for a in attempts if a.status == "down"]
    if down or fetch_down:
        why = (down[0].error if down else fetch_down)
        reason = f"The check could not be completed: {why}"
    elif cands:
        reason = "Possible cases were found but none could be matched with confidence. Check them yourself."
    elif not ref.neutral:
        reason = "Not found by the searches that could be made, but a full search was not possible: the draft has no neutral citation, so this is not reported as “not found”."
    else:
        reason = "Not found by every search that could be made, but a full search was not possible with what the draft gives, so this is not reported as “not found”."
    return Result(COULD_NOT_CHECK, reason, attempts=attempts, candidates=listing, cost_inr=cost)
