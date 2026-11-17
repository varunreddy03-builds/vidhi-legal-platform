"""3,000 generated Legal Intelligence cases whose expected answers come ONLY from the independent auditor (evals/auditor.py).

Nothing here says what the right answer is; each case is a set of documents plus a scripted model reply, and the auditor works out from the documents what the app must do with
every claim. So a mistake in this generator cannot hide a mistake in the app, and a quote I got wrong by accident is judged correctly anyway.

Documents: 20 invented dispute templates, tables, multi-paragraph files, Hindi / Telugu / Tamil / Kannada / Bengali / Marathi files, accented and combining-mark text, files with
very large numbers, matters of 2 to 6 documents, and matters far under and far over the 80,000-character context budget. Dates run from 1990 to 2026; about one case in ten is set in
an invented country. Quotes are damaged in about 35 ways: case, spacing, smart quotes, invisible characters, digit changes, truncated or extended numbers, cut words, short quotes,
dropped / swapped / replaced words, look-alike letters, full-width digits, bidi controls, combining marks, Unicode forms. Claims mix fact, absence, law and procedure, with odd
citation spellings, wrong or missing documents and weak support. Hostile wording is planted in answers and claim texts in English and Indian languages."""

import random
import unicodedata

from evals.campaign import FIRST, FIRMS, FICTIONAL, FICTIONAL_FIRMS, FICTIONAL_FIRST, GOODS, LAST, MONTHS, PLACES, ROLES, World, claim, cite, gold, inr, lib
from evals.parametric_cases import ABSENT_TERMS, TEMPLATES
from evals import auditor

