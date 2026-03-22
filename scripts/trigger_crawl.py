"""Manual trigger script — publishes SNS events to kick off review crawl or analysis.

Usage:
  poetry run python scripts/trigger_crawl.py crawl --appid 440 --dry-run
  poetry run python scripts/trigger_crawl.py crawl --needs-reviews --limit 20
  poetry run python scripts/trigger_crawl.py analyze --appid 440 --dry-run
  poetry run python scripts/trigger_crawl.py analyze --needs-report --limit 10
  poetry run python scripts/trigger_crawl.py analyze --stale-days 30

Publishes the same event models (GameMetadataReadyEvent, ReviewsReadyEvent)
that the automated pipeline uses, so downstream consumers handle them identically.
"""

import argparse
import logging
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "library-layer"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO_ROOT, ".env"))

import boto3  # noqa: E402
import psycopg2  # noqa: E402
from library_layer.events import GameMetadataReadyEvent, ReviewsReadyEvent  # noqa: E402
from library_layer.utils.events import EventPublishError, publish_event  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

console = Console()

REVIEW_ELIGIBILITY_THRESHOLD = 500


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_conn() -> psycopg2.extensions.connection:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        console.print("[red]DATABASE_URL not set[/red]")
        sys.exit(1)
    return psycopg2.connect(db_url)


def query_needs_reviews(threshold: int, limit: int) -> list[tuple[int, str, int]]:
    """Games with review_count >= threshold but 0 crawled reviews."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.appid, g.name, g.review_count
                FROM games g
                LEFT JOIN (
                    SELECT appid, COUNT(*) as crawled FROM reviews GROUP BY appid
                ) r ON g.appid = r.appid
                WHERE g.review_count >= %(threshold)s
                  AND (r.crawled IS NULL OR r.crawled = 0)
                ORDER BY g.review_count DESC
                LIMIT %(limit)s
                """,
                {"threshold": threshold, "limit": limit},
            )
            return cur.fetchall()
    finally:
        conn.close()


def query_needs_report(limit: int) -> list[tuple[int, str, int]]:
    """Games with reviews but no report row."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.appid, g.name, COUNT(r.id) as review_count
                FROM games g
                JOIN reviews r ON g.appid = r.appid
                LEFT JOIN reports rp ON g.appid = rp.appid
                WHERE rp.appid IS NULL
                GROUP BY g.appid, g.name
                HAVING COUNT(r.id) > 0
                ORDER BY COUNT(r.id) DESC
                LIMIT %(limit)s
                """,
                {"limit": limit},
            )
            return cur.fetchall()
    finally:
        conn.close()


def query_stale_reports(days: int, limit: int) -> list[tuple[int, str, object, int]]:
    """Reports older than N days."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.appid, g.name, rp.last_analyzed, COUNT(r.id) as review_count
                FROM games g
                JOIN reviews r ON g.appid = r.appid
                JOIN reports rp ON g.appid = rp.appid
                WHERE rp.last_analyzed < NOW() - %(days)s * INTERVAL '1 day'
                GROUP BY g.appid, g.name, rp.last_analyzed
                ORDER BY rp.last_analyzed ASC
                LIMIT %(limit)s
                """,
                {"days": days, "limit": limit},
            )
            return cur.fetchall()
    finally:
        conn.close()


def _get_game_info(appid: int) -> tuple[str, int]:
    """Return (name, review_count) for a single appid."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, review_count FROM games WHERE appid = %s",
                (appid,),
            )
            row = cur.fetchone()
            if not row:
                console.print(f"[red]appid {appid} not found in games table[/red]")
                sys.exit(1)
            return row[0] or "", row[1] or 0
    finally:
        conn.close()


def _get_review_count(appid: int) -> int:
    """Return number of crawled reviews for an appid."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reviews WHERE appid = %s", (appid,))
            return cur.fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Publish helpers
# ---------------------------------------------------------------------------


def publish_crawl_events(
    games: list[tuple[int, str, int]],
    dry_run: bool,
) -> None:
    """Publish GameMetadataReadyEvent for each game to game-events topic."""
    topic_arn = os.getenv("GAME_EVENTS_TOPIC_ARN")
    if not dry_run and not topic_arn:
        console.print("[red]GAME_EVENTS_TOPIC_ARN not set[/red]")
        sys.exit(1)

    table = Table("appid", "name", "review_count", show_header=True, header_style="bold cyan")
    for appid, name, review_count in games:
        table.add_row(str(appid), name or "", str(review_count or 0))
    console.print(table)

    if dry_run:
        console.print(
            f"\n[yellow][dry-run][/yellow] Would publish {len(games)} GameMetadataReadyEvent(s)"
        )
        return

    sns_client = boto3.client("sns")
    published = 0
    failed = 0

    for appid, _name, review_count in games:
        event = GameMetadataReadyEvent(
            appid=appid,
            review_count=review_count or 0,
            is_eligible=True,
        )
        try:
            publish_event(sns_client, topic_arn, event)
            published += 1
        except EventPublishError as exc:
            logger.error("Failed to publish crawl event for appid=%s: %s", appid, exc)
            failed += 1

    console.print(f"\n[green]Published {published}/{len(games)} events.[/green]", end="")
    if failed:
        console.print(f" [red]{failed} failures.[/red]")
    else:
        console.print()


