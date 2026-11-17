"""Judgments as numbered paragraphs, the paragraph index, and finding a quotation (also when a scan has damaged it). Ten fictional judgments are written here in ten different layouts, so the right answer is known for each.
Nothing real is used and no model is called."""
import random

import pytest

from lib import judgment_paragraphs as jp
from lib import passage_index as pi

TOPICS = ["delay in payment of the invoice", "the cheque returned for insufficient funds", "the tenancy of the shop premises", "wrongful termination of the employee",
          "the boundary of the agricultural land", "supply of defective machinery", "recovery of the loan advance", "the licence of the printing press", "partition of the ancestral house", "refund of the security deposit"]
SENT = ["The appellant states that {t} was never disputed before the trial court.", "The respondent submits that no notice was served and that the claim is barred by delay.",
        "We have heard counsel for both sides and perused the record placed before us.", "It is not disputed that Rs 40,000 was paid on 12 March 2019 towards {t}.",
        "In our view the finding of the trial court on {t} cannot be sustained.", "The appeal is therefore allowed and the impugned order is set aside without any order as to costs."]


def paragraphs_of(seed: int, count: int = 12) -> list[str]:
    rnd = random.Random(seed)
    topic = TOPICS[seed % len(TOPICS)]
    return [" ".join(rnd.choice(SENT).format(t=topic) + f" (ref z{seed}z{i}z{k})" for k in range(rnd.randint(2, 4))) for i in range(1, count + 1)]


HEAD = "IN THE HIGH COURT OF FICTIONAL STATE\nMeera Textiles Ltd. v. Collector of Fictional District\nJUDGMENT\n\n"


def render(paras: list[str], style: str) -> str:
    fmt = {"dot": "{n}. ", "bracket": "[{n}] ", "paren": "({n}) ", "close": "{n}) ", "devanagari": None}[style if style in ("dot", "bracket", "paren", "close") else "devanagari"]
    out = []
    for i, p in enumerate(paras, start=1):
        marker = fmt.format(n=i) if fmt else "".join(chr(0x0966 + int(d)) for d in str(i)) + ". "
        out.append(marker + p)
    return HEAD + "\n\n".join(out) + "\n"


# (name, text, expected paragraph numbers, expected method)
def build_cases():
    cases = []
    for k, style in enumerate(["dot", "bracket", "paren", "close", "devanagari"]):
        paras = paragraphs_of(k)
        cases.append((f"{style} numbering", render(paras, style), paras, list(range(0, 13)), "numbered"))
    paras = paragraphs_of(5)
    text = render(paras, "dot").replace("\n5. ", "\n").replace("\n6. ", "\n")  # the scan lost two markers: 5 and 6 are inside paragraph 4... and 7 follows
    cases.append(("two markers lost", text, None, [0, 1, 2, 3, 4, 7, 8, 9, 10, 11, 12], "numbered"))
    paras = paragraphs_of(6)
    inside = paras[:]
    inside[2] = inside[2] + "\n2010. The year is at the start of this line but is not a paragraph.\n12. Rs 5,000 was the amount, which is not paragraph twelve.\n(i) a list item"
    cases.append(("year, amount and list lines inside a paragraph", render(inside, "dot"), inside, list(range(0, 13)), "numbered"))
    paras = paragraphs_of(7)
    cases.append(("hyphenated line breaks", render(paras, "dot").replace("disputed", "dis-\nputed").replace("respondent", "respon-\ndent"), paras, list(range(0, 13)), "numbered"))
    cases.append(("no numbering at all", HEAD + "\n\n".join(paragraphs_of(8, 7)) + "\n", None, [None] * 8, "blank-lines"))
    paras = paragraphs_of(9, 2)
    cases.append(("too few numbers (2)", render(paras, "dot"), None, [None] * 3, "blank-lines"))
    return cases


CASES = build_cases()


@pytest.mark.parametrize("name,text,paras,numbers,method", CASES, ids=[c[0] for c in CASES])
def test_paragraphs_are_split_on_the_numbers_printed_in_the_judgment(name, text, paras, numbers, method):
    out = jp.split(text)
    assert out["method"] == method
    assert [p["n"] for p in out["paragraphs"]] == numbers
    for p in out["paragraphs"]:
        assert text[p["start"]:p["end"]].strip() == p["text"]  # the offsets point into the judgment
    if method == "numbered":
        assert out["paragraphs"][0]["label"] == "Preamble" and out["paragraphs"][1]["label"] == "Paragraph 1"
        if paras and "2010." not in text:
            assert all(p in out["paragraphs"][i + 1]["text"].replace("-\n", "") for i, p in enumerate(paras))


