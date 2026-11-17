"""The lawyer-checked evaluation set: a loader, a scorer (pure code, no model) and a dated report.

The file is backend/evals/lawyer_set.jsonl, one JSON object per line. A line holds the lawyer's own question, the answer the lawyer checked and the source that answer rests on:

    {"id": "L001", "question": "...", "correct_answer": "...", "source": "Section 138, Negotiable Instruments Act, 1881"}

Required: question, correct_answer, source (a string, or a list of strings when the answer needs several). Accepted names: `answer` or `correct` for correct_answer, `citation` or `sources`
for source. Optional: id (L001, L002 ... when missing), language (default en), must_contain (a list of words or numbers the answer must contain: the lawyer's own key points), expect
("answer", the default, or "could_not_check" when the right behaviour is to say VIDHI cannot check this), note. A line that starts with # and a blank line are ignored.

What is scored, for each case (all by simple word and number rules; a lawyer should read the lines marked partly or wrong):
  answer       right / partly / wrong: the key points of the checked answer are in VIDHI's answer (the lawyer's must_contain list when given, else the numbers and most of the distinctive words)
  citation     named the right source (in a claim's citation, or in the answer text), and whether the quote was verified
  claim labels each claim that is about the checked answer is judged: VERIFIED and agrees = right; VERIFIED but differs = WRONG BUT CONFIDENT; UNSUPPORTED although it agrees = too cautious;
               UNSUPPORTED and differs = right. A claim unrelated to the checked answer is not scored.
  could not check  when the source is not in the verified library (or the lawyer marked the case could_not_check) VIDHI should say it could not check and verify nothing about the law
  wrong but confident  the worst kind, counted on its own: a wrong answer that is not marked as unchecked, or a VERIFIED claim that differs from the checked answer
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from lib import textmatch

DEFAULT_PATH = Path(__file__).resolve().parent / "lawyer_set.jsonl"
MAX = {"question": 2000, "correct_answer": 4000, "source": 500}
ALIASES = {"correct_answer": ("correct_answer", "answer", "correct"), "source": ("source", "citation", "sources")}
EXPECTS = ("answer", "could_not_check")
PERSONAL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\b\d{10}\b|\b\d{4}\s\d{4}\s\d{4}\b")  # an email address, a ten-digit phone number or an Aadhaar-shaped number
HEDGE = re.compile(
    r"cannot verify|could not (?:verify|check)|not (?:been )?(?:verified|checked)|not checked against|unsure|not sure|unclear|do not know|don't know|no verified source|may not|might not", re.I)
ANSWER_RIGHT, ANSWER_PARTLY, ANSWER_WRONG = 0.6, 0.35, 0.0  # share of the checked answer's distinctive words the answer must contain


# ---------- loading ----------
def _first(row: dict, names: tuple[str, ...]):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def load(path: str | Path = DEFAULT_PATH) -> tuple[list[dict], list[str], list[str]]:
    """(cases, problems, warnings). Any problem means the file must be fixed before it is used; warnings are worth reading. Never raises on bad content."""
    p = Path(path)
    cases, problems, warnings, seen_ids, seen_q = [], [], [], set(), set()
    if not p.exists():
        return [], [f"The file {p} does not exist. Put the lawyer-checked questions there, one JSON object per line."], []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"The file could not be read as UTF-8 text ({type(exc).__name__})."], []
    for n, raw in enumerate(lines, start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            problems.append(f"line {n}: not valid JSON")
            continue
        if not isinstance(row, dict):
            problems.append(f"line {n}: not a JSON object")
            continue
        question = str(row.get("question") or row.get("q") or "").strip()
        answer = str(_first(row, ALIASES["correct_answer"]) or "").strip()
        src = _first(row, ALIASES["source"])
        sources = [str(s).strip() for s in src] if isinstance(src, list) else ([str(src).strip()] if src else [])
        sources = [s for s in sources if s]
        expect = str(row.get("expect") or "answer").strip()
        cid = str(row.get("id") or f"L{len(cases) + 1:03d}").strip()
        where = f"line {n} ({cid})"
        if not question:
            problems.append(f"{where}: no question")
        if expect not in EXPECTS:
            problems.append(f"{where}: expect must be one of {EXPECTS}")
        if expect == "answer" and not answer:
            problems.append(f"{where}: no correct_answer")
        if expect == "answer" and not sources:
            problems.append(f"{where}: no source (use expect \"could_not_check\" if no source can be given)")
        for field, value in (("question", question), ("correct_answer", answer), ("source", "; ".join(sources))):
            if len(value) > MAX[field]:
                problems.append(f"{where}: {field} is longer than {MAX[field]} characters")
        if cid in seen_ids:
            problems.append(f"{where}: the id is used twice")
        seen_ids.add(cid)
        key = textmatch.norm(question)
        if key and key in seen_q:
            warnings.append(f"{where}: the same question appears twice")
        seen_q.add(key)
        if PERSONAL.search(question + " " + answer):
            warnings.append(f"{where}: looks like it contains an email address or a phone or ID number. Use no client details at all.")
        must = row.get("must_contain") or []
        if not isinstance(must, list) or not all(isinstance(m, (str, int, float)) for m in must):
            problems.append(f"{where}: must_contain must be a list of words or numbers")
            must = []
        cases.append({"id": cid, "question": question, "correct_answer": answer, "sources": sources, "language": str(row.get("language") or "en"), "must_contain": [str(m) for m in must],
                      "expect": expect, "note": str(row.get("note") or "")[:300]})
    if not cases and not problems:
        problems.append("The file has no cases.")
    return cases, problems, warnings


def file_sha256(path: str | Path = DEFAULT_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ""


# ---------- text helpers ----------
def _words(text: str) -> set[str]:
    return textmatch.distinctive_stems(text)


NUMBER_WORDS = set(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety "
    "hundred thousand lakh lakhs crore crores million first second third fourth fifth sixth seventh eighth ninth tenth once twice".split())


WORD_VALUE = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
              "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
              "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000", "lakh": "100000", "lakhs": "100000", "crore": "10000000", "crores": "10000000",
              "million": "1000000"}


def figures(text: str) -> set[str]:
    """The figures in a text: digits (5,00,000 as 500000) and number words (thirty, ninety, lakh), with a number word and its digits treated as the same figure (thirty = 30). A changed figure
    is the commonest way a legal answer goes wrong."""
    words = re.findall(r"[a-z]+", textmatch.norm(text))
    return set(textmatch.numbers(text)) | {WORD_VALUE.get(w, w) for w in words if w in NUMBER_WORDS}


def says_the_opposite(case_answer: str, answer: str, coverage: float) -> bool:
    """The answer uses (nearly) the checked answer's words but has or lacks a 'not' that the checked answer lacks or has. Only flagged when the words overlap strongly, so a right answer in
    different words is not called wrong for a missing 'not'."""
    return coverage >= ANSWER_RIGHT and bool(case_answer.strip()) and _has_not(answer) != _has_not(case_answer)


_NOT = re.compile(r"\b(?:not|never|cannot|prohibit\w*|forbid\w*)\b|n't")


def _has_not(text: str) -> bool:
    """Does the text say 'not' (not, never, cannot, n't, prohibited)? A bare 'No.' at the start of an answer is left out: it is in right answers and wrong ones alike."""
    return bool(_NOT.search(textmatch.norm(text)))


def _norm_source(s: str) -> str:
    s = textmatch.norm(s)
    s = re.sub(r"\b(?:sec|sec\.|s\.|section|sections)\b\.?", " section ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def source_matches(source: str, cited: str) -> bool:
    """Does `cited` name the same provision or case as `source`? Every number of the source must be in it and most of its other distinctive words."""
    a, b = _norm_source(source), _norm_source(cited)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    numbers = textmatch.numbers(a)
    if numbers and not numbers <= textmatch.numbers(b):
        return False
    stems = _words(re.sub(r"\d+", " ", a))
    if not stems:
        return bool(numbers)
    return len(stems & _words(b)) / len(stems) >= (0.5 if numbers else 0.6)


def _claims(result: dict) -> list[dict]:
    return [c for c in (result.get("claims") or []) if isinstance(c, dict)]


SYSTEM_PARAGRAPHS = ("Not checked against any source", "Note from VIDHI", "System check", "Unresolved evidence", "UNREVIEWED: this answer was written by a program")


def model_words(result: dict) -> str:
    """The answer as the MODEL wrote it: VIDHI's own warnings (the 'not checked against any source' line and the notes it adds) are taken out, so that a refusal is judged on what the model
    said and not on VIDHI's standing banner."""
    paragraphs = str(result.get("answer") or "").split("\n\n")
    return "\n\n".join(p for p in paragraphs if not p.lstrip().startswith(SYSTEM_PARAGRAPHS))


def abstained(result: dict) -> bool:
    """The model said it could not check, and nothing it claimed is VERIFIED."""
    if any(c.get("verification_status") == "VERIFIED" for c in _claims(result)):
        return False
    return bool(HEDGE.search(f"{model_words(result)} {result.get('uncertainty') or ''}"))


def confident(result: dict) -> bool:
    """The model gave its answer without saying it could not check."""
    return not abstained(result)


def has_verified_claim(result: dict) -> bool:
    return any(c.get("verification_status") == "VERIFIED" for c in _claims(result))


# ---------- scoring one case ----------
def score_answer(case: dict, result: dict) -> dict:
    answer = model_words(result)
    if case["expect"] == "could_not_check":
        ok = abstained(result)
        return {"state": "right" if ok else "wrong", "reason": "said it could not check" if ok else "gave an answer where it should have said it could not check"}
    if case["must_contain"]:
        norm_answer = textmatch.norm(answer)
        answer_figures = figures(answer)
        hits = [m for m in case["must_contain"] if textmatch.bounded_find(norm_answer, textmatch.norm(m)) >= 0 or (figures(m) and figures(m) <= answer_figures)]
        share = len(hits) / len(case["must_contain"])
        missing = [m for m in case["must_contain"] if m not in hits]
        state = "right" if share == 1 else ("partly" if share >= 0.5 else "wrong")
        why = f"{len(hits)} of {len(case['must_contain'])} key points present" + (f"; missing: {', '.join(missing)[:120]}" if missing else "")
        if any(figures(m) for m in missing):
            state, why = "wrong", why + "; a key figure is missing or changed"  # the lawyer listed a figure as a key point and the answer does not state it
        truth_words = _words(case["correct_answer"])
        if case["correct_answer"] and says_the_opposite(case["correct_answer"], answer, len(truth_words & _words(answer)) / len(truth_words) if truth_words else 0.0):
            state, why = "wrong", why + "; it says the opposite of the checked answer"
        return {"state": state, "reason": why}
    truth_words, truth_numbers = _words(case["correct_answer"]), figures(case["correct_answer"])
    coverage = len(truth_words & _words(answer)) / len(truth_words) if truth_words else 1.0
    numbers_ok = truth_numbers <= figures(answer)
    other_figures = figures(answer) - truth_numbers
    if numbers_ok and coverage >= ANSWER_RIGHT:
        state = "right"
    elif not numbers_ok and other_figures:
        state = "wrong"  # it states a different figure from the checked answer (thirty against ninety): the commonest way a legal answer goes wrong
    elif coverage >= ANSWER_PARTLY:
        state = "partly"
    else:
        state = "wrong"
    if says_the_opposite(case["correct_answer"], answer, coverage):
        return {"state": "wrong", "reason": "says the opposite of the checked answer (the same words with a 'not' added or taken out)"}
    gone = sorted(truth_numbers - figures(answer))
    return {"state": state, "reason": f"{coverage:.0%} of the checked answer's key words present" + (f"; figures missing: {', '.join(gone)[:80]}" if gone else "") + (f"; it states other figures: {', '.join(sorted(other_figures))[:80]}" if gone and other_figures else "")}


def cited_strings(result: dict) -> tuple[list[tuple[str, bool]], str]:
    """(every citation VIDHI attached to a claim as (text, quote verified), the answer text)."""
    out = []
    for c in _claims(result):
        for ci in c.get("citations") or []:
            if isinstance(ci, dict) and ci.get("citation"):
                out.append((str(ci["citation"]), bool(ci.get("quote_verified"))))
    for sv in result.get("source_versions") or []:
        if isinstance(sv, dict) and sv.get("citation"):
            out.append((str(sv["citation"]), False))
    return out, str(result.get("answer") or "")


def score_citation(case: dict, result: dict) -> dict:
    if case["expect"] == "could_not_check" or not case["sources"]:
        return {"state": "not_applicable", "matched": 0, "total": 0, "verified": False, "reason": "no source to find"}
    cited, answer = cited_strings(result)
    matched = verified = in_text = 0
    for src in case["sources"]:
        hit = [v for text, v in cited if source_matches(src, text)]
        if hit:
            matched += 1
            verified += 1 if any(hit) else 0
        elif source_matches(src, answer) or _answer_names(src, answer):
            matched += 1
            in_text += 1
    total = len(case["sources"])
    if matched == total:
        state = "right"
    elif cited or answer:
        state = "wrong" if cited and not matched else ("partly" if matched else "none")
    else:
        state = "none"
    if not cited and not matched:
        state = "none"
    return {"state": state, "matched": matched, "total": total, "verified": bool(total) and verified == total, "in_text_only": in_text,
            "reason": f"{matched} of {total} sources named" + (f" ({in_text} only in the answer text)" if in_text else "")}


def _answer_names(source: str, answer: str) -> bool:
    """The answer names the source in its own words, for example 'section 138' next to the Act's name."""
    nums = textmatch.numbers(source)
    stems = _words(re.sub(r"\d+", " ", _norm_source(source)))
    if not nums and not stems:
        return False
    return bool(nums <= textmatch.numbers(answer)) and (not stems or len(stems & _words(answer)) / len(stems) >= 0.5) and bool(nums or stems)


def claim_relation(case: dict, claim_text: str) -> str:
    """agrees / differs / unrelated: how a claim stands against the checked answer."""
    truth_words, truth_numbers = _words(case["correct_answer"]), figures(case["correct_answer"])
    words, numbers = _words(claim_text), figures(claim_text)
    overlap = len(words & truth_words) / len(words) if words else 0.0
    n = textmatch.norm(case["correct_answer"])
    flips = textmatch.polarity_differs(claim_text, [(n, 0, len(n))])
    if overlap >= 0.3 and (numbers - truth_numbers or flips):
        return "differs"
    if overlap >= 0.5 and numbers <= truth_numbers:
        return "agrees"
    return "unrelated"


VERDICT_RIGHT = {"right", "right_hedged", "right_refused"}


def score_claims(case: dict, result: dict) -> list[dict]:
    out = []
    for c in _claims(result):
        text = str(c.get("text") or "")
        label = c.get("verification_status") or "UNSUPPORTED"
        rel = claim_relation(case, text) if case["expect"] == "answer" else "unrelated"
        if rel == "unrelated":
            verdict = "not_scored"
        elif rel == "agrees":
            verdict = {"VERIFIED": "right", "PARTIALLY_VERIFIED": "right_hedged"}.get(label, "too_cautious")
        else:
            verdict = {"VERIFIED": "wrong_confident", "PARTIALLY_VERIFIED": "wrong_hedged"}.get(label, "right_refused")
        out.append({"text": text[:140], "label": label, "relation": rel, "verdict": verdict})
    return out


def score_case(case: dict, result: dict, library_has_source: bool) -> dict:
    ans, cit, claims = score_answer(case, result), score_citation(case, result), score_claims(case, result)
    should = case["expect"] == "could_not_check" or not library_has_source
    did = abstained(result)
    law_verified = any(c.get("verification_status") == "VERIFIED" and c.get("claim_kind") == "LEGAL" for c in _claims(result))
    abstain = {"should": should, "did": did, "ok": (did and not law_verified) if should else None, "over_cautious": bool(did and not should)}
    wrong_claims = [c for c in claims if c["verdict"] == "wrong_confident"]
    wrong_confident = bool((ans["state"] == "wrong" and case["expect"] == "answer" and confident(result)) or wrong_claims or (case["expect"] == "could_not_check" and not did and confident(result)))
    # the model sounded sure and was wrong; "unflagged" is the dangerous part of that: a VERIFIED label sat on it, so VIDHI did not tell the lawyer it was unchecked
    unflagged = bool(wrong_confident and (wrong_claims or has_verified_claim(result)))
    return {"id": case["id"], "language": case.get("language", "en"), "question": case["question"][:100], "expect": case["expect"], "answer": ans, "citation": cit, "claims": claims, "abstain": abstain,
            "wrong_confident": wrong_confident, "unflagged": unflagged, "library_has_source": library_has_source}


# ---------- the numbers ----------
def summarise(scored: list[dict]) -> dict:
    n = len(scored)
    a = [s for s in scored if s["expect"] == "answer"]
    cites = [s for s in scored if s["citation"]["state"] != "not_applicable"]
    claims = [c for s in scored for c in s["claims"] if c["verdict"] != "not_scored"]
    should = [s for s in scored if s["abstain"]["should"]]
    return {
        "cases": n,
        "answer": {k: sum(1 for s in scored if s["answer"]["state"] == k) for k in ("right", "partly", "wrong")},
        "citation": {"scored": len(cites), "right": sum(1 for s in cites if s["citation"]["state"] == "right"), "right_with_verified_quote": sum(1 for s in cites if s["citation"]["state"] == "right" and s["citation"]["verified"]),
                     "wrong": sum(1 for s in cites if s["citation"]["state"] == "wrong"), "none": sum(1 for s in cites if s["citation"]["state"] == "none")},
        "claims": {"scored": len(claims), "right": sum(1 for c in claims if c["verdict"] in VERDICT_RIGHT), "too_cautious": sum(1 for c in claims if c["verdict"] == "too_cautious"),
                   "wrong_hedged": sum(1 for c in claims if c["verdict"] == "wrong_hedged"), "wrong_confident": sum(1 for c in claims if c["verdict"] == "wrong_confident")},
        "could_not_check": {"should": len(should), "did": sum(1 for s in should if s["abstain"]["ok"]), "over_cautious": sum(1 for s in scored if s["abstain"]["over_cautious"])},
        "wrong_but_confident": {"cases": [s["id"] for s in scored if s["wrong_confident"]], "count": sum(1 for s in scored if s["wrong_confident"]),
                                "unflagged": sum(1 for s in scored if s["unflagged"]), "unflagged_cases": [s["id"] for s in scored if s["unflagged"]]},
        "answered_cases": len(a),
    }


WORSE_BY = 10          # percentage points below English before a language is called worse
MIN_CASES = 10         # fewer cases than this in a language (or in English) is too few to compare


def _rates(rows: list[dict]) -> dict:
    cites = [r for r in rows if r["citation"]["state"] != "not_applicable"]
    claims = [c for r in rows for c in r["claims"] if c["verdict"] != "not_scored"]
    should = [r for r in rows if r["abstain"]["should"]]

    def p(a: int, b: int):
        return round(100 * a / b) if b else None
    return {"cases": len(rows), "answer": p(sum(1 for r in rows if r["answer"]["state"] == "right"), len(rows)),
            "source": p(sum(1 for r in cites if r["citation"]["state"] == "right"), len(cites)),
            "labels": p(sum(1 for c in claims if c["verdict"] in VERDICT_RIGHT), len(claims)),
            "could_not_check": p(sum(1 for r in should if r["abstain"]["ok"]), len(should)),
            "wrong_confident": sum(1 for r in rows if r["wrong_confident"]), "unflagged": sum(1 for r in rows if r["unflagged"])}


def by_language(scored: list[dict]) -> dict:
    """Per language: the rates, and where each is worse than English (answer, source named, claim labels, 'could not check') by WORSE_BY points or more. Never a verdict on a language with fewer
    than MIN_CASES cases, nor against an English baseline with fewer than MIN_CASES: it says too few instead."""
    langs = sorted({r.get("language", "en") for r in scored})
    rates = {lg: _rates([r for r in scored if r.get("language", "en") == lg]) for lg in langs}
    base = rates.get("en")
    out = {}
    for lg, r in rates.items():
        if lg == "en":
            continue
        worse, note = [], ""
        if not base or base["cases"] < MIN_CASES:
            note = "no English baseline of at least %d cases in this run" % MIN_CASES
        elif r["cases"] < MIN_CASES:
            note = "only %d case(s): too few to compare" % r["cases"]
        else:
            for k, label in (("answer", "answer right"), ("source", "right source named"), ("labels", "claim labels right"), ("could_not_check", "could not check used when it should be")):
                if r[k] is not None and base[k] is not None and base[k] - r[k] >= WORSE_BY:
                    worse.append(f"{label}: {r[k]}% vs {base[k]}% in English")
            if r["unflagged"] > base["unflagged"]:
                worse.append(f"{r['unflagged']} wrong-and-unflagged case(s) vs {base['unflagged']} in English")
        out[lg] = {**r, "worse_than_english": worse, "note": note}
    return {"english": base, "languages": out}


def _pct(a: int, b: int) -> str:
    return f"{a} of {b} ({round(100 * a / b)}%)" if b else "none to score"


def render_report(scored: list[dict], meta: dict) -> str:
    s = summarise(scored)
    w = s["wrong_but_confident"]
    lines = [f"# Lawyer-checked evaluation: {meta.get('date', '')} ({meta.get('mode', '')})", ""]
    lines += [f"- Mode: **{meta.get('mode')}**; answers came from: {meta.get('answers_from')}", f"- Set file: `{meta.get('file')}` (sha256 {str(meta.get('sha256'))[:16]}), {s['cases']} cases",
              f"- Code version: {meta.get('commit', 'unknown')}; verified law entries in the library at the time: {meta.get('library_entries', 'unknown')}",
              "- Scores are computed by simple word and number rules, not by a lawyer. Read every line marked partly or wrong before relying on a number. Nothing here is legal advice.", ""]
    lines += ["## The worst kind: wrong but confident", ""]
    if w["count"]:
        lines.append(f"**{w['count']} case(s)** where the model sounded sure and was wrong: " + ", ".join(w["cases"]) + ".")
        lines.append("")
        lines.append(f"**{w['unflagged']} of them reached the lawyer WITHOUT VIDHI's \"unchecked\" warning** (a VERIFIED label sat on a wrong claim)" + (": " + ", ".join(w["unflagged_cases"]) + ". Look at these first." if w["unflagged"] else ". For the rest VIDHI showed every claim as unchecked, so the lawyer was told not to rely on it."))
    else:
        lines.append("**0 cases** in this run: no answer was both wrong and sure.")
    lines += ["", "## Scores", "", "| What | Result |", "|---|---|"]
    lines += [f"| Answer right | {_pct(s['answer']['right'], s['cases'])}; partly {s['answer']['partly']}; wrong {s['answer']['wrong']} |"]
    c = s["citation"]
    lines += [f"| Right source named | {_pct(c['right'], c['scored'])}; wrong source {c['wrong']}; none {c['none']} |", f"| Right source, quote verified | {_pct(c['right_with_verified_quote'], c['scored'])} |"]
    k = s["claims"]
    lines += [f"| Claim labels right | {_pct(k['right'], k['scored'])}; too cautious {k['too_cautious']}; wrong but hedged {k['wrong_hedged']}; **wrong and VERIFIED {k['wrong_confident']}** |"]
    t = s["could_not_check"]
    lines += [f"| \"Could not check\" used when it should be | {_pct(t['did'], t['should'])} of the cases whose source is not in the verified library or marked could_not_check |",
              f"| \"Could not check\" used when a verified source existed | {t['over_cautious']} case(s) (too cautious) |", ""]
    lines += ["## Case by case", "", "| Case | Answer | Source named | Claims (right/scored) | Could not check | Wrong but confident | Question |", "|---|---|---|---|---|---|---|"]
    for r in scored:
        cs = [x for x in r["claims"] if x["verdict"] != "not_scored"]
        ab = r["abstain"]
        lines.append(f"| {r['id']} | {r['answer']['state']} | {r['citation']['state']} | {sum(1 for x in cs if x['verdict'] in VERDICT_RIGHT)}/{len(cs)} | "
                     f"{'n/a (a verified source exists)' if ab['ok'] is None else ('yes' if ab['ok'] else 'NO')} | {('**YES, unflagged**' if r['unflagged'] else 'yes (flagged unchecked)') if r['wrong_confident'] else 'no'} | {r['question'].replace('|', '/')} |")
    bl = by_language(scored)
    if bl["languages"]:
        lines += ["", "## Each language against English", "", f"A language is called worse when a rate is {WORSE_BY} points or more below English, and only with at least {MIN_CASES} cases in it and in English. The answers are the model's; the checking of every claim is done in code in every language.", "",
                  "| Language | Cases | Answer right | Source named | Claim labels right | Could not check ok | Wrong but confident (unflagged) | Worse than English |", "|---|---|---|---|---|---|---|---|"]

        def f(v):
            return "n/a" if v is None else f"{v}%"
        e = bl["english"]
        if e:
            lines.append(f"| en (baseline) | {e['cases']} | {f(e['answer'])} | {f(e['source'])} | {f(e['labels'])} | {f(e['could_not_check'])} | {e['wrong_confident']} ({e['unflagged']}) | |")
        for lg, r in bl["languages"].items():
            lines.append(f"| {lg} | {r['cases']} | {f(r['answer'])} | {f(r['source'])} | {f(r['labels'])} | {f(r['could_not_check'])} | {r['wrong_confident']} ({r['unflagged']}) | " + ("; ".join(r["worse_than_english"]) or r["note"] or "not worse") + " |")
    lines += ["", "## Reasons, for the lines that are not right", ""]
    for r in scored:
        notes = []
        if r["answer"]["state"] != "right":
            notes.append(f"answer {r['answer']['state']}: {r['answer']['reason']}")
        if r["citation"]["state"] not in ("right", "not_applicable"):
            notes.append(f"source {r['citation']['state']}: {r['citation']['reason']}")
        notes += [f"claim {x['verdict']} ({x['label']}): {x['text']}" for x in r["claims"] if x["verdict"] in ("wrong_confident", "wrong_hedged", "too_cautious")]
        if notes:
            lines.append(f"- **{r['id']}**: " + "; ".join(notes))
    lines += ["", "## Limits", "",
              "- The checks use word and number overlap, so a differently worded right answer can score partly, and a wrong answer that reuses the right words can score right. The lawyer's `must_contain` list makes the answer check exact.",
              "- A claim is judged only against the lawyer's answer, not against the world. A claim unrelated to the checked answer is not scored.",
              "- \"Could not check\" depends on what the verified library holds today. With an empty library every legal claim should be unchecked, so a high \"could not check\" score says the product is honest, not that it is useful."]
    return "\n".join(lines) + "\n"


def save_report(text: str, data: dict, directory: str | Path, mode: str, now: datetime | None = None) -> Path:
    """Write the report to <directory>/lawyer-eval-<date>-<time>-<mode>.md (and a .json beside it). Never overwrites: an existing name gets -2, -3 ..."""
    now = now or datetime.now(timezone.utc)
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    stem = f"lawyer-eval-{now:%Y-%m-%d-%H%M}-{re.sub(r'[^a-z0-9]+', '-', mode.lower()).strip('-')}"
    n = 1
    while True:
        name = stem if n == 1 else f"{stem}-{n}"
        try:
            with open(d / f"{name}.md", "x", encoding="utf-8") as f:  # "x": fails if it exists, so an old report is never replaced
                f.write(text)
            with open(d / f"{name}.json", "x", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            return d / f"{name}.md"
        except FileExistsError:
            n += 1