TEMPLATES2 = [
    dict(key="hospital", text="{a} was admitted to {b} Hospital on {date} for treatment. The bill raised on {pdate} is Rs {amt}. {a} paid Rs {paid} at discharge.",
         facts=[("When was the patient admitted?", "On {date}.", "admitted to {b} Hospital on {date}"), ("What is the bill?", "Rs {amt}.", "bill raised on {pdate} is Rs {amt}"), ("What was paid?", "Rs {paid}.", "paid Rs {paid} at discharge")],
         other="Hospital note: The treatment charges were itemised and explained to the family.", qa="is Rs {amt}", qb="itemised and explained"),
    dict(key="school", text="{a} enrolled with {b} Academy on {date}. The annual fee is Rs {amt}, payable in {days} days. A refund of Rs {paid} was requested on {pdate}.",
         facts=[("What is the fee?", "Rs {amt}.", "annual fee is Rs {amt}"), ("When is it payable?", "In {days} days.", "payable in {days} days"), ("What refund was requested?", "Rs {paid}.", "refund of Rs {paid} was requested on {pdate}")],
         other="Academy reply: No refund is permitted after the term begins.", qa="refund of Rs {paid} was requested", qb="No refund is permitted"),
    dict(key="courier", text="{b} Couriers accepted a parcel of {goods} from {a} on {date}, declared value Rs {amt}. The parcel was reported lost after {days} days.",
         facts=[("What was declared?", "Rs {amt}.", "declared value Rs {amt}"), ("When was it accepted?", "On {date}.", "accepted a parcel of {goods} from {a} on {date}"), ("When was it reported lost?", "After {days} days.", "reported lost after {days} days")],
         other="Courier record: The parcel was delivered and signed for at the address.", qa="reported lost", qb="delivered and signed for"),
    dict(key="franchise", text="{a} signed a franchise agreement with {b} on {date} with a fee of Rs {amt}. Royalty of Rs {paid} is due every {days} days.",
         facts=[("What is the fee?", "Rs {amt}.", "with a fee of Rs {amt}"), ("What royalty is due?", "Rs {paid}.", "Royalty of Rs {paid} is due every {days} days"), ("When was it signed?", "On {date}.", "franchise agreement with {b} on {date}")],
         other="Note of {b}: The royalty was waived orally for the first year.", qa="Royalty of Rs {paid} is due", qb="waived orally"),
    dict(key="society", text="Member {a} of {b} Society was charged maintenance of Rs {amt} on {date}. Dues of Rs {paid} remain for {days} days.",
         facts=[("What was charged?", "Rs {amt}.", "charged maintenance of Rs {amt} on {date}"), ("What dues remain?", "Rs {paid}.", "Dues of Rs {paid} remain"), ("For how long?", "{days} days.", "remain for {days} days")],
         other="Member's letter: The maintenance charge was never approved at a general meeting.", qa="was charged maintenance", qb="never approved"),
    dict(key="bank", text="{a} holds account {inv} with {b} Bank. On {date} a debit of Rs {amt} was posted. The bank reversed Rs {paid} on {pdate}.",
         facts=[("Which account?", "Account {inv}.", "holds account {inv} with {b} Bank"), ("What was debited?", "Rs {amt}.", "a debit of Rs {amt} was posted"), ("What was reversed?", "Rs {paid}.", "reversed Rs {paid} on {pdate}")],
         other="Bank reply: The debit was authorised by the account holder.", qa="a debit of Rs {amt} was posted", qb="authorised by the account holder"),
    dict(key="rental", text="{b} rented {goods} to {a} on {date} for Rs {amt} a month. The security deposit is Rs {paid}. The equipment was returned after {days} days.",
         facts=[("What rent?", "Rs {amt} a month.", "for Rs {amt} a month"), ("What deposit?", "Rs {paid}.", "security deposit is Rs {paid}"), ("When returned?", "After {days} days.", "returned after {days} days")],
         other="Note of {b}: The equipment was returned damaged and the deposit is forfeited.", qa="security deposit is", qb="deposit is forfeited"),
    dict(key="ecommerce", text="{a} ordered {goods} on {date} for Rs {amt} on the platform of {b}. A refund of Rs {paid} was initiated on {pdate}. Delivery took {days} days.",
         facts=[("What was the price?", "Rs {amt}.", "for Rs {amt} on the platform of {b}"), ("What refund?", "Rs {paid}.", "refund of Rs {paid} was initiated on {pdate}"), ("How long was delivery?", "{days} days.", "Delivery took {days} days")],
         other="Platform message: No refund has been initiated for this order.", qa="refund of Rs {paid} was initiated", qb="No refund has been initiated"),
    dict(key="estate", text="The late {a} left a house at {place} valued at Rs {amt}. The will dated {date} names {b} as executor. Debts of Rs {paid} remain unpaid.",
         facts=[("What did the deceased leave?", "A house at {place}.", "left a house at {place} valued at Rs {amt}"), ("Who is executor?", "{b}.", "names {b} as executor"), ("What debts remain?", "Rs {paid}.", "Debts of Rs {paid} remain unpaid")],
         other="Family statement: The will dated {date} was never signed by the deceased.", qa="The will dated {date} names", qb="never signed by the deceased"),
    dict(key="complaint", text="On {date} {a} lodged a complaint at {place} against {b} alleging non-payment of Rs {amt}. Rs {paid} was returned on {pdate}.",
         facts=[("What was alleged?", "Non-payment of Rs {amt}.", "alleging non-payment of Rs {amt}"), ("Where was it lodged?", "At {place}.", "lodged a complaint at {place}"), ("What was returned?", "Rs {paid}.", "Rs {paid} was returned on {pdate}")],
         other="Reply of {b}: The full amount was paid before the complaint was lodged.", qa="alleging non-payment", qb="full amount was paid"),
]
ALL_TEMPLATES = TEMPLATES + TEMPLATES2

