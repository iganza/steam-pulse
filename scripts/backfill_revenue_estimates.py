"""Backfill Boxleiter v2 revenue estimates for existing games.

Pure-Python: no LLM calls, no Steam API, no reviews crawled. Reads games,
genres, and tags straight from the DB and calls `compute_estimate` for each
candidate. Idempotent and re-runnable.

Usage:
    # Local dev (against docker compose Postgres)
    poetry run python scripts/backfill_revenue_estimates.py --dry-run
    poetry run python scripts/backfill_revenue_estimates.py

    # Staging / production — open an SSH tunnel first, then point
    # DATABASE_URL at the tunnelled Postgres:
    bash scripts/dev/db-tunnel.sh   # in another terminal
    DATABASE_URL=postgresql://... poetry run python scripts/backfill_revenue_estimates.py --dry-run

Flags:
    --dry-run         Compute estimates but do not write anything to the DB.
    --all             Recompute every game. Default is --only-stale: skip
                      games whose `revenue_estimate_method` already matches
                      the current METHOD_VERSION.
    --start-after N   Resume after appid N (skip all appids <= N).
    --batch N         Number of appids per bulk genre/tag lookup (default 500).
    --limit N         Stop after processing N candidates (debugging aid).

After a successful run, refresh the affected matviews so the API and list
surfaces pick up the new values:

    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_genre_games;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_tag_games;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_price_positioning;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_discovery_feeds;
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Iterator
from decimal import Decimal

import psycopg2
import psycopg2.extras
from library_layer.models.game import Game
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.revenue_estimator import METHOD_VERSION, compute_estimate
from library_layer.utils.db import get_conn


def _iter_candidate_appids(
    *,
    only_stale: bool,
    batch_size: int,
    start_after: int | None,
) -> Iterator[list[int]]:
    """Stream candidate appids from a named server-side cursor.

    Avoids loading the full games table into memory on large production DBs
    — psycopg2 only buffers `itersize` rows at a time.

    Important: this opens a **dedicated** connection (not the cached
    `get_conn()` handle used by the repositories). A named server-side
    cursor lives inside a transaction and is destroyed by any COMMIT on
    its connection — and the repository bulk update commits per batch. If
    we shared one connection we'd lose the cursor after the first write.
    """
    clauses: list[str] = []
    params_list: list[int | str] = []

    if only_stale:
        clauses.append("revenue_estimate_method IS DISTINCT FROM %s")
        params_list.append(METHOD_VERSION)

    if start_after is not None:
        clauses.append("appid > %s")
        params_list.append(start_after)

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT appid FROM games{where} ORDER BY appid"
    params: tuple[int | str, ...] = tuple(params_list)

    db_url = os.environ["DATABASE_URL"]
    reader_conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with reader_conn.cursor(name="backfill_revenue_estimates_appids") as cur:
            cur.itersize = batch_size
            cur.execute(sql, params)
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                yield [int(r["appid"]) for r in rows]
    finally:
        reader_conn.close()


def _fetch_games_bulk(game_repo: GameRepository, appids: list[int]) -> dict[int, Game]:
    """Bulk SELECT only the columns `compute_estimate` needs."""
    rows = game_repo._fetchall(
        """
        SELECT appid, name, slug, type, price_usd, is_free, review_count, release_date, positive_pct
        FROM games
        WHERE appid = ANY(%s)
        """,
        (appids,),
    )
    return {int(r["appid"]): Game.model_validate(dict(r)) for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Boxleiter v2 revenue estimates.")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write.")
    parser.add_argument(
        "--all",
        dest="only_stale",
        action="store_false",
        default=True,
        help="Recompute every game. Default is stale-only (games missing estimates or with outdated data).",
    )
    parser.add_argument(
        "--start-after", type=int, default=None, help="Resume after this appid (skip appids <= N)."
    )
    parser.add_argument("--batch", type=int, default=500, help="Batch size (default 500).")
    parser.add_argument("--limit", type=int, default=None, help="Stop after N candidates.")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    game_repo = GameRepository(get_conn)
    tag_repo = TagRepository(get_conn)

    total = 0
    updated = 0
    reasons: Counter[str] = Counter()

    last_appid = args.start_after or 0

    if args.start_after is not None:
        print(f"Resuming after appid {args.start_after}", flush=True)

    for appids in _iter_candidate_appids(
        only_stale=args.only_stale, batch_size=args.batch, start_after=args.start_after
    ):
        if args.limit is not None and total >= args.limit:
            break
        if args.limit is not None:
            appids = appids[: max(0, args.limit - total)]
            if not appids:
                break

        games_by_appid = _fetch_games_bulk(game_repo, appids)
        genres_by_appid = tag_repo.find_genres_for_appids(appids)
        tags_by_appid = tag_repo.find_tags_for_appids(appids)

        batch_updates: list[tuple[int, int | None, Decimal | None, str | None, str | None]] = []
        for appid in appids:
            game = games_by_appid.get(appid)
            if game is None:
                continue
            total += 1
            estimate = compute_estimate(
                game,
                genres_by_appid.get(appid, []),
                tags_by_appid.get(appid, []),
            )
            if estimate.reason is not None:
                reasons[estimate.reason] += 1
            else:
                reasons["_computed"] += 1
            batch_updates.append(
                (
                    appid,
                    estimate.estimated_owners,
                    estimate.estimated_revenue_usd,
                    estimate.method,
                    estimate.reason,
                )
            )

        if not args.dry_run and batch_updates:
            # One bulk UPDATE + one commit per batch instead of per row.
            try:
                game_repo.bulk_update_revenue_estimates(batch_updates)
                updated += len(batch_updates)
            except psycopg2.errors.NumericValueOutOfRange:
                # Fall back to per-row so one bogus estimate doesn't kill the batch.
                game_repo.conn.rollback()
                print(
                    "  WARN: numeric overflow in batch — retrying row-by-row",
                    flush=True,
                )
                for row in batch_updates:
                    try:
                        game_repo.bulk_update_revenue_estimates([row])
                        updated += 1
                    except psycopg2.errors.NumericValueOutOfRange:
                        game_repo.conn.rollback()
                        reasons["_overflow_skipped"] += 1
                        print(
                            f"  WARN: skipping appid={row[0]} — revenue estimate "
                            f"{row[2]} overflows column, likely bogus data",
                            flush=True,
                        )

        last_appid = appids[-1] if appids else last_appid
        print(
            f"  processed batch of {len(appids)} "
            f"(running total: {total}, updated: {updated}, last appid: {last_appid})",
            flush=True,
        )

    print()
    print(f"Candidates processed: {total}")
    if args.dry_run:
        print("DRY RUN — no rows written")
    else:
        print(f"Rows updated:         {updated}")
    print("Outcome breakdown:")
    for reason, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
        label = "with estimate" if reason == "_computed" else f"skipped: {reason}"
        print(f"  {label:35s} {count}")

    if not args.dry_run:
        print()
        print("Reminder: refresh matviews so API responses pick up the new values:")
        print("  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_genre_games;")
        print("  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_tag_games;")
        print("  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_price_positioning;")
        print("  REFRESH MATERIALIZED VIEW CONCURRENTLY mv_discovery_feeds;")


if __name__ == "__main__":
    main()
