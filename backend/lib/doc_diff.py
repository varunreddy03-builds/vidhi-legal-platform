"""Compare two documents' text: what was added, deleted or changed, word by word. Pure code (diff-match-patch); no AI, nothing stored, nothing decided.

Both texts are the pages VIDHI read, joined with a blank line. The comparison is on the TEXT READ, not on the look of the file: a scan read with errors will show those errors as changes,
which is why the caller passes the pages' reading warnings along."""

from diff_match_patch import diff_match_patch

MAX_CHARS = 400_000  # per document; above this the comparison is refused rather than run for a long time
TIME_LIMIT = 5.0  # seconds the diff may think; when it runs out it still returns a correct (just less tidy) answer


def _words(text: str) -> list[str]:
    """Split into words and the white space between them, so the diff works on whole words."""
    import re

    return re.findall(r"\s+|\S+", text)


def compare(a: str, b: str) -> dict:
    """{"segments": [{"op": "equal"|"insert"|"delete", "text": str}, ...], "counts": {...}}. `delete` is text only in the first document; `insert` only in the second."""
    if len(a) > MAX_CHARS or len(b) > MAX_CHARS:
        raise ValueError("too long")
    # map every distinct word to one character, diff those, then map back: whole words are never cut in half
    table: dict[str, str] = {}
    back: list[str] = [""]

    def encode(text: str) -> str:
        out = []
        for w in _words(text):
            if w not in table:
                if len(back) >= 0x10000 - 0x800:  # stay below the surrogate range; a huge vocabulary falls back to a plain character diff
                    raise OverflowError
                table[w] = chr(len(back) + 0x100)
                back.append(w)
            out.append(table[w])
        return "".join(out)

    dmp = diff_match_patch()
    dmp.Diff_Timeout = TIME_LIMIT
    try:
        diffs = dmp.diff_main(encode(a), encode(b), False)
        diffs = [(op, "".join(back[ord(c) - 0x100] for c in chunk)) for op, chunk in diffs]
    except OverflowError:
        diffs = dmp.diff_main(a, b)
        dmp.diff_cleanupSemantic(diffs)
    names = {-1: "delete", 0: "equal", 1: "insert"}
    segments = [{"op": names[op], "text": text} for op, text in diffs if text]
    words = lambda op: sum(len(s["text"].split()) for s in segments if s["op"] == op)  # noqa: E731
    return {"segments": segments, "counts": {"added_words": words("insert"), "deleted_words": words("delete"), "unchanged_words": words("equal")}, "identical": all(s["op"] == "equal" for s in segments)}
