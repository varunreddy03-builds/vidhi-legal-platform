"""Rare, guarded illustration making (Gemini image model).

Meant only for a simple explanatory picture (for example a timeline or a diagram of who owes whom). It is OFF unless IMAGE_GEN_ENABLED=true, Pro only,
capped per organisation per month (IMAGE_MONTHLY_CAP, default 3), always labelled AI-generated, and refuses prompts that ask for real people, documents,
IDs, signatures, stamps or anything that could pass as evidence. The model is IMAGE_MODEL (default below; check Google's current image model list).
IMAGEGEN_STUB=true is for tests/dev only (returns a tiny picture, no network)."""

import base64
import os
import re

from lib import aibudget

DEFAULT_MODEL = "gemini-2.5-flash-image"
MAX_PROMPT = 500
# a 1x1 transparent PNG
STUB_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")

_REFUSED = (
    "photo", "photograph", "realistic", "real person", "portrait", "face", "selfie", "celebrity", "signature", "signed", "stamp", "seal", "letterhead",
    "aadhaar", "aadhar", "pan card", "passport", "licence", "license", "id card", "certificate", "court order", "judgment", "judgement", "notice",
    "receipt", "invoice", "cheque", "bank statement", "evidence", "forge", "fake", "counterfeit", "screenshot", "currency note", "banknote",
    "तस्वीर", "फोटो", "हस्ताक्षर", "मुहर", "आधार", "पासपोर्ट", "प्रमाणपत्र", "रसीद", "चेक", "सबूत", "नकली",
)


class ImageError(Exception):
    pass


def enabled() -> bool:
    return os.environ.get("IMAGE_GEN_ENABLED", "false").lower() == "true"


def monthly_cap() -> int:
    return int(os.environ.get("IMAGE_MONTHLY_CAP", "3"))


def stub_enabled() -> bool:
    return os.environ.get("IMAGEGEN_STUB", "false").lower() == "true"


def refusal(prompt: str) -> str | None:
    """Why this prompt is not allowed, or None."""
    low = prompt.casefold()
    for word in _REFUSED:
        if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", low) if word.isascii() else word in low:
            return f"Illustrations cannot show real people, documents, IDs, signatures, stamps or anything that could pass as evidence (\"{word}\")."
    return None


def wrap(prompt: str) -> str:
    return (
        "Create a simple, clean explanatory illustration in flat vector style. No text, no letters, no real people or faces, no logos, no documents, "
        f"no signatures or stamps. Subject: {prompt.strip()}"
    )


async def generate(prompt: str) -> bytes:
    """PNG bytes. Raises ImageError."""
    if stub_enabled():
        return STUB_PNG
    from google.genai import types

    from lib.ai import _client

    async with aibudget.fixed("image", 1, task="image"):
        client = _client()  # keep it referenced for the whole call (see lib/ai.py)
        resp = await client.aio.models.generate_content(
            model=os.environ.get("IMAGE_MODEL") or DEFAULT_MODEL, contents=wrap(prompt),
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
    for cand in getattr(resp, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                return data
    raise ImageError("the model returned no picture")