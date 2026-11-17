"""Startup check for missing settings. Reports NAMES only, never values.

On a live site (APP_URL is an https address, the same test lib/stand_ins uses) a missing required setting stops the app from starting, with the names listed, instead of
failing later in a request. On a laptop (http address) it only logs a warning for the same names, so local work is not blocked."""

import logging
import os

logger = logging.getLogger("vidhi.startup")

REQUIRED_LIVE = ("MONGO_URL", "DB_NAME", "APP_URL", "CORS_ORIGINS", "LINK_SECRET", "WEBHOOK_CRON_SECRET", "DATA_ENCRYPTION_KEY")  # uploads are encrypted at rest on a live site
ONE_OF_LIVE = (("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "NVIDIA_API_KEY", "MISTRAL_API_KEY", "ZAI_API_KEY"),)  # at least one model provider


def is_live() -> bool:
    return os.environ.get("APP_URL", "").strip().lower().startswith("https://")


def missing() -> list[str]:
    out = [n for n in REQUIRED_LIVE if not os.environ.get(n, "").strip()]
    if is_live():
        if "*" in [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",")]:
            out.append("CORS_ORIGINS (a wildcard * is not allowed on a live site: name your own address)")
        if os.environ.get("COOKIE_SECURE", "true").strip().lower() == "false":
            out.append("COOKIE_SECURE (must not be false on a live https site)")
        if os.environ.get("ENABLE_DOCS", "false").strip().lower() == "true":
            out.append("ENABLE_DOCS (the interactive API pages must be off on a live site)")
    for group in ONE_OF_LIVE:
        if not any(os.environ.get(n, "").strip() for n in group):
            out.append(" or ".join(group))
    return out


def enforce() -> None:
    names = missing()
    if not names:
        return
    if is_live():
        raise RuntimeError("These settings are missing and the app will not start without them on a live site: " + "; ".join(names) + ". See .env.example. Values are never printed.")
    logger.warning("Settings that a live site needs and this environment does not have (fine for local work): %s", "; ".join(names))
