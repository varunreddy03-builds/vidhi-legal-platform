"""Searching English law with a question asked in another language.

The verified library is in English. A question in Hindi, Tamil or Telugu shares no words with it, so before searching we ask a light, cheap model
for an English version of the QUESTION ONLY (never documents). The English version is used purely to find candidate library entries; the model
still answers the original question, in its language, and every citation is still verified against the library text by code."""

import logging

from lib import ai, text

logger = logging.getLogger(__name__)
SCHEMA = '{"english": string}'


async def english_query(question: str, session_id: str) -> str:
    """The question in English for searching, or the original if it is already English or the translation fails."""
    if text.mostly_latin(question):
        return question
    try:
        data = await ai.ask_json(
            session_id,
            "Translate this legal question into plain English for a search engine. Keep names, numbers and section numbers exactly. "
            "Do not answer it and add nothing.\nQUESTION: " + question[:1500],
            SCHEMA, purpose="translate-query", tier="free",
        )
        english = str(data.get("english") or "").strip()
        return english if english else question
    except Exception:  # noqa: BLE001 - searching with the original words is a fine fallback
        logger.info("question translation for search failed", exc_info=True)
        return question