def test_a_lost_marker_is_reported_not_hidden():
    name, text, *_ = next(c for c in CASES if c[0] == "two markers lost")
    assert any("not found" in w for w in jp.split(text)["warnings"])


def test_a_year_or_amount_at_the_start_of_a_line_is_not_a_paragraph():
    name, text, *_ = next(c for c in CASES if c[0].startswith("year, amount"))
    out = jp.split(text)
    assert [p["n"] for p in out["paragraphs"]] == list(range(0, 13))
    assert "2010. The year" in out["paragraphs"][3]["text"] and "12. Rs 5,000" in out["paragraphs"][3]["text"]


def test_a_missing_number_is_never_made_up():
    out = jp.split(HEAD + "Some words here.\n\nMore words follow here.\n")
    assert out["method"] == "blank-lines" and all(p["n"] is None for p in out["paragraphs"]) and out["warnings"]
    assert jp.split("")["paragraphs"] == [] and jp.split(None)["paragraphs"] == []


def test_long_paragraphs_are_cut_at_sentence_ends_into_passages_that_keep_their_offsets():
    long = "The court considered the matter at length. " * 120
    text = "1. " + long + "\n\n2. Short one here.\n\n3. Another short one.\n"
    paras = jp.split(text)["paragraphs"]
    parts = jp.passages(paras, limit=800)
    assert len(parts) > 6 and all(p["n"] in (1, 2, 3) for p in parts)
    assert all(len(p["text"]) <= 900 for p in parts)
    for p in parts:
        assert text[p["start"]:p["end"]].strip() == p["text"].strip()


# ---- the index ----

@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSAGE_INDEX_DIR", str(tmp_path / "idx"))
    records = [{"id": f"j{k}", "text": c[1]} for k, c in enumerate(CASES)]
    return pi.build(records), records


def test_the_index_finds_the_paragraph_and_the_text_is_read_from_the_judgment(index):
    out, records = index
    assert out["judgments"] == 10 and out["passages"] >= 60 and out["numbered"] == 8
    text = records[0]["text"]
    hits = pi.search(["ref", "z0z4z0"], jid="j0")
    assert hits and hits[0]["jid"] == "j0" and hits[0]["n"] == 4
    assert "(ref z0z4z0)" in text[hits[0]["start"]:hits[0]["end"]]
    assert pi.search(["ref", "z0z4z0"], jid="j1") == []  # another judgment has no such paragraph


def test_find_uses_the_index_and_the_scan_gives_the_same_paragraph(index, monkeypatch):
    out, records = index
    text = records[2]["text"]
    a = pi.find("j2", text, "ref z2z7z1")
    assert a["source"] == "index" and a["hits"][0]["n"] == 7 and "(ref z2z7z1)" in a["hits"][0]["text"]
    monkeypatch.setenv("PASSAGE_INDEX_DIR", str(pi.index_dir() / "missing"))
    b = pi.find("j2", text, "ref z2z7z1")
    assert b["source"] == "scan" and b["hits"][0]["n"] == 7 and b["hits"][0]["text"] == a["hits"][0]["text"]


def test_a_missing_or_damaged_index_means_a_scan_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSAGE_INDEX_DIR", str(tmp_path / "none"))
    assert not pi.available() and pi.search(["delay"]) is None
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / pi.STATE_FILE).write_text("{not json")
    monkeypatch.setenv("PASSAGE_INDEX_DIR", str(tmp_path / "bad"))
    assert pi.search(["delay"]) is None
    (tmp_path / "bad" / pi.STATE_FILE).write_text('{"schema": 1}')
    assert pi.search(["delay"]) is None  # no usable index files in the folder
    text = CASES[0][1]
    assert pi.find("x", text, "ref z0z3z0")["source"] == "scan"


def test_a_rebuild_replaces_the_index_and_nothing_stale_is_found(index):
    out, records = index
    again = pi.build([{"id": "only", "text": "1. Alpha beta gamma delta epsilon.\n\n2. Zeta eta theta iota kappa.\n\n3. Lambda mu nu xi omicron.\n"}])
    assert again["judgments"] == 1
    assert pi.search(["ref", "z0z4z0"]) == []
    assert pi.search(["kappa"])[0]["n"] == 2


def test_query_words_are_not_able_to_change_the_search(index):
    assert pi.search(["delay) OR (court:*"]) is None and pi.search([]) is None
    assert pi.search(["ref"], jid='j0" OR jid:"j1') is None


# ---- finding a quotation ----

def paras_for(k: int) -> list[dict]:
    return jp.split(CASES[k][1])["paragraphs"]


