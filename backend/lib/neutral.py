"""Neutral-wording guard (project rule 2): the app flags inconsistencies, it never says someone 'lied'.

Applied to AI-written text only (never to quoted source passages). A sentence that judges a person's honesty
is replaced by a neutral stub rather than shown; the caller records that wording was adjusted.

The check looks through invisible characters and full-width / compatibility letters ("li​ed", "ｌｉａｒ"), covers English and the other languages the product answers in
(Hindi, Marathi, Telugu, Tamil, Kannada, Malayalam, Bengali, Gujarati, Punjabi, Urdu), and leaves ordinary legal idioms alone ("the burden lies on the plaintiff",
"pleaded not guilty")."""

import re
import unicodedata

from lib.textmatch import INVISIBLE

_BANNED = re.compile(
    r"\b(lied|lies(?!\s+(?:on|upon|with|in|within|between|at|under|outside|beyond|before|solely|entirely|squarely|primarily|largely|heavily|mainly)\b)|lying|lie|liar|liars|"
    r"perjur\w*|dishonest\w*|deceiv\w*|deceit\w*|fabricat\w*|fraudulent\w*|fraudster\w*|defraud\w*|(?:commit(?:ted|ting)?|perpetrat\w*)\s+(?:a\s+)?fraud|swindl\w*|"
    r"cheat\w*|(?<!not )(?<!never )(?<!no )guilty|culprit\w*|false statement\w*|false testimony|untruthful\w*|untrue|falsif\w*|forg(?:ed|ery|eries)|misled|misrepresent\w*)\b",
    re.I,
)
# stems in other scripts, matched anywhere in the text (these scripts have no \b word edges)
_OTHER = (
    "झूठ", "धोखा", "धोखाधड़ी", "बेईमान", "फसवणूक", "खोटे बोल",           # Hindi, Marathi
    "అబద్ధ", "మోసం", "మోసగాడు",                                           # Telugu
    "பொய்", "மோசடி",                                                      # Tamil
    "ಸುಳ್ಳು", "ವಂಚನೆ",                                                    # Kannada
    "നുണ", "വഞ്ചന",                                                       # Malayalam
    "মিথ্যা", "প্রতারণা",                                                  # Bengali
    "જૂઠ", "છેતરપિંડી",                                                    # Gujarati
    "ਝੂਠ", "ਧੋਖਾ",                                                        # Punjabi
    "جھوٹ", "دھوکہ", "دھوکا",                                              # Urdu
)
STUB = "A sentence was removed here because it judged someone's honesty. VIDHI flags differences between sources; please read the quoted passages."
_SPLIT = re.compile(r"(?<=[.!?।॥])\s+|\n+")


def _probe(sentence: str) -> str:
    return unicodedata.normalize("NFKC", INVISIBLE.sub("", sentence))


def _judges_honesty(sentence: str) -> bool:
    p = _probe(sentence)
    return bool(_BANNED.search(p)) or any(w in p for w in _OTHER)


def neutralize(text: str) -> tuple[str, bool]:
    """(text with offending sentences replaced, whether anything changed)."""
    if not text or not _judges_honesty(text):
        return text, False
    out, changed = [], False
    for sentence in _SPLIT.split(text):
        if _judges_honesty(sentence):
            changed = True
            if not out or out[-1] != STUB:
                out.append(STUB)
        elif sentence.strip():
            out.append(sentence.strip())
    return " ".join(out), changed


def is_neutral(text: str) -> bool:
    return not _judges_honesty(text or "")
