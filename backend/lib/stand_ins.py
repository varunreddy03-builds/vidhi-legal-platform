"""Test-only switches that replace a real service with a fake (scripted AI, captured email, fake payments...). Left on in a live site they fail silently: a demand notice shows as
SENT but only lands in a test table, a "paid" checkout charges nobody. A live site is one whose APP_URL is https, so the app refuses to start there with any of them on."""

import os

STAND_INS = ("AI_STUB", "PAYMENTS_STUB", "EMAIL_DRY_RUN", "VOICE_STUB", "TWILIO_STUB", "WEBPUSH_STUB", "GOOGLE_STUB", "IMAGEGEN_STUB")


def refuse_on_live_site() -> None:
    if not os.environ.get("APP_URL", "").strip().lower().startswith("https://"):
        return
    on = [name for name in STAND_INS if os.environ.get(name, "false").strip().lower() == "true"]
    if on:
        raise RuntimeError(f"Test-only switch(es) {', '.join(on)} are on while APP_URL is a live https address. Turn them off (see .env.example) before starting.")
