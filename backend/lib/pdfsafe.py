"""Honest PDF text for the exports built with reportlab's built-in fonts.

Those fonts draw only Western European characters. Hindi, Telugu, Tamil and other Indian scripts would come out as black boxes or nothing, and a drawn font is not enough on its own:
reportlab does not do the letter shaping (joined consonants, vowel signs) these scripts need, so a bundled font would still print wrong letter shapes. Until a shaping engine is added,
the PDF says so: every character it cannot draw is shown as '?', and a note at the top tells the reader to use the Word download, which keeps the exact text."""

from xml.sax.saxutils import escape as xml_escape


class Guard:
    def __init__(self) -> None:
        self.count = 0

    def escape(self, text) -> str:
        out = []
        for ch in str(text if text is not None else ""):
            try:
                ch.encode("cp1252")
                out.append(ch)
            except UnicodeEncodeError:
                if ch.isspace() or ch in "​‌‍﻿":  # invisible characters: drop, do not count
                    continue
                out.append("?")
                self.count += 1
        return xml_escape("".join(out))

    def note(self) -> str:
        return (f"Some text in this report is in a script this PDF cannot draw ({self.count} characters are shown as ?). "
                "Download the Word version to read the exact text.")
