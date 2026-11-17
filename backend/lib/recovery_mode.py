"""Two switches for Legal Recovery.

MASTER: RECOVERY_ENABLED. OFF by default (owner, 2026-11-15: "remove legal recovery from the app"): Legal Recovery is not part of the app. Its menu entries, pages and search results are hidden, every /recovery
route answers "not available", and the reminder and statement e-mail jobs send nothing. NOTHING is deleted: the code, the tests and every saved case stay, and RECOVERY_ENABLED=true brings it all back.

SECOND: RECOVERY_FULL_FLOW, which only matters when the master switch is on. Off (the default): Legal Recovery is a small free helper - eligibility questions, the free portal first, a notice to download or copy,
three dates the person types. On (RECOVERY_FULL_FLOW=true): the earlier full flow as well - sending the notice by email, escalation steps, the full case page.
Nothing is deleted when it is off: the code, the tests and the saved data stay, and turning the switch on brings everything back."""

import os

from fastapi import HTTPException

NOT_AVAILABLE = "Sending the notice by email is not available in this version of Legal Recovery. Download the notice and send it yourself."


NOT_PART_OF_APP = "Legal Recovery is not available in this version of VIDHI."


def enabled() -> bool:
    return os.environ.get("RECOVERY_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def require_enabled() -> None:
    """Route dependency on every Legal Recovery route: 404 while the master switch is off."""
    if not enabled():
        raise HTTPException(status_code=404, detail=NOT_PART_OF_APP)


def full_flow() -> bool:
    return os.environ.get("RECOVERY_FULL_FLOW", "").strip().lower() in ("1", "true", "yes", "on")


def require_full_flow() -> None:
    """Route dependency: the route answers 'not available' while the switch is off."""
    if not full_flow():
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
