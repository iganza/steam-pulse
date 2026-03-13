"""Bootstrap script — seeds the app-crawl-queue with Steam apps.

Usage:
  poetry run python scripts/seed.py --dry-run --limit 5
  poetry run python scripts/seed.py --limit 500
  poetry run python scripts/seed.py           # full catalog

Steps:
  1. Fetch the full Steam app list.
  2. Push all appids to app-crawl-queue (SQS).
  3. After the app-crawler has run, call --seed-reviews to push
     the top 500 (by review_count) to review-crawl-queue.

Flags:
  --dry-run   Print what would be queued; make no SQS or DB calls.
  --limit N   Only process the first N apps (useful for smoke-testing).
  --seed-reviews  Push top N games to review-crawl-queue instead.
"""

import argparse
import asyncio
import json
import logging
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

from library_layer.steam_source import DirectSteamSource

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

APP_QUEUE_ENV = "APP_CRAWL_QUEUE_URL"
REVIEW_QUEUE_ENV = "REVIEW_CRAWL_QUEUE_URL"


# ---------------------------------------------------------------------------
# SQS helper
# ---------------------------------------------------------------------------


def _send_batch(queue_url: str, messages: list[dict]) -> int:
    """Send messages to SQS in batches of 10. Returns count sent."""
    import boto3  # type: ignore[import-untyped]
    sqs = boto3.client("sqs")
    sent = 0
    for i in range(0, len(messages), 10):
        batch = messages[i : i + 10]
        entries = [
            {
                "Id": str(j),
                "MessageBody": json.dumps(msg),
            }
            for j, msg in enumerate(batch)
        ]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = resp.get("Failed", [])
        if failed:
            logger.warning("%d messages failed in batch starting at %d", len(failed), i)
        sent += len(batch) - len(failed)
    return sent


# ---------------------------------------------------------------------------
# App seeding
# ---------------------------------------------------------------------------


async def seed_apps(limit: int | None, dry_run: bool) -> list[dict]:
    """Fetch the app list and push to app-crawl-queue."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        steam = DirectSteamSource(client)
        logger.info("Fetching Steam app list…")
        apps = await steam.get_app_list(limit=limit)

    # Filter out apps without a name (many are DLC stubs)
    apps = [a for a in apps if a.get("name", "").strip()]
    logger.info("Found %d named apps on Steam", len(apps))

    if limit:
        apps = apps[:limit]
        logger.info("Limiting to first %d apps", limit)

    if dry_run:
        print(f"\n[DRY RUN] Would push {len(apps)} apps to app-crawl-queue")
        print(f"{'appid':<10} name")
        print("-" * 50)
        for app in apps[:20]:
            print(f"  {app['appid']:<8} {app['name']!r}")
        if len(apps) > 20:
            print(f"  … and {len(apps) - 20} more")
        return apps

    queue_url = os.getenv(APP_QUEUE_ENV)
    if not queue_url:
        logger.error(
            "%s is not set — cannot push to SQS. Use --dry-run to test without SQS.", APP_QUEUE_ENV
        )
        sys.exit(1)

    messages = [{"appid": a["appid"]} for a in apps]
    sent = _send_batch(queue_url, messages)
    logger.info("Pushed %d appids to app-crawl-queue", sent)
    return apps


# ---------------------------------------------------------------------------
# Review seeding (run after app-crawler has populated review_count)
# ---------------------------------------------------------------------------


async def seed_reviews(limit: int, dry_run: bool) -> None:
    """Push top N apps by review_count to review-crawl-queue."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set — cannot query top games by review_count")
        sys.exit(1)

    import psycopg2

    conn = psycopg2.connect(db_url)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT appid, name, review_count
            FROM games
            WHERE review_count IS NOT NULL
            ORDER BY review_count DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    conn.close()

    if not rows:
        logger.warning("No games with review_count in DB — run app-crawler first")
        return

    if dry_run:
        print(f"\n[DRY RUN] Would push {len(rows)} games to review-crawl-queue")
        print(f"{'appid':<10} {'reviews':<10} name")
        print("-" * 60)
        for appid, name, rc in rows[:20]:
            print(f"  {appid:<8} {rc or 0:<8} {name!r}")
        if len(rows) > 20:
            print(f"  … and {len(rows) - 20} more")
        return

    queue_url = os.getenv(REVIEW_QUEUE_ENV)
    if not queue_url:
        logger.error("%s is not set", REVIEW_QUEUE_ENV)
        sys.exit(1)

    messages = [{"appid": row[0]} for row in rows]
    sent = _send_batch(queue_url, messages)
    logger.info("Pushed %d appids to review-crawl-queue", sent)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seed",
        description="Bootstrap SteamPulse with the Steam catalog",
    )
    p.add_argument("--dry-run", action="store_true", help="Print plan; make no SQS/DB writes")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Process at most N apps (default: all)")
    p.add_argument("--seed-reviews", action="store_true",
                   help="Push top N games to review-crawl-queue (run after app-crawler)")
    return p


async def main() -> None:
    args = _build_parser().parse_args()
    limit = args.limit or (500 if args.seed_reviews else None)

    if args.seed_reviews:
        await seed_reviews(limit=limit or 500, dry_run=args.dry_run)
    else:
        await seed_apps(limit=limit, dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