KN = dict(script="kn", names=["ರಮೇಶ್", "ಸುನೀತಾ", "ಅನಿಲ್", "ಕವಿತಾ"], q="{a} {b}ಗೆ ಎಷ್ಟು ಸಾಲ ನೀಡಿದರು?", text="{a} {b}ಗೆ {amt} ರೂಪಾಯಿ ಸಾಲ ನೀಡಿದರು. {days} ದಿನಗಳಲ್ಲಿ ಮರುಪಾವತಿ ಮಾಡಬೇಕು.", quote="{amt} ರೂಪಾಯಿ ಸಾಲ ನೀಡಿದರು", ans="{a} {b}ಗೆ {amt} ರೂಪಾಯಿ ಸಾಲ ನೀಡಿದರು.")
BN = dict(script="bn", names=["রমেশ", "সুনীতা", "অনিল", "কবিতা"], q="{a} {b}-কে কত টাকা ধার দিয়েছেন?", text="{a} {b}-কে {amt} টাকা ধার দিয়েছেন। {days} দিনের মধ্যে ফেরত দিতে হবে।", quote="{amt} টাকা ধার দিয়েছেন", ans="{a} {b}-কে {amt} টাকা ধার দিয়েছেন।")
MR = dict(script="mr", names=["रमेश", "सुनीता", "अनिल", "कविता"], q="{a} यांनी {b} यांना किती रुपये उसने दिले?", text="{a} यांनी {b} यांना {amt} रुपये उसने दिले. {days} दिवसांत परतफेड करायची आहे.", quote="{amt} रुपये उसने दिले", ans="{a} यांनी {b} यांना {amt} रुपये उसने दिले.")
from evals.campaign import HI, TA, TE  # noqa: E402

INDIC_ALL = [HI, TE, TA, KN, BN, MR]
HOSTILE_EN = ["He lied about it.", "She is a liar.", "That is deceitful.", "They are dishonest.", "This was a fraudulent scheme.", "He cheated her.", "It amounts to perjury.", "The other side is lying."]
HOSTILE_IN = {"hi": "उसने झूठ बोला।", "te": "అతను అబద్ధం చెప్పాడు.", "ta": "அவர் பொய் சொன்னார்.", "kn": "ಅವನು ಸುಳ್ಳು ಹೇಳಿದ.", "bn": "সে মিথ্যা বলেছে।", "mr": "तो खोटे बोलला."}
ABSENCE_POOL = ["bank guarantee", "notarised affidavit", "arbitration clause", "site inspection report", "handwriting expert", "insurance cover note", "trade licence", "power of attorney", "mortgage deed"]
LAW_QUESTIONS = ["What is the limitation period for this?", "Which court has jurisdiction?", "What remedy does the statute give?"]
FILENAMES = lambda n: [f"doc{i}.txt" for i in range(1, n + 1)]  # noqa: E731
ACCENT_NAMES = ["René Dubois", "Zoë Müller", "José Álvarez", "Renée Brontë", "Søren Åberg"]


# ------------------------------------------------------------------ quote damage
def _digit_positions(s):
    return [i for i, c in enumerate(s) if c.isdigit()]


def damage(op: str, q: str, rng: random.Random, doc: str = "") -> str:
    words = q.split(" ")
    if op == "exact":
        return q
    if op == "upper":
        return q.upper()
    if op == "lower":
        return q.lower()
    if op == "spaces":
        return q.replace(" ", "   ")
    if op == "newline":
        return q.replace(" ", "\n")
    if op == "smartq":
        return q.replace("'", "’").replace('"', "“")
    if op == "endash":
        return q.replace("-", "–")
    if op == "zwsp":
        k = rng.randrange(1, max(2, len(q) - 1))
        return q[:k] + "​" + q[k:]
    if op == "softhyphen":
        k = rng.randrange(1, max(2, len(q) - 1))
        return q[:k] + "­" + q[k:]
    if op == "nbsp":
        return q.replace(" ", " ")
    if op == "trailing":
        return q + " and further"
    if op == "leading":
        return "and further " + q
    if op == "trunc_digit":
        return q[:-1] if q and q[-1].isdigit() else q[: max(12, len(q) - 3)]
    if op == "ext_digit":
        return q + "0" if q and q[-1].isdigit() else q + "9"
    if op == "cut_end":
        return q[:-2]
    if op == "cut_start":
        return q[2:]
    if op == "short":
        return q[:11]
    if op == "twelve":
        return q[:12]
    if op == "empty":
        return ""
    if op == "blank":
        return "   \n  "
    if op == "digit_change":
        pos = _digit_positions(q)
        if not pos:
            return q
        k = rng.choice(pos)
        return q[:k] + str((int(q[k]) + rng.randint(1, 9)) % 10) + q[k + 1:]
    if op == "word_drop" and len(words) > 3:
        del words[rng.randrange(1, len(words) - 1)]
        return " ".join(words)
    if op == "word_swap" and len(words) > 3:
        i = rng.randrange(0, len(words) - 1)
        words[i], words[i + 1] = words[i + 1], words[i]
        return " ".join(words)
    if op == "word_replace" and len(words) > 3:
        words[rng.randrange(1, len(words) - 1)] = "unpaid"
        return " ".join(words)
    if op == "homoglyph":
        return q.translate(str.maketrans({"a": "а", "e": "е", "o": "о", "c": "с", "p": "р"}))
    if op == "fullwidth":
        return q.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
    if op == "bidi":
        k = len(q) // 2
        return q[:k] + "‮" + q[k:]
    if op == "combining":
        for k, c in enumerate(q):
            if c.isalpha():
                return q[: k + 1] + "́" + q[k + 1:]
        return q
    if op == "nfd":
        return unicodedata.normalize("NFD", q)
    if op == "nfc":
        return unicodedata.normalize("NFC", q)
    return q


