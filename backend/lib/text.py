"""Language-aware text tools shared by retrieval. Indian-language text must be searchable as well as English:
the old tokenizer only recognised a-z, so a Hindi, Tamil or Telugu document produced no search tokens at all."""

import re
import unicodedata

# letters, digits and the combining vowel signs of the Indian scripts (Devanagari..Malayalam), Arabic-script languages, Ol Chiki, Meetei Mayek
_WORD = re.compile(r"[\wऀ-ൿ؀-ۿ᱐-᱿ꯀ-꯿]+", re.UNICODE)
_LATIN = re.compile(r"[a-z]")

STOP = {
    # English
    "the", "and", "for", "that", "this", "with", "are", "was", "were", "has", "have", "had", "not", "any", "can", "may", "what", "which", "who",
    "whom", "from", "into", "under", "such", "shall", "will", "would", "should", "could", "their", "there", "than", "then", "its", "his", "her",
    "our", "your", "you", "about",
    # Hindi / Marathi / common Indic function words
    "का", "की", "के", "है", "हैं", "में", "और", "से", "को", "पर", "यह", "था", "थे", "थी", "एक", "कि", "ने", "भी", "तो", "हो", "या", "जो", "इस", "उस",
    "आहे", "आणि", "ना", "ही", "चा", "ची", "चे",
}


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"[​-‏‪-‮⁠﻿]", "", t)


def tokens(text: str) -> list[str]:
    """Words of any script. Latin words need 3+ letters; words in other scripts need 2+ (they carry more per character)."""
    out = []
    for w in _WORD.findall(normalise(text)):
        w = w.strip("_")
        if w in STOP:
            continue
        if _LATIN.search(w[:1]) or w[:1].isascii():
            if len(w) >= 3:
                out.append(w)
        elif len(w) >= 2:
            out.append(w)
    return out


def mostly_latin(text: str) -> bool:
    """True if the letters in the text are mostly English (so no translation is needed before searching)."""
    letters = [c for c in text if c.isalpha()]
    return not letters or sum(1 for c in letters if c.isascii()) / len(letters) >= 0.6