"""Applies the Gazette notifications in data/legal_library/_commencement_notifications.json to the loaded Acts (instruments) whose own text gives no start date, so the date check can use them.
A date is shown with its source and stays UNVERIFIED until a named person has reviewed it (scripts/commencement_review.py). Safe to run again.

    DB_NAME=vidhi_dev python scripts/apply_commencement_notifications.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import legal_store  # noqa: E402


async def main() -> None:
    print("database:", os.environ["DB_NAME"])
    done = await legal_store.refresh_commencement()
    for d in done:
        print(f"  {d['instrument']}: from {d['from']} ({d['basis']}) by {d['notification']}")
    print(f"{len(done)} Act(s) updated")


if __name__ == "__main__":
    asyncio.run(main())