OPS = ["exact"] * 6 + ["upper", "lower", "spaces", "newline", "smartq", "endash", "zwsp", "softhyphen", "nbsp", "trailing", "leading", "trunc_digit", "ext_digit", "cut_end", "cut_start", "short", "twelve",
       "empty", "blank", "digit_change", "word_drop", "word_swap", "word_replace", "homoglyph", "fullwidth", "bidi", "combining", "nfd", "nfc"]


def ref_for(rng, index: int, n_docs: int, mode: str = "good") -> object:
    """A reference to document `index` (0-based), spelled in one of the ways a model writes it; or a bad one."""
    if mode == "missing":
        return rng.choice([None, "", "   "])
    if mode == "out_of_range":
        return rng.choice(["DOC-99", "DOC-00", "DOC-" + str(n_docs + 1), "document one"])
    k = index + 1
    return rng.choice([f"DOC-{k:02d}", f"DOC-{k:02d}", f"DOC-{k}", f"doc {k}", f"[DOC-{k:02d}]", f"doc_{k}", f"Doc-{k:02d}", f"doc{k}.txt", f"DOC{k}"])


# ------------------------------------------------------------------ documents
def indic_doc(rng, year):
    lang = rng.choice(INDIC_ALL)
    a, b = rng.sample(lang["names"], 2)
    p = dict(a=a, b=b, amt=inr(rng.randrange(25, 9500) * 1000), days=str(rng.choice([15, 30, 45, 60])))
    return lang["text"].format(**p), lang["quote"].format(**p), lang["q"].format(**p), lang["ans"].format(**p), lang["script"]


