#!/usr/bin/env python3
"""Copy a handful of games (with tags, genres, categories, reviews) from
the production DB into the local Docker Postgres so the three-phase
analyzer can be exercised against real data before merge/deploy.

Assumes you have an SSM tunnel open to production in another terminal:

    bash scripts/dev/db-tunnel.sh --stage prod     # localhost:5433 → prod RDS

and your local Postgres running via `./scripts/dev/start-local.sh`
(localhost:5432).

The prod connection is passwordless here — libpq reads the password
from `~/.pgpass` (a line like `localhost:5433:production_steampulse:postgres:<pw>`).
Override with `--prod-url` if your setup differs. The script never
writes to prod.

Usage:
    # Import the 5 most recently discovered games that already have
    # metadata crawled AND at least 50 reviews crawled.
    poetry run python scripts/dev/import_from_prod.py --limit 5

    # Import a specific set of appids.
    poetry run python scripts/dev/import_from_prod.py --appids 440 730 570

    # Cap reviews per game (default 500 — enough to exercise chunking).
    poetry run python scripts/dev/import_from_prod.py --limit 3 --reviews-per-game 2000

    # Override connection strings.
    poetry run python scripts/dev/import_from_prod.py \\
        --prod-url "postgresql://postgres@localhost:5433/production_steampulse?sslmode=require" \\
        --local-url "postgresql://steampulse:dev@localhost:5432/steampulse" \\
        --limit 5

The script is idempotent: existing rows are UPSERTed (`ON CONFLICT DO
UPDATE` for games / reviews, `DO NOTHING` for junction tables keyed on
composite PKs). Re-running it just refreshes the copied rows.
"""

import argparse
import getpass
import os
from typing import Any

import psycopg2
import psycopg2.extras

_LOCAL_DEFAULT = "postgresql://steampulse:dev@localhost:5432/steampulse"
# Passwordless — libpq reads the password from ~/.pgpass. Uses keyword
# DSN form so we can point at the RDS CA bundle: `sslmode=require` alone
# fails RDS's cert chain and libpq falls through to cleartext auth
# ("no password supplied"). `verify-ca` with the bundled cert matches
# the working psql invocation in CLAUDE.md.
_PROD_DEFAULT = (
    "host=localhost port=5433 dbname=production_steampulse user=postgres "
    "sslmode=verify-ca sslrootcert=./global-bundle.pem"
)

# Columns we copy from each table. Explicit lists keep the script stable
# against cosmetic schema additions — any new prod column will be missed
# loudly (the SELECT still works; INSERT excludes it) rather than silently
# breaking an `INSERT ... SELECT *` shape mismatch.
_GAME_COLUMNS = (
    "appid",
    "name",
    "slug",
    "type",
    "developer",
    "developer_slug",
    "publisher",
    "publisher_slug",
    "developers",
    "publishers",
    "website",
    "release_date",
    "coming_soon",
    "price_usd",
    "is_free",
    "short_desc",
    "detailed_description",
    "about_the_game",
    "review_count",
    "review_count_english",
    "total_positive",
    "total_negative",
    "positive_pct",
    "review_score_desc",
    "header_image",
    "background_image",
    "required_age",
    "platforms",
    "supported_languages",
    "achievements_total",
    "metacritic_score",
    "deck_compatibility",
    "deck_test_results",
    "crawled_at",
)

_REVIEW_COLUMNS = (
    "appid",
    "steam_review_id",
    "author_steamid",
    "voted_up",
    "playtime_hours",
    "body",
    "posted_at",
    "language",
    "votes_helpful",
    "votes_funny",
    "written_during_early_access",
    "received_for_free",
    "crawled_at",
)

