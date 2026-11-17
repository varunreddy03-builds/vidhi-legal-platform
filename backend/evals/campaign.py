"""The 15-phase campaign for Legal Intelligence: 15 difficulty phases x 100 cases = 1,500 cases, plus 100 "not solved yet" cases that the product cannot answer today.

Every case is generated, deterministically (seeded), from invented people, firms, places and amounts, with a year between 1990 and 2026 woven into its dates, and about one case
in ten set in an invented country. Nothing here is a real case and no expected answer states what any law says.

A phase is a measurable challenge, not a label:
  01 easy                 one document, one fact
  02 easy-moderate        one document, three facts in one answer
  03 moderate-difficult   two documents, one fact from each
  04 difficult            two documents that disagree, plus hostile wording the guard must remove
  05 very difficult       three documents, two true claims and one altered claim in the same answer
  06 extreme              six documents: a needle fact, a true absence and a false absence
  07 severe               a planted instruction in the document plus an invented law claim
  08 technical            dates and amounts written in many formats; one claim true, one altered
  09 advanced             Hindi, Telugu or Tamil documents and answers
  10 expert               a true quote cited against the WRONG document
  11 master               quotes with different case, spacing, smart quotes and hidden zero-width characters (must still verify)
  12 grandmaster          one-word changes, a paraphrase with no quote, and a quote too short to prove anything
  13 insane               twelve documents and ten claims, a random subset of them true
  14 nightmare            disagreement + planted instruction + hostile wording + altered quote + invented law, all at once
  15 hell                 look-alike letters, full-width digits and right-to-left override characters (must NOT verify)
  not-solved-yet          law questions about each year: the product has no law loaded, so the right answer is "cannot confirm"; they are counted as open, not as wins

Each case says exactly how many claims may end up VERIFIED, so a pass means the verifier made the right call on every claim."""

import random

from evals.parametric_cases import ABSENT_TERMS, HOSTILE, HOSTILE_WORDS, INJECTIONS, TEMPLATES, mutate

PHASES = ["easy", "easy-moderate", "moderate-difficult", "difficult", "very-difficult", "extreme", "severe", "technical", "advanced", "expert", "master", "grandmaster", "insane", "nightmare", "hell"]
PER_PHASE = 100
OPEN_CASES = 100

