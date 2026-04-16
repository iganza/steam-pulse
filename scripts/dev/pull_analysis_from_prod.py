#!/usr/bin/env python3
"""Pull LLM analysis tables from production into local Docker Postgres.

The reverse of scripts/dev/push_analysis_to_prod.py — it pulls reports,
chunk_summaries, merged_summaries, and analysis_jobs from the production
RDS (via SSH tunnel) into your local DB so you can view analyzed games
without re-running the LLM pipeline.

Also pulls the game row itself (+ tags/genres/categories) so the report
page has metadata to render against. Skips reviews — they're large and
not needed for viewing reports.

Assumes you have an SSM tunnel open to production in another terminal:

    bash scripts/dev/db-tunnel.sh --stage prod     # localhost:5433 → prod RDS

and your local Postgres running via `./scripts/dev/start-local.sh`
(localhost:5432).

The prod connection is passwordless — libpq reads the password from
`~/.pgpass` (a line like `localhost:5433:production_steampulse:postgres:<pw>`).
Override with `--prod-url` if your setup differs. The script never
writes to prod.

Usage:
    # Pull ALL games that have a report in prod.
    poetry run python scripts/dev/pull_analysis_from_prod.py

    # Pull specific appids only.
    poetry run python scripts/dev/pull_analysis_from_prod.py --appids 1086940 440

    # Dry run — show what would be pulled without writing locally.
    poetry run python scripts/dev/pull_analysis_from_prod.py --dry-run
"""

import argparse
import getpass
import os

import psycopg2
import psycopg2.extras

_LOCAL_DEFAULT = "postgresql://steampulse:dev@localhost:5432/steampulse"
_PROD_DEFAULT = (
    "host=localhost port=5433 dbname=production_steampulse user=postgres "
    "sslmode=verify-ca sslrootcert=./global-bundle.pem"
)

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

_GAME_JSON_COLS = {"developers", "publishers", "platforms", "deck_test_results"}

_TAG_COLUMNS = ("id", "name", "slug", "steam_tag_id", "category")
_GENRE_COLUMNS = ("id", "name", "slug")

_REPORT_COLUMNS = (
    "appid",
    "report_json",
    "reviews_analyzed",
    "analysis_version",
    "is_public",
    "seo_title",
    "seo_description",
    "featured_at",
    "last_analyzed",
    "created_at",
    "pipeline_version",
    "chunk_count",
    "merged_summary_id",
)

_CHUNK_COLUMNS = (
    "id",
    "appid",
    "chunk_index",
    "chunk_hash",
    "review_count",
    "summary_json",
    "model_id",
    "prompt_version",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "created_at",
)

_MERGED_COLUMNS = (
    "id",
    "appid",
    "merge_level",
    "summary_json",
    "source_chunk_ids",
    "chunks_merged",
    "model_id",
    "prompt_version",
    "input_tokens",
    "output_tokens",
    "latency_ms",
    "created_at",
)

_JOB_COLUMNS = (
    "job_id",
    "status",
    "appid",
    "created_at",
    "updated_at",
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--local-url", default=_LOCAL_DEFAULT, help="Local Postgres URL")
    p.add_argument(
        "--prod-url",
        default=_PROD_DEFAULT,
        help=f"Postgres URL for the prod-tunneled DB. Default: {_PROD_DEFAULT}",
    )
    p.add_argument(
        "--appids",
        type=int,
        nargs="+",
        help="Specific appids to pull. Without this, pulls all games that have a report.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be pulled without writing locally.",
    )
    return p.parse_args()


def _cols(columns: tuple[str, ...]) -> str:
    return ", ".join(columns)


def _placeholders(columns: tuple[str, ...]) -> str:
    return ", ".join(["%s"] * len(columns))


def _row_values(row: dict, columns: tuple[str, ...], json_cols: set[str]) -> tuple:
    return tuple(
        psycopg2.extras.Json(row[c]) if c in json_cols and row[c] is not None else row[c]
        for c in columns
    )


def _pick_appids(prod: psycopg2.extensions.connection) -> list[int]:
    with prod.cursor() as cur:
        cur.execute("SELECT appid FROM reports ORDER BY last_analyzed DESC NULLS LAST")
        return [row[0] for row in cur.fetchall()]


def _pull_games(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_GAME_COLUMNS)} FROM games WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] games: {len(rows)} row(s) would be upserted")
        return

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _GAME_COLUMNS if c != "appid")
    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO games ({_cols(_GAME_COLUMNS)})
                VALUES ({_placeholders(_GAME_COLUMNS)})
                ON CONFLICT (appid) DO UPDATE SET {updates}
                """,
                _row_values(row, _GAME_COLUMNS, _GAME_JSON_COLS),
            )
    local.commit()
    print(f"  ✓ games: {len(rows)} row(s) upserted")


def _pull_tag_dictionary(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
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

    if dry_run:
        print(f"  [dry-run] tags: {len(tag_rows)}, genres: {len(genre_rows)}")
        return

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
    print(f"  ✓ tags: {len(tag_rows)}, genres: {len(genre_rows)}")


def _pull_associations(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
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
            "SELECT appid, category_id, category_name FROM game_categories WHERE appid = ANY(%s)",
            (appids,),
        )
        game_categories = cur.fetchall()

    if dry_run:
        print(
            f"  [dry-run] game_tags: {len(game_tags)}, "
            f"game_genres: {len(game_genres)}, game_categories: {len(game_categories)}"
        )
        return

    with local.cursor() as cur:
        cur.execute("DELETE FROM game_tags WHERE appid = ANY(%s)", (appids,))
        cur.execute("DELETE FROM game_genres WHERE appid = ANY(%s)", (appids,))
        cur.execute("DELETE FROM game_categories WHERE appid = ANY(%s)", (appids,))
        if game_tags:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO game_tags (appid, tag_id, votes) VALUES %s", game_tags,
            )
        if game_genres:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO game_genres (appid, genre_id) VALUES %s", game_genres,
            )
        if game_categories:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO game_categories (appid, category_id, category_name) VALUES %s",
                game_categories,
            )
    local.commit()
    print(
        f"  ✓ game_tags: {len(game_tags)}, "
        f"game_genres: {len(game_genres)}, game_categories: {len(game_categories)}"
    )


def _pull_reports(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_REPORT_COLUMNS)} FROM reports WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] reports: {len(rows)} row(s) would be upserted")
        return

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _REPORT_COLUMNS if c != "appid")
    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO reports ({_cols(_REPORT_COLUMNS)})
                VALUES ({_placeholders(_REPORT_COLUMNS)})
                ON CONFLICT (appid) DO UPDATE SET {updates}
                """,
                _row_values(row, _REPORT_COLUMNS, {"report_json"}),
            )
    local.commit()
    print(f"  ✓ reports: {len(rows)} row(s) upserted")


