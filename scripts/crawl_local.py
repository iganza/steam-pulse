"""Local full-catalog crawler — runs metadata and/or review crawl locally.

Reads pending rows from app_catalog, processes them concurrently, and writes
results directly to the local Postgres DB.  No SQS, no Step Functions, no LLM.

Usage:
  # Phase 1: crawl all game metadata (~6-15 hours for 170k games)
  poetry run python scripts/crawl_local.py --phase metadata

  # Phase 2: crawl reviews for eligible games (>=500 reviews)
  poetry run python scripts/crawl_local.py --phase reviews

  # Both phases in sequence
  poetry run python scripts/crawl_local.py --phase both

  # Tune concurrency (default 5 — conservative to avoid Steam 429s)
  poetry run python scripts/crawl_local.py --phase metadata --concurrency 8

  # Dry-run: show pending counts only
  poetry run python scripts/crawl_local.py --dry-run

Requires:
  DATABASE_URL (or defaults to postgresql://steampulse:dev@127.0.0.1:5432/steampulse)
  STEAM_API_KEY in .env
"""

import argparse
import asyncio
import logging
import os
import sys
import time

import httpx
import psycopg2
from dotenv import load_dotenv

# Add source roots
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "library-layer"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "lambda-functions"))

load_dotenv(os.path.join(REPO_ROOT, ".env"))

from library_layer.steam_source import DirectSteamSource  # noqa: E402
from lambda_functions.app_crawler.handler import crawl_app  # noqa: E402
from lambda_functions.review_crawler.handler import crawl_reviews  # noqa: E402

logging.basicConfig(
    level=logging.WARNING,  # suppress per-game debug noise
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
progress_logger = logging.getLogger("crawl.progress")
progress_logger.setLevel(logging.INFO)
progress_logger.propagate = False
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
progress_logger.addHandler(_handler)

DB_URL = os.getenv("DATABASE_URL", "postgresql://steampulse:dev@127.0.0.1:5432/steampulse")

# Disable SFN and review queue triggers — we drive the pipeline manually
os.environ["SFN_ARN"] = ""
os.environ["REVIEW_CRAWL_QUEUE_URL"] = ""


def _conn() -> "psycopg2.connection":
    return psycopg2.connect(DB_URL)


def _count_pending(phase: str) -> tuple[int, int]:
    """Return (pending, total) for the given phase."""
    with _conn() as conn:
        with conn.cursor() as cur:
            if phase == "metadata":
                cur.execute("SELECT COUNT(*) FROM app_catalog WHERE meta_status = 'pending'")
                pending = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM app_catalog")
                total = cur.fetchone()[0]
            else:
                # Only count games where metadata is done AND reviews are pending
                cur.execute(
                    "SELECT COUNT(*) FROM app_catalog WHERE review_status = 'pending' AND meta_status = 'done'"
                )
                pending = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM app_catalog WHERE meta_status = 'done'"
                )
                total = cur.fetchone()[0]
    return pending, total


def _next_batch(phase: str, batch_size: int) -> list[int]:
    """Read the next batch of pending appids from the DB."""
    with _conn() as conn:
        with conn.cursor() as cur:
            if phase == "metadata":
                cur.execute(
                    """
                    SELECT appid FROM app_catalog
                    WHERE meta_status = 'pending'
                    ORDER BY appid
                    LIMIT %s
                    """,
                    (batch_size,),
                )
            else:
                cur.execute(
                    """
                    SELECT appid FROM app_catalog
                    WHERE review_status = 'pending' AND meta_status = 'done'
                    ORDER BY review_count DESC NULLS LAST
                    LIMIT %s
                    """,
                    (batch_size,),
                )
            return [row[0] for row in cur.fetchall()]


async def _process_one(
    appid: int,
    phase: str,
    steam: DirectSteamSource,
    sem: asyncio.Semaphore,
) -> str:
    """Process one appid; returns 'done', 'skipped', or 'failed'."""
    async with sem:
        c = _conn()
        try:
            if phase == "metadata":
                ok = await crawl_app(appid, steam, c)
            else:
                ok = await crawl_reviews(appid, steam, c)
            return "done" if ok else "skipped"
        except Exception as exc:
            logger.warning("appid=%d unexpected error: %s", appid, exc)
            return "failed"
        finally:
            c.close()


async def run_phase(phase: str, concurrency: int) -> None:
    pending, total = _count_pending(phase)
    if pending == 0:
        progress_logger.info("[%s] Nothing pending — skipping phase.", phase)
        return

    progress_logger.info(
        "[%s] Starting — %d pending of %d total | concurrency=%d",
        phase, pending, total, concurrency,
    )

    sem = asyncio.Semaphore(concurrency)
    batch_size = concurrency * 4  # read ahead a bit

    done = skipped = failed = 0
    start = time.monotonic()
    last_report = start

    async with httpx.AsyncClient(timeout=30.0) as client:
        steam = DirectSteamSource(client)

        while True:
            batch = _next_batch(phase, batch_size)
            if not batch:
                break

            results = await asyncio.gather(*[
                _process_one(appid, phase, steam, sem) for appid in batch
            ])

            for r in results:
                if r == "done":
                    done += 1
                elif r == "skipped":
                    skipped += 1
                else:
                    failed += 1

            now = time.monotonic()
            if now - last_report >= 30 or (done + skipped + failed) % 100 == 0:
                elapsed = now - start
                processed = done + skipped + failed
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = (pending - processed) / rate if rate > 0 else 0
                progress_logger.info(
                    "[%s] %d/%d processed | done=%d skipped=%d failed=%d | "
                    "%.1f/min | ~%.0f min left",
                    phase, processed, pending, done, skipped, failed,
                    rate * 60, remaining / 60,
                )
                last_report = now

    elapsed = time.monotonic() - start
    progress_logger.info(
        "[%s] Complete — done=%d skipped=%d failed=%d in %.1f min",
        phase, done, skipped, failed, elapsed / 60,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Local full-catalog Steam crawler (no LLM)")
    p.add_argument(
        "--phase",
        choices=["metadata", "reviews", "both"],
        default="metadata",
        help="Which crawl phase to run (default: metadata)",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent Steam API requests (default: 1 — Steam rate limits aggressively)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show pending counts and exit",
    )
    args = p.parse_args()

    if args.dry_run:
        for phase in ("metadata", "reviews"):
            pending, total = _count_pending(phase)
            print(f"  {phase:10} {pending:>7} pending / {total:>7} total")
        return

    phases = ["metadata", "reviews"] if args.phase == "both" else [args.phase]
    for phase in phases:
        asyncio.run(run_phase(phase, args.concurrency))


if __name__ == "__main__":
    main()
