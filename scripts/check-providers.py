"""Checks which AI providers in your .env actually answer, with one tiny request each. Prints names and results only:
never a key. Costs a fraction of a paisa.

    cd backend && python ../scripts/check-providers.py            (reads ../.env)
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

root = Path(__file__).resolve().parent.parent
load_dotenv(root / ".env")
sys.path.insert(0, str(root / "backend"))
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")  # lib.ai imports the db lazily; nothing is written
os.environ.setdefault("DB_NAME", "vidhi_check")

from lib import ai  # noqa: E402

PROMPT = 'Reply with exactly this JSON and nothing else: {"ok": true}'


async def one(provider: str, tier: str) -> str:
    token = ai._TIER.set(tier)
    try:
        text = await asyncio.wait_for(ai._call_text(provider, "You reply with JSON only.", PROMPT, json_mode=True), 60)
        parsed = ai.parse_json_object(text)
        return "OK" if parsed and parsed.get("ok") else f"answered but not as asked: {text[:60]!r}"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
            if os.environ.get(k):
                msg = msg.replace(os.environ[k], "***")
        return f"FAILED ({type(exc).__name__}: {msg[:140]})"
    finally:
        ai._TIER.reset(token)


async def main() -> None:
    for provider in ai.PROVIDERS:
        if not ai.provider_configured(provider):
            print(f"{provider:7} not configured (no key in .env)")
            continue
        for tier in ("free", "full"):
            if tier == "free" and provider in ("sonnet", "haiku"):
                continue  # the free plan never uses Claude models
            print(f"{provider:7} {tier:4} {ai.provider_model(provider, tier):34} {await one(provider, tier)}")


asyncio.run(main())
