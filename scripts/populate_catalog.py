"""Populate app_catalog from the full Steam app list.

Fetches all ~170k appids from Steam GetAppList and upserts them into the
app_catalog table (new rows only — existing rows are not touched).

Usage:
  poetry run python scripts/populate_catalog.py
  poetry run python scripts/populate_catalog.py --dry-run
  poetry run python scripts/populate_catalog.py --limit 1000

Requires DATABASE_URL in environment (or .env file).
"""

import argparse
import logging
import os
import sys

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, "src/lambda-functions")
from lambda_functions.crawler.catalog_refresh import fetch_app_list, upsert_catalog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    p = argparse.ArgumentParser(description="Populate app_catalog from Steam GetAppList")
    p.add_argument("--dry-run", action="store_true", help="Fetch only; make no DB writes")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Only process the first N apps (useful for smoke-testing)")
    args = p.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url and not args.dry_run:
        logger.error("DATABASE_URL not set — add it to .env or export it first")
        sys.exit(1)

    logger.info("Fetching Steam app list…")
    api_key = os.getenv("STEAM_API_KEY")
    if not api_key:
        logger.warning("STEAM_API_KEY not set — request may fail (Steam requires a key for GetAppList)")
    with httpx.Client(timeout=30) as client:
        apps = fetch_app_list(client, api_key=api_key)

    apps = [a for a in apps if a.get("name", "").strip()]
    logger.info("Fetched %d named apps from Steam", len(apps))

    if args.limit:
        apps = apps[: args.limit]
        logger.info("Limiting to first %d apps", args.limit)

    if args.dry_run:
        print(f"\n[DRY RUN] Would upsert {len(apps)} apps into app_catalog")
        print(f"{'appid':<12} name")
        print("-" * 50)
        for a in apps[:20]:
            print(f"  {a['appid']:<10} {a['name']!r}")
        if len(apps) > 20:
            print(f"  … and {len(apps) - 20} more")
        return

    conn = psycopg2.connect(db_url)
    new_rows = upsert_catalog(conn, apps)
    conn.close()

    logger.info("Done — %d new rows inserted, %d already existed",
                new_rows, len(apps) - new_rows)


if __name__ == "__main__":
    main()