def test_an_exact_quotation_is_found_in_its_paragraph():
    paras = paras_for(0)
    quote = "We have heard counsel for both sides and perused the record placed before us."
    p = next(x for x in paras if quote in x["text"])
    hit = jp.locate_quote(paras, quote)
    assert hit["exact"] is True and hit["n"] == p["n"] and hit["similarity"] == 1.0
    assert jp.locate_quote(paras, quote.upper().replace(" ", "   "))["exact"] is True  # case and spacing are not differences


def test_a_quotation_running_over_two_paragraphs_is_found():
    paras = [{"n": 1, "label": "Paragraph 1", "start": 0, "end": 60, "text": "The court examined the bills and found that the sum was paid"},
             {"n": 2, "label": "Paragraph 2", "start": 62, "end": 120, "text": "in full before the due date, which ends the dispute here."}]
    hit = jp.locate_quote(paras, "found that the sum was paid in full before the due date")
    assert hit["exact"] and hit["n"] == 1 and "into Paragraph 2" in hit["note"]


FIXED = ["Counsel appeared for the parties and the matter was heard on the date fixed by the court.",
         "The respondent submits that the finding of the trial court was filed with the record and perused with care before us. The claim fails.",
         "The appeal is allowed and the order is set aside without costs."]
FIXED_TEXT = HEAD + "\n\n".join(f"{i}. {p}" for i, p in enumerate(FIXED * 2, start=1)) + "\n"
CLEAN = "The respondent submits that the finding of the trial court was filed with the record and perused with care before us."
DAMAGE = [
    ("rn read as m", lambda s: s.replace("m", "rn", 2)),
    ("l and I confused", lambda s: s.replace("l", "I", 3)),
    ("hyphen at a line break", lambda s: s.replace("perused", "per-\nused")),
    ("stray spaces", lambda s: s.replace("record", "rec ord").replace("before", "be fore")),
    ("ligature", lambda s: s.replace("fi", "ﬁ")),
    ("pipe for l", lambda s: s.replace("l", "|", 2)),
]


@pytest.mark.parametrize("name,damage", DAMAGE, ids=[d[0] for d in DAMAGE])
def test_a_scan_damaged_quotation_is_found_but_never_called_exact(name, damage):
    paras = jp.split(FIXED_TEXT)["paragraphs"]
    damaged = damage(CLEAN)
    assert damaged != CLEAN
    hit = jp.locate_quote(paras, damaged)
    p = next(x for x in paras if CLEAN in x["text"])
    assert hit and hit["n"] == p["n"] and hit["exact"] is False and hit["similarity"] >= jp.MIN_SIMILARITY
    assert "approximate" in hit["note"] and p["start"] <= hit["start"] < hit["end"] <= p["end"]


def test_a_different_figure_or_a_lost_not_is_never_matched():
    paras = [{"n": 3, "label": "Paragraph 3", "start": 0, "end": 200, "text": "It is not disputed that Rs 40,000 was paid on 12 March 2019 towards the invoice in question."}]
    assert jp.locate_quote(paras, "It is not disputed that Rs 40,000 was paid on 12 March 2019 towards the invoice")["exact"]
    assert jp.locate_quote(paras, "It is not disputed that Rs 40,800 was paid on 12 March 2019 towards the invoice") is None
    assert jp.locate_quote(paras, "It is disputed that Rs 40,000 was paid on 12 March 2019 towards the invoice") is None
    assert jp.locate_quote(paras, "It is not disputed that Rs 40,000 was paid on 12 March 2018 towards the invoice") is None


def test_text_that_is_not_in_the_judgment_or_too_short_is_not_found():
    paras = paras_for(2)
    assert jp.locate_quote(paras, "The statute of limitation was extended by an ordinance of the governor") is None
    assert jp.locate_quote(paras, "the court") is None
    assert jp.locate_quote(paras, "") is None
    assert jp.locate_quote([], "We have heard counsel for both sides") is None


def test_every_judgment_in_the_set_gives_back_a_quotation_taken_from_each_numbered_paragraph():
    checked = 0
    for name, text, paras, numbers, method in CASES:
        if method != "numbered":
            continue
        got = jp.split(text)["paragraphs"]
        for p in got[1:]:
            sentence = p["text"].split(". ")[0] if ". " in p["text"] else p["text"]
            if len(sentence) < 30 or "-\n" in sentence or "\n" in sentence:
                continue
            hit = jp.locate_quote(got, sentence)
            assert hit and hit["exact"] and hit["n"] in (p["n"], p["n"] - 1), (name, p["n"], sentence)
            checked += 1
    assert checked >= 30