_TAG_COLUMNS = ("id", "name", "slug", "steam_tag_id", "category")
_GENRE_COLUMNS = ("id", "name", "slug")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--prod-url",
        default=_PROD_DEFAULT,
        help=(
            "Postgres URL for the prod-tunneled DB. Default: "
            f"{_PROD_DEFAULT} (passwordless — libpq reads ~/.pgpass)."
        ),
    )
    p.add_argument("--local-url", default=_LOCAL_DEFAULT, help="Local Postgres URL")
    p.add_argument(
        "--appids",
        type=int,
        nargs="+",
        help="Specific appids to copy. Mutually exclusive with --limit.",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Copy N most-recently-crawled games that have reviews. "
            "Ignored if --appids is set."
        ),
    )
    p.add_argument(
        "--reviews-per-game",
        type=int,
        default=500,
        help="Cap reviews copied per appid (helpfulness DESC). Default 500.",
    )
    p.add_argument(
        "--min-reviews",
        type=int,
        default=50,
        help="When using --limit, only pick games with at least this many reviews. Default 50.",
    )
    args = p.parse_args()
    if not args.appids and args.limit is None:
        p.error("pass either --appids or --limit")
    return args


def _pick_appids(prod: Any, limit: int, min_reviews: int) -> list[int]:
    with prod.cursor() as cur:
        cur.execute(
            """
            SELECT g.appid
            FROM games g
            WHERE g.review_count >= %s
              AND EXISTS (SELECT 1 FROM reviews r WHERE r.appid = g.appid)
            ORDER BY g.crawled_at DESC NULLS LAST
            LIMIT %s
            """,
            (min_reviews, limit),
        )
        return [row[0] for row in cur.fetchall()]


def _cols(columns: tuple[str, ...]) -> str:
    return ", ".join(columns)


def _placeholders(columns: tuple[str, ...]) -> str:
    return ", ".join(["%s"] * len(columns))


def _copy_games(prod: Any, local: Any, appids: list[int]) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_GAME_COLUMNS)} FROM games WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _GAME_COLUMNS if c != "appid"
    )
    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO games ({_cols(_GAME_COLUMNS)})
                VALUES ({_placeholders(_GAME_COLUMNS)})
                ON CONFLICT (appid) DO UPDATE SET {updates}
                """,
                tuple(
                    psycopg2.extras.Json(row[c])
                    if c in {"developers", "publishers", "platforms", "deck_test_results"}
                    and row[c] is not None
                    else row[c]
                    for c in _GAME_COLUMNS
                ),
            )
    local.commit()
    print(f"  ✓ games: {len(rows)} row(s) upserted")


def _copy_tag_dictionary(prod: Any, local: Any, appids: list[int]) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT DISTINCT {_cols(_TAG_COLUMNS)}
            FROM tags t
            WHERE t.id IN (SELECT tag_id FROM game_tags WHERE appid = ANY(%s))
            """,
            (appids,),
        )
        tag_rows = cur.fetchall()
        cur.execute(
            f"""
            SELECT DISTINCT {_cols(_GENRE_COLUMNS)}
            FROM genres g
            WHERE g.id IN (SELECT genre_id FROM game_genres WHERE appid = ANY(%s))
            """,
            (appids,),
        )
        genre_rows = cur.fetchall()

    with local.cursor() as cur:
        for row in tag_rows:
            cur.execute(
                f"""
                INSERT INTO tags ({_cols(_TAG_COLUMNS)})
                VALUES ({_placeholders(_TAG_COLUMNS)})
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  slug = EXCLUDED.slug,
                  steam_tag_id = EXCLUDED.steam_tag_id,
                  category = EXCLUDED.category
                """,
                tuple(row[c] for c in _TAG_COLUMNS),
            )
        for row in genre_rows:
            cur.execute(
                f"""
                INSERT INTO genres ({_cols(_GENRE_COLUMNS)})
                VALUES ({_placeholders(_GENRE_COLUMNS)})
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  slug = EXCLUDED.slug
                """,
                tuple(row[c] for c in _GENRE_COLUMNS),
            )
    local.commit()
    print(f"  ✓ tags dictionary: {len(tag_rows)} tag(s), {len(genre_rows)} genre(s)")