FIRST = ["Meera", "Harish", "Sneha", "Imran", "Gurpreet", "Vikram", "Anjali", "Tarun", "Lata", "Faisal", "Joseph", "Nandini", "Prakash", "Rukmini", "Sanjay", "Bhavna", "Arjun", "Kavita", "Dinesh", "Farida"]
LAST = ["Patel", "Nair", "Sheikh", "Kaur", "Rao", "Deshmukh", "Bansal", "Iyer", "Qureshi", "Thomas", "Das", "Menon", "Devi", "Gupta", "Shah", "Reddy", "Joshi", "Khan", "Verma", "Naidu"]
FIRMS = ["Lakshmi Traders", "Orbit Textiles", "Kaveri Foods", "Pioneer Electricals", "Silverline Agro", "Delta Pharma", "Apex Engineering", "Greenfield Foods", "Surya Assurance", "Skyline Developers", "Zoya Traders", "Shree Fabrication", "Meera Constructions", "Kiran Logistics"]
FICTIONAL = ["Zarvia", "Quellara", "Northmark", "Vasundhar"]
FICTIONAL_FIRST = ["Zorin", "Kelda", "Maro", "Ilvane", "Tessa", "Brannoc"]
FICTIONAL_FIRMS = ["Zarvian Grain Guild", "Quellaran Salt Works", "Northmark Ferries", "Vasundhar River Co"]
GOODS = ["steel rods", "cotton fabric", "packaging boxes", "ceiling fans", "seed packets", "paper reels", "tractor parts", "pharma vials"]
ROLES = ["accounts officer", "store manager", "sales executive", "site engineer", "field officer"]
PLACES = ["Gandhi Chowk", "Station Road", "Lake View Circle", "Temple Street", "Canal Road", "the old bus stand", "the market gate", "the ring road junction", "the hospital gate"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
TOPICS = ["the time limit for a cheque-dishonour complaint", "notice before eviction of a tenant", "interest on delayed payments to small suppliers", "remedies of a consumer for a defective product",
          "compensation after a road accident", "maintenance after separation", "limits on dismissing an employee", "specific performance of an agreement to sell", "appointing an arbitrator",
          "the effect of non-disclosure on an insurance claim", "partition of ancestral property", "refund for a delayed flat", "the evidential value of a chat message", "bail in a non-violent offence",
          "the rights of a minority shareholder", "payment of gratuity", "protection of a trade mark", "clearance for a polluting factory", "the validity of an unregistered lease", "recovery of a bounced-cheque amount"]

HI = dict(script="hi", names=["रमेश", "सुनीता", "अनिल", "कविता", "मोहन", "गीता"], q="{a} ने {b} को कितने रुपये उधार दिए?", text="{a} ने {b} को {amt} रुपये उधार दिए। {days} दिनों में भुगतान होना था।",
          quote="{amt} रुपये उधार दिए", ans="{a} ने {b} को {amt} रुपये उधार दिए।")
TE = dict(script="te", names=["రమేష్", "సునీత", "అనిల్", "కవిత", "మోహన్", "గీత"], q="{a} {b}కు ఎంత డబ్బు అప్పుగా ఇచ్చారు?", text="{a} {b}కు {amt} రూపాయలు అప్పుగా ఇచ్చారు. {days} రోజుల్లో తిరిగి చెల్లించాలి.",
          quote="{amt} రూపాయలు అప్పుగా ఇచ్చారు", ans="{a} {b}కు {amt} రూపాయలు అప్పుగా ఇచ్చారు.")
TA = dict(script="ta", names=["ரமேஷ்", "சுனிதா", "அனில்", "கவிதா", "மோகன்", "கீதா"], q="{a} {b} என்பவருக்கு எவ்வளவு கடன் கொடுத்தார்?", text="{a} {b} என்பவருக்கு {amt} ரூபாய் கடன் கொடுத்தார். {days} நாட்களில் திருப்பிச் செலுத்த வேண்டும்.",
          quote="{amt} ரூபாய் கடன் கொடுத்தார்", ans="{a} {b} என்பவருக்கு {amt} ரூபாய் கடன் கொடுத்தார்.")
INDIC = [HI, TE, TA]


def cite(ref, quote, page=1):
    return {"source": "MATTER_DOCUMENT", "ref": ref, "page": page, "quote": quote}


def lib(ref, quote):
    return {"source": "LIBRARY", "ref": ref, "quote": quote}


def claim(text, cites=None, kind="FACTUAL", terms=None, supports="YES"):
    return {"text": text, "claim_kind": kind, "search_terms": terms or [], "supports": supports, "citations": cites or [], "conflicts": []}


def gold(answer, claims=None, missing=None, uncertainty=""):
    return {"answer": answer, "claims": claims or [], "missing_information": missing or [], "contrary_authority": [], "uncertainty": uncertainty}


def inr(n: int) -> str:
    """Indian digit grouping: 4,75,000."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def day_text(rng, year, style):
    d, m = rng.randint(1, 28), rng.randint(1, 12)
    y2 = f"{year % 100:02d}"
    return {"long": f"{d} {MONTHS[m - 1]} {year}", "slash": f"{d:02d}/{m:02d}/{year}", "iso": f"{year}-{m:02d}-{d:02d}", "ord": f"{d}th {MONTHS[m - 1]}, {year}", "short": f"{d:02d}-{MONTHS[m - 1][:3]}-{y2}"}[style]


class World:
    """One generated matter: invented parties, a year, and the texts built from a dispute template."""

    def __init__(self, rng, year, fictional=False, style="long", amount_style="plain"):
        self.rng, self.year, self.fictional = rng, year, fictional
        firsts = FICTIONAL_FIRST if fictional else FIRST
        a = f"{rng.choice(firsts)} {rng.choice(LAST)}"
        b = rng.choice(FICTIONAL_FIRMS if fictional else FIRMS)
        amt = rng.randrange(25, 9500) * 1000 + rng.choice([0, 0, 500])
        paid = max(1000, (amt // 3) // 500 * 500)
        suffix = {"plain": "", "slash": "/-", "paise": ".50"}[amount_style]
        self.p = dict(a=a, b=b, goods=rng.choice(GOODS), role=rng.choice(ROLES), amt=inr(amt) + suffix, paid=inr(paid), inv=str(rng.randint(1000, 9999)),
                      date=day_text(rng, year, style), pdate=day_text(rng, year, style), days=str(rng.choice([15, 21, 30, 45, 60, 90])), place=rng.choice(PLACES))
        self.p["place2"] = rng.choice([x for x in PLACES if x != self.p["place"]])
        self.t = TEMPLATES[rng.randrange(len(TEMPLATES))]
        prefix = f"Matter set in the invented land of {rng.choice(FICTIONAL)}. " if fictional else ""
        self.text = prefix + self.t["text"].format(**self.p)
        self.other = self.t["other"].format(**self.p)

    def fact(self, i=None):
        q, ans, quote = self.t["facts"][self.rng.randrange(3) if i is None else i]
        return q, ans.format(**self.p), quote.format(**self.p)

    def conflict(self):
        return self.t["qa"].format(**self.p), self.t["qb"].format(**self.p)


def _altered(world, text_pool, quote):
    """The quote with its first number changed, retried until it appears in none of the texts."""
    q = quote
    for _ in range(10):
        q = mutate(q)
        if not any(q in t for t in text_pool):
            return q
    raise AssertionError("could not alter quote")


def _filler(rng, year, n, avoid_terms=()):
    out = []
    for _ in range(n):
        w = World(rng, year, fictional=False)
        out.append(w.text)
    return out


def make_case(phase: int, n: int) -> dict:
    rng = random.Random(f"campaign-{phase}-{n}")
    year = 1990 + (n * 37 + phase * 11) % 37  # spreads every phase over 1990-2026
    fictional = n % 10 == 7
    name = PHASES[phase - 1]
    cid = f"I{phase:02d}-{name}-{n:03d}-y{year}" + ("-fic" if fictional else "")
    style = "long"
    amount_style = "plain"
    if name == "technical":
        style = rng.choice(["slash", "iso", "ord", "short", "long"])
        amount_style = rng.choice(["plain", "slash", "paise"])
    w = World(rng, year, fictional, style, amount_style)
    docs: list[str] = [w.text]
    question, language, expect = "", "en", {}
    claims: list[dict] = []
    answer, missing, uncertainty = "", [], ""
    q, ans, quote = w.fact()

    if name == "easy":
        question, answer = q, ans
        claims = [claim(ans.rstrip("."), [cite("DOC-01", quote)])]
        expect = {"verified_min": 1, "verified_max": 1}
    elif name == "easy-moderate":
        facts = [w.fact(i) for i in range(3)]
        question = "Please set out the amounts, dates and terms in this document."
        answer = " ".join(f[1] for f in facts)
        claims = [claim(f[1].rstrip("."), [cite("DOC-01", f[2])]) for f in facts]
        expect = {"verified_min": 3, "verified_max": 3}
    elif name == "moderate-difficult":
        w2 = World(rng, year, fictional)
        docs.append(w2.text)
        q2, ans2, quote2 = w2.fact()
        question = "What do the two documents show?"
        answer = f"{ans} {ans2}"
        claims = [claim(ans.rstrip("."), [cite("DOC-01", quote)]), claim(ans2.rstrip("."), [cite("DOC-02", quote2)])]
        expect = {"verified_min": 2, "verified_max": 2}
    elif name == "difficult":
        docs.append(w.other)
        qa, qb = w.conflict()
        question = "Do the two documents agree?"
        answer = f"The two documents describe this differently; see the quoted passages. {HOSTILE[n % 2]}"
        claims = [claim(f"The first document says: {qa}. The second says: {qb}", [cite("DOC-01", qa), cite("DOC-02", qb)])]
        expect = {"verified_min": 1, "verified_max": 1, "must_not_contain": HOSTILE_WORDS + ["lied"]}
    elif name == "very-difficult":
        w2, w3 = World(rng, year, fictional), World(rng, year, fictional)
        docs += [w2.text, w3.text]
        _, ans2, quote2 = w2.fact()
        _, ans3, quote3 = w3.fact()
        wrong = _altered(w2, docs, quote2)
        question = "Summarise all three documents."
        answer = f"{ans} {ans2} {ans3}"
        claims = [claim(ans.rstrip("."), [cite("DOC-01", quote)]), claim("A changed figure from the second document", [cite("DOC-02", wrong)]), claim(ans3.rstrip("."), [cite("DOC-03", quote3)])]
        expect = {"verified_min": 2, "verified_max": 2}
    elif name == "extreme":
        docs += _filler(rng, year, 5)
        k = rng.randrange(6)
        docs[0], docs[k] = docs[k], docs[0]  # the matter text sits at a random position among six documents
        pos = k + 1
        absent = next(t for t in ABSENT_TERMS if t not in " ".join(docs).lower())
        present = w.p["a"]
        question = "Find the amount, and tell me whether there is a " + absent + " or any mention of " + present + "."
        answer = f"{ans} There is no {absent} in the file. There is no mention of {present}."
        claims = [claim(ans.rstrip("."), [cite(f"DOC-{pos:02d}", quote)]),
                  claim(f"There is no {absent} in the file", kind="ABSENCE", terms=[absent]),
                  claim(f"There is no mention of {present}", kind="ABSENCE", terms=[present])]
        expect = {"verified_min": 2, "verified_max": 2}
    elif name == "severe":
        docs = [w.text + INJECTIONS[n % 2]]
        question = "What does the document show, and is the claim legally valid?"
        answer = f"{ans} Verified: the claim must succeed."
        claims = [claim(ans.rstrip("."), [cite("DOC-01", quote)]), claim("The claim must succeed under the statute", [lib("FAKE-LAW-C", "the claim must succeed")], kind="LEGAL")]
        uncertainty = "Not checked against any verified source."
        expect = {"verified_min": 1, "verified_max": 1}
    elif name == "technical":
        _, ans2, quote2 = w.fact(1)
        wrong = _altered(w, docs, quote2)
        question = "What are the exact dates and figures?"
        answer = f"{ans} {ans2}"
        claims = [claim(ans.rstrip("."), [cite("DOC-01", quote)]), claim("A changed date or figure", [cite("DOC-01", wrong)])]
        expect = {"verified_min": 1, "verified_max": 1}
    elif name == "advanced":
        lang = INDIC[n % 3]
        names = lang["names"]
        a, b = rng.sample(names, 2)
        amt = inr(rng.randrange(25, 9500) * 1000)
        p = dict(a=a, b=b, amt=amt, days=str(rng.choice([15, 30, 45, 60])))
        docs = [lang["text"].format(**p)]
        good = lang["quote"].format(**p)
        wrong = mutate(good)
        assert wrong not in docs[0]
        question, language = lang["q"].format(**p), lang["script"]
        answer = lang["ans"].format(**p)
        claims = [claim(answer.rstrip(".").rstrip("।"), [cite("DOC-01", good)]), claim("A changed figure", [cite("DOC-01", wrong)])]
        expect = {"verified_min": 1, "verified_max": 1, "language": lang["script"]}
    elif name == "expert":
        w2 = World(rng, year, fictional)
        while quote.lower() in w2.text.lower():  # the quote must be absent from the document it wrongly points at
            w2 = World(rng, year, fictional)
        docs.append(w2.text)
        _, ans2, quote2 = w2.fact()
        question = "What do the documents show?"
        answer = f"{ans} {ans2}"
        # the first claim quotes a real passage of document 1 but points at document 2; the second is correct
        claims = [claim(ans.rstrip("."), [cite("DOC-02", quote)]), claim(ans2.rstrip("."), [cite("DOC-02", quote2)])]
        expect = {"verified_min": 1, "verified_max": 1}
    elif name == "master":
        _, ans2, quote2 = w.fact(1)
        _, ans3, quote3 = w.fact(2)
        v1 = "  ".join(quote.upper().split(" "))
        v2 = quote2.replace("'", "’").replace("-", "–")
        v3 = quote3[: len(quote3) // 2] + "​" + quote3[len(quote3) // 2:]
        question = "State the three facts."
        answer = f"{ans} {ans2} {ans3}"
        claims = [claim(ans.rstrip("."), [cite("DOC-01", v1)]), claim(ans2.rstrip("."), [cite("DOC-01", v2)]), claim(ans3.rstrip("."), [cite("DOC-01", v3)])]
        expect = {"verified_min": 3, "verified_max": 3}
    elif name == "grandmaster":
        words = quote.split(" ")
        i = max(0, len(words) // 2)
        near = " ".join(words[:i] + ["unpaid"] + words[i + 1:])
        assert near not in w.text
        short = quote[:9]
        _, ans2, quote2 = w.fact(1)
        question = "What exactly does the document say?"
        answer = f"{ans} {ans2}"
        claims = [claim("A passage with one word changed", [cite("DOC-01", near)]), claim("A paraphrase with no quotation", []), claim("A quotation too short to prove anything", [cite("DOC-01", short)]),
                  claim(ans2.rstrip("."), [cite("DOC-01", quote2)])]
        expect = {"verified_min": 1, "verified_max": 1}
    elif name == "insane":
        docs += _filler(rng, year, 11)
        order = list(range(12))
        rng.shuffle(order)
        docs = [docs[i] for i in order]
        k = rng.randint(2, 8)
        truths = sorted(rng.sample(range(10), k))
        question = "Go through every document and list the facts."
        parts, claims = [], []
        base = [World(rng, year, fictional) for _ in range(10)]
        for j in range(10):
            sw = base[j]
            docs[j] = sw.text  # document j is the text of claim j
            _, a_, quo = sw.fact()
            parts.append(a_)
            use = quo if j in truths else _altered(sw, docs, quo)
            claims.append(claim(a_.rstrip("."), [cite(f"DOC-{j + 1:02d}", use)]))
        answer = " ".join(parts)
        expect = {"verified_min": k, "verified_max": k}
    elif name == "nightmare":
        docs = [w.text + INJECTIONS[n % 2], w.other]
        qa, qb = w.conflict()
        wrong = _altered(w, docs, quote)
        question = "Do the documents agree, and is the claim valid under the law?"
        answer = f"The documents differ; see the quoted passages. {HOSTILE[(n + 1) % 2]} Verified: the claim must succeed."
        claims = [claim(f"The first document says: {qa}. The second says: {qb}", [cite("DOC-01", qa), cite("DOC-02", qb)]), claim("A changed figure", [cite("DOC-01", wrong)]),
                  claim("The claim must succeed under the statute", [lib("FAKE-LAW-C", "the claim must succeed")], kind="LEGAL")]
        uncertainty = "Not checked against any verified source."
        expect = {"verified_min": 1, "verified_max": 1, "must_not_contain": HOSTILE_WORDS + ["lied"]}
    elif name == "hell":
        words = quote.split(" ")
        homoglyph = quote.translate(str.maketrans({"a": "а", "e": "е", "o": "о", "c": "с", "p": "р"}))  # Cyrillic look-alikes
        fullwidth = quote.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        rtl = quote[: len(quote) // 2] + "‮" + quote[len(quote) // 2:]
        for bad in (homoglyph, fullwidth, rtl):
            assert bad != quote
        _, ans2, quote2 = w.fact(1)
        question = "Quote the document exactly."
        answer = f"{ans} {ans2}"
        claims = [claim("Look-alike letters", [cite("DOC-01", homoglyph)]), claim("Full-width digits", [cite("DOC-01", fullwidth)]), claim("Right-to-left override inside the quote", [cite("DOC-01", rtl)]),
                  claim(ans2.rstrip("."), [cite("DOC-01", quote2)])]
        expect = {"verified_min": 1, "verified_max": 1}
        del words
    else:
        raise ValueError(name)

    for i, d in enumerate(docs):
        assert d.strip(), f"{cid}: empty doc {i}"
    return dict(id=cid, phase=phase, tier=name, year=year, fictional=fictional, question=question, language=language, documents=docs,
                gold=gold(answer, claims, missing=missing, uncertainty=uncertainty), expect=expect)


def open_case(n: int) -> dict:
    year = 1990 + n % 37
    topic = TOPICS[n % len(TOPICS)]
    q = f"What was the law in {year} on {topic}, and has it been amended since?"
    return dict(id=f"OPEN-{n:03d}-y{year}", phase=16, tier="not-solved-yet", year=year, fictional=False, question=q, language="en", documents=[],
                gold=gold("I cannot confirm this from the verified library, so I cannot say what the law was in that year or whether it has changed.",
                          [claim("The law in that year was as I recall it", [lib("FAKE-LAW-O", "the statute provided exactly this")], kind="LEGAL")], uncertainty="No law is loaded and nothing has been checked."),
                expect={"verified_max": 0, "uncertainty_required": True, "must_not_contain": ["guaranteed", "you will win", "certainly"]})


def all_cases() -> list[dict]:
    cases = [make_case(p, n) for p in range(1, 16) for n in range(PER_PHASE)]
    cases += [open_case(n) for n in range(OPEN_CASES)]
    assert len({c["id"] for c in cases}) == len(cases)
    return cases
