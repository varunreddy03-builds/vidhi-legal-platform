"""Database migrations by hand.   python scripts/migrate.py --status    shows what has and has not been applied     python scripts/migrate.py --run    applies what is pending.
The API also applies pending migrations when it starts. Uses MONGO_URL and DB_NAME from the environment (backend/.env is read like the API does)."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from lib import migrations  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--run", action="store_true")
    a = ap.parse_args()
    if a.run:
        result = await migrations.run_pending()
        print(result)
        if result["failed"]:
            return 1
    for row in await migrations.status():
        print(f"{row['id']:<40} {row['state']:<9} {row['description']}" + (f"  ERROR: {row['error']}" if row["error"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