def build_matter(rng, year, fictional, shape):
    """-> docs[list[str]], anchors[list[(doc_index, quote, question, answer)]], language"""
    language = "en"
    w = World(rng, year, fictional, rng.choice(["long", "slash", "iso", "ord", "short"]), rng.choice(["plain", "slash", "paise"]))
    w.t = rng.choice(ALL_TEMPLATES)
    prefix = f"Matter set in the invented land of {rng.choice(FICTIONAL)}. " if fictional else ""
    w.text, w.other = prefix + w.t["text"].format(**w.p), w.t["other"].format(**w.p)
    facts = [(q, a.format(**w.p), quote.format(**w.p)) for q, a, quote in w.t["facts"]]
    docs, anchors = [w.text], [(0, quote, q, a) for q, a, quote in facts]
    if shape == "plain":
        pass
    elif shape == "multi":
        extra = []
        for _ in range(rng.randint(2, 5)):
            f = World(rng, year, False)
            f.t = rng.choice(ALL_TEMPLATES)
            extra.append(f.t["text"].format(**f.p))
        parts = [w.text] + extra
        rng.shuffle(parts)
        docs = ["\n\n".join(parts) + "\n\n- item one\n- item two\n"]
        anchors = [(0, quote, q, a) for q, a, quote in facts]
    elif shape == "table":
        p = w.p
        docs = [f"Item | Amount\nGoods | Rs {p['amt']}\nPaid | Rs {p['paid']}\nDate | {p['date']}\nRef | {p['inv']}"]
        anchors = [(0, f"Goods | Rs {p['amt']}", "What are the goods?", f"Rs {p['amt']}"), (0, f"Paid | Rs {p['paid']}", "What was paid?", f"Rs {p['paid']}"), (0, f"Date | {p['date']}", "What date?", p["date"])]
    elif shape == "indic":
        text, quote, q, ans, language = indic_doc(rng, year)
        docs, anchors = [text], [(0, quote, q, ans)]
    elif shape == "accent":
        n1, n2 = rng.sample(ACCENT_NAMES, 2)
        docs = [f"{n1} agreed to pay {n2} the sum of Rs {w.p['amt']} on {w.p['date']}. {n2} gave a receipt to {n1} the same day."]
        anchors = [(0, f"{n1} agreed to pay {n2} the sum of Rs {w.p['amt']}", "Who agreed to pay?", n1), (0, f"{n2} gave a receipt to {n1}", "Who gave a receipt?", n2)]
    elif shape == "bignum":
        big = rng.choice(["4,00,00,000", "12,50,00,000", "40,000,000", "1,00,000", "9,99,999", "250,000.50"])
        docs = [f"The agreed price was Rs {big} in total. A further Rs 1,000 was paid. Invoice 77{rng.randint(10, 99)} refers."]
        anchors = [(0, f"agreed price was Rs {big} in total", "What was the price?", big), (0, "further Rs 1,000 was paid", "What was paid?", "Rs 1,000")]
    elif shape == "multidoc":
        n = rng.randint(2, 6)
        docs, anchors = [], []
        for i in range(n):
            f = World(rng, year, fictional)
            f.t = rng.choice(ALL_TEMPLATES)
            docs.append(f.t["text"].format(**f.p))
            q, a, quote = f.t["facts"][rng.randrange(3)]
            anchors.append((i, quote.format(**f.p), q, a.format(**f.p)))
    elif shape in ("long_under", "long_over"):
        paras = []
        target = 40_000 if shape == "long_under" else 120_000
        size = 0
        while size < target:
            f = World(rng, year, False)
            f.t = rng.choice(ALL_TEMPLATES)
            t = f.t["text"].format(**f.p)
            paras.append(t)
            size += len(t) + 2
        pos = rng.randrange(len(paras))
        paras[pos] = w.text
        docs = ["\n\n".join(paras)]
        anchors = [(0, quote, q, a) for q, a, quote in facts]
    return docs, anchors, language


SHAPES = ["plain"] * 6 + ["multi"] * 3 + ["table"] * 2 + ["indic"] * 2 + ["accent", "bignum", "bignum", "multidoc", "multidoc", "multidoc", "long_under", "long_over"]