def _pull_chunk_summaries(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_CHUNK_COLUMNS)} FROM chunk_summaries WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] chunk_summaries: {len(rows)} row(s) would be upserted")
        return

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _CHUNK_COLUMNS if c != "id")
    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO chunk_summaries ({_cols(_CHUNK_COLUMNS)})
                VALUES ({_placeholders(_CHUNK_COLUMNS)})
                ON CONFLICT (appid, chunk_hash, prompt_version) DO UPDATE SET {updates}
                """,
                _row_values(row, _CHUNK_COLUMNS, {"summary_json"}),
            )
    local.commit()
    print(f"  ✓ chunk_summaries: {len(rows)} row(s) upserted")


def _pull_merged_summaries(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_MERGED_COLUMNS)} FROM merged_summaries WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] merged_summaries: {len(rows)} row(s) would be upserted")
        return

    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO merged_summaries ({_cols(_MERGED_COLUMNS)})
                VALUES ({_placeholders(_MERGED_COLUMNS)})
                ON CONFLICT (id) DO UPDATE SET
                    summary_json = EXCLUDED.summary_json,
                    input_tokens = EXCLUDED.input_tokens,
                    output_tokens = EXCLUDED.output_tokens,
                    latency_ms = EXCLUDED.latency_ms
                """,
                _row_values(row, _MERGED_COLUMNS, {"summary_json"}),
            )
    local.commit()
    print(f"  ✓ merged_summaries: {len(rows)} row(s) upserted")


def _pull_analysis_jobs(
    prod: psycopg2.extensions.connection,
    local: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_JOB_COLUMNS)} FROM analysis_jobs WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] analysis_jobs: {len(rows)} row(s) would be upserted")
        return

    with local.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO analysis_jobs ({_cols(_JOB_COLUMNS)})
                VALUES ({_placeholders(_JOB_COLUMNS)})
                ON CONFLICT (job_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at
                """,
                _row_values(row, _JOB_COLUMNS, set()),
            )
    local.commit()
    print(f"  ✓ analysis_jobs: {len(rows)} row(s) upserted")


def main() -> None:
    args = _parse_args()

    print("▶ Connecting to prod (read-only) + local...")
    prod_dsn = args.prod_url
    if "password=" not in prod_dsn and not os.environ.get("PGPASSWORD"):
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
            appids = _pick_appids(prod)
            print(f"  Found {len(appids)} game(s) with reports in prod")

        if not appids:
            print("No reports found in prod — exiting.")
            return

        if args.dry_run:
            print("\n▶ DRY RUN — nothing will be written locally\n")

        print("\n▶ Pulling games...")
        _pull_games(prod, local, appids, args.dry_run)

        print("\n▶ Pulling tag / genre dictionaries...")
        _pull_tag_dictionary(prod, local, appids, args.dry_run)

        print("\n▶ Pulling associations...")
        _pull_associations(prod, local, appids, args.dry_run)

        print("\n▶ Pulling reports...")
        _pull_reports(prod, local, appids, args.dry_run)

        print("\n▶ Pulling chunk_summaries...")
        _pull_chunk_summaries(prod, local, appids, args.dry_run)

        print("\n▶ Pulling merged_summaries...")
        _pull_merged_summaries(prod, local, appids, args.dry_run)

        print("\n▶ Pulling analysis_jobs...")
        _pull_analysis_jobs(prod, local, appids, args.dry_run)

        if not args.dry_run:
            print(f"\n✔ Done. {len(appids)} game(s) pulled from prod.")
        else:
            print(f"\n✔ Dry run complete. {len(appids)} game(s) would be pulled.")
    finally:
        prod.close()
        local.close()


if __name__ == "__main__":
    main()
