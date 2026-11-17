"""Checks a demand notice must pass before it can be exported, approved or emailed.

1. No blanks left: any [ ] / [address] / [date] style placeholder must be filled in.
2. No legal references: the drafting model must not cite law (project rule 1 - nothing is verified without a verified source). If a section/Act/case reference is present,
   the user must remove it or have a lawyer verify it before sending.
3. No threats or accusations: words about arrest, police, crime, fraud or dishonesty are refused (RISKY_RE).
4. No stray figures: every sum of money written in the wording must be one of the figures VIDHI itself put in the statement of account. A model's own arithmetic
   (`you owe Rs 99,99,999`) is never allowed to stand beside the calculated balance.
5. The statement of account must still be exactly the one VIDHI wrote when the notice was drafted, and the figures behind it must not have changed since (a payment, a credit,
   a charge). Otherwise the notice would demand a sum that is no longer owed.
6. No claim that the notice has been served, delivered or received: only a delivery record can say that.

The party names and addresses of the case are blanked out before the word checks, so a customer called "Police Housing Society" or a street called "Order 4 Road" does not trip them.
Every pattern here is bounded, so a hostile 12,000-character line cannot make it slow."""

import re
from decimal import Decimal, InvalidOperation

PLACEHOLDER_RE = re.compile(r"\[[^\[\]\n]{0,80}\]|\{\{[^{}\n]{0,80}\}\}")

_LEGAL_REF_PATTERNS = [
    re.compile(r"\b(?:sections?|sec|s\.|articles?|art|u/s|order|rule|rules)\.?\s{0,3}\d{1,4}[A-Za-z]{0,3}(?:\(\w{1,4}\)){0,4}", re.I),
    re.compile(r"\b(?:order|rule)\s{1,3}[IVXLC]{1,6}\b", re.I),
    re.compile(r"\b(?:[A-Z][A-Za-z]{1,20}\s){1,6}Act(?:,?\s{0,3}(?:of\s{1,3})?\d{4})?\b"),
    re.compile(r"\b(?:IPC|BNS|BNSS|BSA|CrPC|CPC|SCC|AIR|NI Act|MSMED)\b"),
    re.compile(r"\b(?:Indian Penal Code|Code of (?:Civil|Criminal) Procedure|Bharatiya (?:Nyaya|Nagarik Suraksha) Sanhita|Bharatiya Sakshya Adhiniyam|Constitution of India|Negotiable Instruments|Insolvency and Bankruptcy Code|Indian Contract|Evidence Act)\b", re.I),
    re.compile(r"\bv(?:s|ersus)?\.?\s{1,3}[A-Z][A-Za-z]{1,30}"),
    # "section 138" written in the languages a translated notice is in (security audit SA8): the word for section or article, then a number in any script's digits
    re.compile(r"(?:धारा|अनुच्छेद|कलम|సెక్షన్|ఆర్టికల్|பிரிவு|சட்டப்பிரிவு|ধারা|অনুচ্ছেদ|કલમ|ਧਾਰਾ|ଧାରା|വകുപ്പ്|ಕಲಂ|ಸೆಕ್ಷನ್|دفعہ|ধাৰা)\s{0,3}\d{1,4}[A-Za-z]{0,3}"),
]