def claim_for(rng, docs, anchors, op, kind_roll):
    """One scripted claim and a label for the damage applied."""
    if kind_roll < 0.70:
        i, quote, q, ans = rng.choice(anchors)
        doc = docs[i] if i < len(docs) else ""
        use_op = op
        if op in ("nfd", "nfc"):
            use_op = op
        mode = rng.choices(["good", "wrong_doc", "missing", "out_of_range"], [80, 10, 5, 5])[0]
        target = i
        if mode == "wrong_doc" and len(docs) > 1:
            target = rng.choice([k for k in range(len(docs)) if k != i])
        elif mode == "wrong_doc":
            mode = "good"
        cite_ref = ref_for(rng, target, len(docs), mode)
        supports = rng.choices(["YES", "PARTIAL", "NO", ""], [82, 8, 5, 5])[0]
        kind = rng.choice(["FACTUAL"] * 18 + ["factual", "Factual"])
        text = ans.rstrip(".") if rng.random() > 0.05 else ans.rstrip(".") + " " + rng.choice(HOSTILE_EN)
        return claim(text, [cite(cite_ref, damage(use_op, quote, rng, doc))], kind=kind, supports=supports), use_op
    if kind_roll < 0.82:
        present = rng.random() < 0.3
        pool = [t for t in ABSENCE_POOL if t not in " ".join(docs).lower()]
        names = [w for d in docs for w in d.split() if len(w) > 4 and w.isalpha()]
        term = rng.choice(names) if present and names else rng.choice(pool)
        style = rng.choice(["linked", "linked", "linked", "unlinked", "empty", "short", "case", "two"])
        terms = {"linked": [term], "unlinked": ["xyzzy plugh"], "empty": [], "short": ["ab"], "case": [term.upper()], "two": [term, rng.choice(pool)]}[style]
        text = f"There is no {term} in the file" if style != "unlinked" else "There is nothing of that kind in the file"
        return claim(text, kind="ABSENCE", terms=terms), "absence-" + style + ("-present" if present else "")
    if kind_roll < 0.90:
        return claim("The law is as I recall it", [lib("FAKE-LAW-S", "the statute provides exactly this")] if rng.random() < 0.8 else [], kind=rng.choice(["LEGAL", "legal"])), "legal"
    if kind_roll < 0.95:
        i, quote, q, ans = rng.choice(anchors)
        return claim("A suggested next step: " + ans.rstrip("."), [cite(ref_for(rng, i, len(docs)), damage(op, quote, rng))] if rng.random() < 0.7 else [], kind="PROCEDURAL"), "procedural"
    i, quote, q, ans = rng.choice(anchors)
    return claim(ans.rstrip("."), [cite(ref_for(rng, i, len(docs)), quote)], kind=rng.choice(["OTHER", "", "unknown"])), "oddkind"


def make_case(n: int) -> dict:
    rng = random.Random(f"stress-{n}")
    year = 1990 + (n * 29 + 7) % 37
    fictional = n % 10 == 3
    shape = rng.choice(SHAPES)
    docs, anchors, language = build_matter(rng, year, fictional, shape)
    k = rng.choices([1, 2, 3, 4, 5], [30, 30, 20, 12, 8])[0]
    first_op = OPS[n % len(OPS)]  # every damage is the first claim's damage in a fixed share of cases
    claims, labels = [], []
    for j in range(k):
        op = first_op if j == 0 else rng.choice(OPS)
        if op in ("nfd", "nfc") and shape not in ("accent", "indic"):
            op = "exact"
        c, label = claim_for(rng, docs, anchors, op, rng.random() if j else rng.choice([0.1, 0.1, 0.1, 0.75, 0.85, 0.92]) if n % 7 == 0 else rng.random())
        claims.append(c)
        labels.append(label)
    question = rng.choice(anchors)[2]
    answer = rng.choice(anchors)[3]
    if rng.random() < 0.18:
        answer += " " + (HOSTILE_IN.get(language) if language in HOSTILE_IN and rng.random() < 0.7 else rng.choice(HOSTILE_EN))
    uncertainty = rng.choice(["", "Not all points could be checked.", ""])
    case = {"id": f"S{n:04d}-{labels[0].split('-')[0]}-{shape}-y{year}" + ("-fic" if fictional else ""), "n": n, "year": year, "shape": shape, "fictional": fictional, "question": question,
            "language": language if language in ("hi", "te", "ta", "kn", "bn", "mr") else "en", "documents": docs, "labels": labels, "gold": gold(answer, claims, uncertainty=uncertainty)}
    if rng.random() < 0.08:
        case["question"] = rng.choice(LAW_QUESTIONS)
    assert all(isinstance(d, str) and d.strip() for d in docs)
    return case


def all_cases(count: int = 3000) -> list[dict]:
    cases = [make_case(i) for i in range(count)]
    assert len({c["id"] for c in cases}) == len(cases)
    return cases


if __name__ == "__main__":
    import collections

    cs = all_cases()
    print(len(cs), dict(collections.Counter(c["shape"] for c in cs)))
    print(collections.Counter(a for c in cs for a in c["labels"]).most_common(12))
    print(sum(len(c["documents"]) for c in cs), "documents", auditor.BUDGET)