def publish_analyze_events(
    games: list[tuple],
    dry_run: bool,
) -> None:
    """Publish ReviewsReadyEvent for each game to content-events topic."""
    topic_arn = os.getenv("CONTENT_EVENTS_TOPIC_ARN")
    if not dry_run and not topic_arn:
        console.print("[red]CONTENT_EVENTS_TOPIC_ARN not set[/red]")
        sys.exit(1)

    # Games may have 3 or 4 columns depending on the query
    table_headers = ["appid", "name", "review_count"]
    has_last_analyzed = len(games[0]) == 4 if games else False
    if has_last_analyzed:
        table_headers.insert(2, "last_analyzed")

    table = Table(*table_headers, show_header=True, header_style="bold cyan")
    for row in games:
        if has_last_analyzed:
            appid, name, last_analyzed, review_count = row
            table.add_row(str(appid), name or "", str(last_analyzed), str(review_count))
        else:
            appid, name, review_count = row
            table.add_row(str(appid), name or "", str(review_count))
    console.print(table)

    if dry_run:
        console.print(
            f"\n[yellow][dry-run][/yellow] Would publish {len(games)} ReviewsReadyEvent(s)"
        )
        return

    sns_client = boto3.client("sns")
    published = 0
    failed = 0

    for row in games:
        appid = row[0]
        name = row[1] or ""
        review_count = row[-1]

        event = ReviewsReadyEvent(
            appid=appid,
            game_name=name,
            reviews_crawled=review_count,
        )
        try:
            publish_event(sns_client, topic_arn, event)
            published += 1
        except EventPublishError as exc:
            logger.error("Failed to publish analyze event for appid=%s: %s", appid, exc)
            failed += 1

    console.print(f"\n[green]Published {published}/{len(games)} events.[/green]", end="")
    if failed:
        console.print(f" [red]{failed} failures.[/red]")
    else:
        console.print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trigger_crawl",
        description="Manually trigger review crawl or analysis via SNS events",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # ── crawl
    crawl = sub.add_parser("crawl", help="Publish GameMetadataReadyEvent to game-events topic")
    crawl_target = crawl.add_mutually_exclusive_group(required=True)
    crawl_target.add_argument("--appid", type=int, metavar="N", help="Single game appid")
    crawl_target.add_argument(
        "--needs-reviews",
        action="store_true",
        help="Query games with enough reviews on Steam but 0 crawled",
    )
    crawl.add_argument(
        "--threshold",
        type=int,
        default=REVIEW_ELIGIBILITY_THRESHOLD,
        metavar="N",
        help=f"Minimum review_count for --needs-reviews (default: {REVIEW_ELIGIBILITY_THRESHOLD})",
    )
    crawl.add_argument("--limit", type=int, default=50, metavar="N", help="Max games (default: 50)")
    crawl.add_argument(
        "--dry-run", action="store_true", help="Show what would be published, skip SNS"
    )

    # ── analyze
    analyze = sub.add_parser("analyze", help="Publish ReviewsReadyEvent to content-events topic")
    analyze_target = analyze.add_mutually_exclusive_group(required=True)
    analyze_target.add_argument("--appid", type=int, metavar="N", help="Single game appid")
    analyze_target.add_argument(
        "--needs-report",
        action="store_true",
        help="Query games with reviews but no report",
    )
    analyze_target.add_argument(
        "--stale-days",
        type=int,
        metavar="N",
        help="Query games with reports older than N days",
    )
    analyze.add_argument(
        "--limit", type=int, default=50, metavar="N", help="Max games (default: 50)"
    )
    analyze.add_argument(
        "--dry-run", action="store_true", help="Show what would be published, skip SNS"
    )

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "crawl":
        if args.appid:
            name, review_count = _get_game_info(args.appid)
            games = [(args.appid, name, review_count)]
        else:
            games = query_needs_reviews(args.threshold, args.limit)
            if not games:
                console.print("[yellow]No games found matching criteria[/yellow]")
                return
            console.print(f"Found {len(games)} game(s) needing review crawl\n")
        publish_crawl_events(games, dry_run=args.dry_run)

    elif args.command == "analyze":
        if args.appid:
            name, _ = _get_game_info(args.appid)
            review_count = _get_review_count(args.appid)
            games: list[tuple] = [(args.appid, name, review_count)]
        elif args.needs_report:
            games = query_needs_report(args.limit)
        else:
            games = query_stale_reports(args.stale_days, args.limit)

        if not games:
            console.print("[yellow]No games found matching criteria[/yellow]")
            return
        console.print(f"Found {len(games)} game(s) for analysis\n")
        publish_analyze_events(games, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
