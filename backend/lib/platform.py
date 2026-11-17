"""The platform owner (operator of the whole service), which is NOT the same thing as an organisation's Owner role.

PLATFORM_ADMIN_EMAILS lists the email addresses allowed into the admin console (comma separated). To be let in, the account must also have a
CONFIRMED email address and two-step sign-in switched on. Every admin route depends on `require_platform_admin`, which runs on the server; the
interface merely hides the link. A person who is not an admin gets a plain 404, so the console's existence is not revealed."""

import os

from fastapi import Depends, HTTPException

from lib.auth import current_user
from lib.twofactor import is_enabled


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("PLATFORM_ADMIN_EMAILS", "").split(",") if e.strip()}


def is_platform_admin(user: dict) -> bool:
    return bool(user.get("email_verified")) and user.get("email", "").lower() in admin_emails()


async def require_platform_admin(user: dict = Depends(current_user)) -> dict:
    if not is_platform_admin(user):
        raise HTTPException(status_code=404, detail="Not found")
    if not is_enabled(user):
        raise HTTPException(status_code=403, detail="Turn on two-step sign-in (Settings) to use the admin console.")
    return user