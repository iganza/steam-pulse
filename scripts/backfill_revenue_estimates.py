"""Backfill Boxleiter v1 revenue estimates for existing games.

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
    --batch N         Number of appids per bulk genre/tag lookup (default 500).
    --limit N         Stop after processing N candidates (debugging aid).

After a successful run, refresh the affected matviews so the API and list
surfaces pick up the new values:

    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_genre_games;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_tag_games;
    REFRESH MATERIALIZED VIEW CONCURRENTLY mv_price_positioning;
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from collections.abc import Iterator

from library_layer.models.game import Game
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.revenue_estimator import METHOD_VERSION, compute_estimate
from library_layer.utils.db import get_conn


def _iter_candidate_appids(
    game_repo: GameRepository,
    *,
    only_stale: bool,
    batch_size: int,
) -> Iterator[list[int]]:
    """Yield lists of candidate appids in chunks of `batch_size`."""
    if only_stale:
        sql = (
            "SELECT appid FROM games "
            "WHERE revenue_estimate_method IS DISTINCT FROM %s "
            "ORDER BY appid"
        )
        params: tuple = (METHOD_VERSION,)
    else:
        sql = "SELECT appid FROM games ORDER BY appid"
        params = ()

    rows = game_repo._fetchall(sql, params)
    chunk: list[int] = []
    for r in rows:
        chunk.append(int(r["appid"]))
        if len(chunk) >= batch_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _fetch_games_bulk(game_repo: GameRepository, appids: list[int]) -> dict[int, Game]:
    """Bulk SELECT only the columns `compute_estimate` needs."""
    rows = game_repo._fetchall(
        """
        SELECT appid, name, slug, type, price_usd, is_free, review_count, release_date
        FROM games
        WHERE appid = ANY(%s)
        """,
        (appids,),
    )
    return {int(r["appid"]): Game.model_validate(dict(r)) for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Boxleiter v1 revenue estimates.")
    parser.add_argument("--dry-run", action="store_true", help="Compute but do not write.")
    parser.add_argument(
        "--all",
        dest="only_stale",
        action="store_false",
        default=True,
        help="Recompute every game. Default: --only-stale.",
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

    for appids in _iter_candidate_appids(
        game_repo, only_stale=args.only_stale, batch_size=args.batch
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

            if args.dry_run:
                continue

            game_repo.update_revenue_estimate(
                appid=appid,
                owners=estimate.estimated_owners,
                revenue_usd=estimate.estimated_revenue_usd,
                method=estimate.method,
            )
            updated += 1

        print(
            f"  processed batch of {len(appids)} "
            f"(running total: {total}, updated: {updated})",
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


if __name__ == "__main__":
    main()