# Words that threaten or accuse. An unpaid invoice is a civil matter: a notice must not threaten arrest or police
# action, accuse the customer of fraud or dishonesty, or say anyone "lied". (Project rule 2 applies to notices too.)
RISKY_RE = re.compile(
    r"\b(arrest\w*|jail\w*|imprison\w*|police|FIR|criminal\w*|cheat\w*|fraud\w*|defraud\w*|thie[fv]\w*|theft|stole\w*|stolen|scam\w*|swindl\w*|embezzl\w*|prosecut\w*|"
    r"liar|lied|lying|dishonest\w*|blackmail\w*|extort\w*)\b",
    re.I,
)
# the same idea in the languages a translated notice is written in (matched anywhere in the text)
RISKY_OTHER = (
    "गिरफ्तार", "गिरफ़्तार", "पुलिस", "जेल", "धोखा", "धोखाधड़ी", "झूठ", "अटक", "पोलीस", "तुरुंग", "फसवणूक",
    "అరెస్ట్", "అరెస్టు", "పోలీసు", "జైలు", "మోసం", "అబద్ధ",
    "கைது", "போலீஸ்", "காவல்", "சிறை", "மோசடி", "பொய்",
    "ಬಂಧ", "ಪೊಲೀಸ್", "ಜೈಲು", "ವಂಚನೆ", "ಸುಳ್ಳು",
    "അറസ്റ്റ്", "പോലീസ്", "ജയിൽ", "വഞ്ചന", "നുണ",
    "গ্রেপ্তার", "পুলিশ", "জেল", "প্রতারণা", "মিথ্যা",
    "ધરપકડ", "પોલીસ", "જેલ", "છેતરપિંડી", "જૂઠ",
    "ਗ੍ਰਿਫਤਾਰ", "ਪੁਲਿਸ", "ਜੇਲ", "ਧੋਖਾ", "ਝੂਠ",
    "گرفتار", "پولیس", "جیل", "دھوکہ", "دھوکا", "جھوٹ",
)
# only a delivery record can say a notice reached anyone
SERVICE_RE = re.compile(
    r"\b(?:deemed\s{1,3}(?:to\s{1,3}(?:have\s{1,3}been\s{1,3})?)?(?:served|delivered|received)|"
    r"(?:this|the)\s{1,3}notice\s{1,3}(?:has|have)?\s{0,3}(?:been|was|is)\s{1,3}(?:duly\s{1,3})?(?:served|delivered|received)|"
    r"(?:has|have|was|were)\s{1,3}(?:been\s{1,3})?(?:duly\s{1,3})?served\s{1,3}(?:on|upon)\s{1,3}you)\b",
    re.I,
)