def _copy_associations(prod: Any, local: Any, appids: list[int]) -> None:
    with prod.cursor() as cur:
        cur.execute(
            "SELECT appid, tag_id, votes FROM game_tags WHERE appid = ANY(%s)",
            (appids,),
        )
        game_tags = cur.fetchall()
        cur.execute(
            "SELECT appid, genre_id FROM game_genres WHERE appid = ANY(%s)",
            (appids,),
        )
        game_genres = cur.fetchall()
        cur.execute(
            """
            SELECT appid, category_id, category_name
            FROM game_categories WHERE appid = ANY(%s)
            """,
            (appids,),
        )
        game_categories = cur.fetchall()

    with local.cursor() as cur:
        # Replace associations wholesale so stale rows don't leak (matches
        # the project's delete-and-replace invariant for game_* junction
        # tables — see CLAUDE.md).
        cur.execute("DELETE FROM game_tags WHERE appid = ANY(%s)", (appids,))
        cur.execute("DELETE FROM game_genres WHERE appid = ANY(%s)", (appids,))
        cur.execute("DELETE FROM game_categories WHERE appid = ANY(%s)", (appids,))
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO game_tags (appid, tag_id, votes) VALUES %s",
            game_tags,
        )
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO game_genres (appid, genre_id) VALUES %s",
            game_genres,
        )
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO game_categories (appid, category_id, category_name) VALUES %s",
            game_categories,
        )
    local.commit()
    print(
        f"  ✓ associations: {len(game_tags)} game_tags, "
        f"{len(game_genres)} game_genres, {len(game_categories)} game_categories"
    )


def _copy_reviews(prod: Any, local: Any, appid: int, per_game: int) -> int:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT {_cols(_REVIEW_COLUMNS)}
            FROM reviews
            WHERE appid = %s AND body IS NOT NULL AND body <> ''
            ORDER BY votes_helpful DESC NULLS LAST, posted_at DESC
            LIMIT %s
            """,
            (appid, per_game),
        )
        rows = cur.fetchall()
    if not rows:
        return 0
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _REVIEW_COLUMNS if c != "steam_review_id"
    )
    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO reviews ({_cols(_REVIEW_COLUMNS)})
                VALUES ({_placeholders(_REVIEW_COLUMNS)})
                ON CONFLICT (steam_review_id) DO UPDATE SET {updates}
                """,
                tuple(row[c] for c in _REVIEW_COLUMNS),
            )
    local.commit()
    return len(rows)


def main() -> None:
    args = _parse_args()

    # Password resolution order:
    #   1. Explicit `password=` already in --prod-url (libpq handles it)
    #   2. PGPASSWORD env var (libpq handles it)
    #   3. ~/.pgpass match (libpq handles it)
    #   4. Interactive prompt — covers the common case where the user's
    #      psql session has the password cached but .pgpass doesn't
    #      match libpq's literal host/port/db/user tuple.
    print("▶ Connecting to prod (read-only intent) + local...")
    prod_dsn = args.prod_url
    if (
        "password=" not in prod_dsn
        and not os.environ.get("PGPASSWORD")
        and "password=" not in args.local_url  # harmless check, keeps branches aligned
    ):
        try:
            prod = psycopg2.connect(prod_dsn)
        except psycopg2.OperationalError as e:
            if "no password supplied" not in str(e):
                raise
            pw = getpass.getpass("Prod postgres password: ")
            prod = psycopg2.connect(prod_dsn + f" password={pw}")
    else:
        prod = psycopg2.connect(prod_dsn)
    prod.set_session(readonly=True)
    local = psycopg2.connect(args.local_url)

    try:
        if args.appids:
            appids = args.appids
            print(f"  Using explicit appids: {appids}")
        else:
            appids = _pick_appids(prod, args.limit, args.min_reviews)
            print(f"  Picked {len(appids)} appid(s) from prod: {appids}")
        if not appids:
            print("No appids to copy — exiting.")
            return

        print("\n▶ Copying games...")
        _copy_games(prod, local, appids)

        print("\n▶ Copying tag / genre dictionaries...")
        _copy_tag_dictionary(prod, local, appids)

        print("\n▶ Copying game_tags / game_genres / game_categories...")
        _copy_associations(prod, local, appids)

        print(f"\n▶ Copying up to {args.reviews_per_game} reviews per game...")
        total = 0
        for appid in appids:
            n = _copy_reviews(prod, local, appid, args.reviews_per_game)
            print(f"  ✓ appid={appid}: {n} review(s)")
            total += n
        print(f"\n✔ Done. {len(appids)} game(s), {total} review(s) imported.")
    finally:
        prod.close()
        local.close()


if __name__ == "__main__":
    main()
