"""Which writing system a text is in, from the letters themselves. Plain code, no model.

It says the SCRIPT, never the language: Devanagari is used for Hindi, Marathi, Sanskrit and Nepali, and Latin letters carry English and many other languages. Claiming a language from
a script would be a guess, so the stored value is called `script`. A text is given a script only when at least 80% of its letters are in it; otherwise it is "mixed", and a text with
no letters at all is "none"."""

SCRIPTS = (  # (name, first code point, last code point)
    ("latin", 0x0041, 0x005A), ("latin", 0x0061, 0x007A), ("latin", 0x00C0, 0x024F),
    ("devanagari", 0x0900, 0x097F), ("bengali", 0x0980, 0x09FF), ("gurmukhi", 0x0A00, 0x0A7F), ("gujarati", 0x0A80, 0x0AFF), ("odia", 0x0B00, 0x0B7F),
    ("tamil", 0x0B80, 0x0BFF), ("telugu", 0x0C00, 0x0C7F), ("kannada", 0x0C80, 0x0CFF), ("malayalam", 0x0D00, 0x0D7F),
    ("arabic", 0x0600, 0x06FF), ("arabic", 0x0750, 0x077F), ("ol_chiki", 0x1C50, 0x1C7F), ("meetei_mayek", 0xABC0, 0xABFF),
)
SHARE = 0.8
NAMES = frozenset(n for n, _, _ in SCRIPTS) | {"mixed", "other", "none"}  # every value script_of can return


def judgment_script(opening, title=None) -> str:
    """The script of a judgment record: that of the OPENING of the order (its own words) when it has any letters, otherwise that of the case title. Case titles on eCourts are in Latin letters even
    for an order written in Hindi, so the title alone would call a Hindi order Latin."""
    s = script_of(opening or "")
    return s if s != "none" else script_of(title or "")


def stored_script(opening, title=None) -> str | None:
    """What is stored on a judgment record: None when the script is Latin (almost every record, so nothing is stored), otherwise the script name, "mixed" or "none" (no letters at all: nothing
    is known). A record without a `script` field therefore means "Latin" only for a record that went through this function or the backfill (scripts/judgment_script_backfill.py)."""
    s = judgment_script(opening, title)
    return None if s == "latin" else s


def script_of(text: str) -> str:
    """The script of `text`: a name from SCRIPTS, "mixed", "other" (letters in a script not listed) or "none" (no letters)."""
    counts: dict[str, int] = {}
    letters = 0
    for ch in text or "":
        if not ch.isalpha():
            continue
        letters += 1
        cp = ord(ch)
        for name, lo, hi in SCRIPTS:
            if lo <= cp <= hi:
                counts[name] = counts.get(name, 0) + 1
                break
    if not letters:
        return "none"
    if not counts:
        return "other"
    top, n = max(counts.items(), key=lambda kv: kv[1])
    return top if n / letters >= SHARE else "mixed"