_NUM = r"(?:\d{1,3}(?:,\d{2,3}){1,6}|\d{1,15})(?:\.\d{1,4})?"
_CUR = r"(?<![A-Za-z])(?:Rs\.?|INR|₹|USD|US\$|\$|EUR|€|£|GBP|AED|Rupees?)"  # not inside a word: "Acme Traders 12 MG Road" must not read as "Rs 12"
# a sum of money: `Rs 1,200`, `INR 5,00,000`, `₹ 300`, `Rupees 5000`, or as the statement prints it: `1,200.00 INR`, `5,000/-`, `5000 rupees`
_SCALE = r"(?:lakhs?|lacs?|crores?|crs?\.?|thousand|million|billion)"  # "Rs 10 lakh" is 10,00,000, never 10
_MONEY_RE = re.compile(rf"(?:{_CUR}\s{{0,3}}(?P<n1>{_NUM})(?:\s{{0,2}}(?P<s1>{_SCALE}))?)|(?:(?P<n2>{_NUM})(?:\s{{0,2}}(?P<s2>{_SCALE}))?\s{{0,3}}(?:(?:INR|USD|EUR|GBP|AED|rupees?)(?![A-Za-z])|/-))", re.I)
_MULT = {"lakh": 10**5, "lac": 10**5, "crore": 10**7, "cr": 10**7, "thousand": 10**3, "million": 10**6, "billion": 10**9}
_UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * (i + 2) for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())}
_BIG = {"thousand": 10**3, "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5, "crore": 10**7, "crores": 10**7, "million": 10**6}
_WORD = "|".join(sorted([*_UNITS, *_TENS, *_BIG, "hundred", "and"], key=len, reverse=True))
# a sum written in words: "Rupees five thousand", "Rs. Two Lakh Fifty Thousand only"
_WORDS_RE = re.compile(rf"(?<![A-Za-z])(?:Rs\.?|INR|Rupees?)\s{{0,3}}((?:(?:{_WORD})(?![A-Za-z])[\s-]*)+)", re.I)
_STATEMENT_HEAD = "Statement of account"


def _unique(items):
    seen, out = set(), []
    for i in items:
        key = " ".join(i.split()).lower()
        if key not in seen:
            seen.add(key)
            out.append(" ".join(i.split()))
    return out


def find_placeholders(text: str) -> list[str]:
    return _unique(m.group(0) for m in PLACEHOLDER_RE.finditer(text or ""))


def find_legal_references(text: str) -> list[str]:
    found: list[str] = []
    for rx in _LEGAL_REF_PATTERNS:
        found += [m.group(0).strip() for m in rx.finditer(text or "")]
    return _unique(found)


def find_risky_language(text: str) -> list[str]:
    t = text or ""
    return _unique([m.group(0) for m in RISKY_RE.finditer(t)] + [w for w in RISKY_OTHER if w in t])


# A claim that the notice has been served or is taken as received, in the languages a translated notice is in (security audit SA8). Only PHRASES that state it as done or deemed are listed, so that the ordinary
# "pay within 15 days of receiving this notice" is not caught. Hindi, Marathi, Telugu, Tamil, Bengali and Gujarati only; no native speaker has reviewed these lists, and a person still reads every translation.
NOTICE_WORDS = ("नोटिस", "नोटीस", "सूचना", "सूचनापत्र", "నోటీసు", "నోటీస్", "அறிவிப்பு", "நோட்டீஸ்", "নোটিস", "નોટિસ", "નોટીસ")
SERVICE_OTHER = (
    "तामील हो चुका", "तामील हो चुकी", "तामील किया जा चुका", "तामील किया गया", "तामील माना", "तामील मान", "प्राप्त माना", "प्राप्त हो चुका", "प्राप्त हो चुकी", "प्राप्त हुआ माना", "प्राप्त समझा", "पहुँचा दिया गया", "पहुंचा दिया गया", "सुपुर्द किया गया",
    "बजावण्यात आली", "बजावली गेली", "बजावला गेला", "प्राप्त झाल्याचे मानले", "मिळाल्याचे मानले",
    "అందినట్లు", "అందజేయబడింది", "అందజేయబడినది", "అందుకున్నట్లు", "అందినదిగా భావ", "అందినట్టు", "బజాయించబడింది",
    "பெறப்பட்டதாக", "பெறப்பட்டது", "வழங்கப்பட்டதாக", "வழங்கப்பட்டது", "கருதப்படும்", "கருதப்படுகிறது", "சேர்க்கப்பட்டது",
    "জারি করা হয়েছে", "প্রাপ্ত বলে গণ্য", "পৌঁছে দেওয়া হয়েছে", "প্রাপ্ত হয়েছে বলে",
    "બજાવવામાં આવી", "પ્રાપ્ત થયેલ ગણાશે", "મળ્યું ગણાશે", "પહોંચાડવામાં આવી",
)


def find_service_claims(text: str) -> list[str]:
    t = text or ""
    found = [m.group(0) for m in SERVICE_RE.finditer(t)]
    for phrase in SERVICE_OTHER:
        for m in re.finditer(re.escape(phrase), t):
            if any(w in t[max(0, m.start() - 80): m.end() + 80] for w in NOTICE_WORDS):  # the notice itself is being talked about, not some other delivery
                found.append(phrase)
                break
    return _unique(found)


def _value(raw: str):
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def _amount(m) -> "Decimal | None":
    """The value of one _MONEY_RE match, with lakh/crore/thousand/million applied."""
    raw = m.group("n1") or m.group("n2")
    v = _value(raw)
    suffix = (m.group("s1") or m.group("s2") or "").lower().rstrip(".")
    if v is not None and suffix:
        v *= _MULT[suffix.rstrip("s") if suffix.rstrip("s") in _MULT else suffix]
    return v


def _words_value(words: str) -> "Decimal | None":
    """A spelled-out number as a value, or None when it cannot be read with certainty (then it is flagged, never trusted)."""
    toks = [t for t in re.split(r"[\s-]+", words.lower()) if t and t != "and"]
    if not toks:
        return None
    total, current = 0, 0
    for t in toks:
        if t in _UNITS:
            current += _UNITS[t]
        elif t in _TENS:
            current += _TENS[t]
        elif t == "hundred":
            current = max(current, 1) * 100
        elif t in _BIG:
            total += max(current, 1) * _BIG[t]
            current = 0
        else:
            return None
    return Decimal(total + current)


def _prose_amounts(text: str) -> list[tuple[str, "Decimal | None"]]:
    """(as written, value) for every sum in the text; a value of None means a written-out sum that could not be read."""
    out = [(m.group(0).strip(), v) for m in _MONEY_RE.finditer(text) if (v := _amount(m)) is not None]
    out += [(" ".join(m.group(0).split()), _words_value(m.group(1))) for m in _WORDS_RE.finditer(text) if m.group(1).strip().lower() not in ("and", "only")]
    return out


def _without(text: str, names: list[str] | None) -> str:
    """The text with the case's own names and addresses blanked, so they cannot trip the word checks."""
    out = text or ""
    for n in sorted({x.strip() for x in (names or []) if isinstance(x, str) and len(x.strip()) >= 3}, key=len, reverse=True):
        out = re.sub(re.escape(n), " ", out, flags=re.I)
    return out


def _split_statement(text: str, statement: str | None) -> tuple[str, str]:
    """(statement lines, the rest of the text). With the statement VIDHI wrote it is that exact block; without it, the indented lines under the 'Statement of account' heading."""
    if statement and statement in text:
        return statement, text.replace(statement, " ", 1)
    lines, inside, block, rest = (text or "").splitlines(), False, [], []
    for line in lines:
        if line.strip() == _STATEMENT_HEAD:
            inside = True
            block.append(line)
        elif inside and line.startswith("  ") and line.strip():
            block.append(line)
        else:
            inside = False
            rest.append(line)
    return "\n".join(block), "\n".join(rest)


def find_stray_amounts(text: str, statement: str | None = None) -> list[str]:
    """Sums of money in the wording that are not in the statement of account (the lines VIDHI wrote from the owner's figures)."""
    block, rest = _split_statement(text or "", statement)
    allowed = {v for _, v in _prose_amounts(block) if v is not None}
    if not allowed:  # no statement of account in the text (a notice written by hand): there is nothing to compare the wording with
        return []
    return _unique(shown for shown, value in _prose_amounts(rest) if value is None or value not in allowed)  # an unreadable written-out sum cannot be matched to the statement, so it is flagged


def notice_blockers(text: str, *, statement: str | None = None, expected_balance: float | None = None, current_balance: float | None = None, names: list[str] | None = None) -> dict:
    """What stops this notice from going out. `statement`, `expected_balance`, `current_balance` and `names` come from the case (see `blockers_for`)."""
    t = (text or "").replace("\r\n", "\n")
    scan = _without(t, names)
    ph, refs, risky, service = find_placeholders(t), find_legal_references(scan), find_risky_language(scan), find_service_claims(scan)
    stray = find_stray_amounts(t, statement)
    changed = bool(statement and _STATEMENT_HEAD in t and statement not in t)
    figures = bool(expected_balance is not None and current_balance is not None and abs(float(expected_balance) - float(current_balance)) > 0.004)
    return {"placeholders": ph, "legal_references": refs, "risky_language": risky, "amount_mismatches": stray, "service_claims": service,
            "statement_changed": changed, "figures_changed": figures,
            "blocked": bool(ph or refs or risky or stray or service or changed or figures)}


def blockers_for(case: dict, text: str | None = None) -> dict:
    """The blockers for a recovery case's current notice (or `text`), using what was recorded when it was drafted and the case's figures now."""
    from lib.balance import compute_balance

    meta = case.get("notice_meta") or {}
    body = case.get("notice_body") if text is None else text
    names = [case.get(k) for k in ("creditor_name", "debtor_name", "creditor_address", "debtor_address")]
    current = None
    if meta.get("statement") is not None or meta.get("balance") is not None:
        current = compute_balance(case)["balance"]
    return notice_blockers(body or "", statement=meta.get("statement"), expected_balance=meta.get("balance"), current_balance=current, names=names)
