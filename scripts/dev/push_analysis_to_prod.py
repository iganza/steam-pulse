#!/usr/bin/env python3
"""Push local LLM analysis tables to production.

Copies chunk_summaries, merged_summaries, reports, and analysis_jobs
from the local Docker Postgres into the production RDS (via SSH tunnel).

This is the reverse of scripts/dev/import_from_prod.py — it pushes
analysis artifacts upward rather than pulling game/review data down.

Assumes you have an SSM tunnel open to production in another terminal:

    bash scripts/dev/db-tunnel.sh --stage prod     # localhost:5433 → prod RDS

and your local Postgres running via `./scripts/dev/start-local.sh`
(localhost:5432).

The prod connection is passwordless here — libpq reads the password
from `~/.pgpass` (a line like `localhost:5433:production_steampulse:postgres:<pw>`).
Override with `--prod-url` if your setup differs.

Usage:
    # Push all analysis data for all appids found locally.
    poetry run python scripts/dev/push_analysis_to_prod.py

    # Push only specific appids.
    poetry run python scripts/dev/push_analysis_to_prod.py --appids 440 730 570

    # Dry run — show what would be pushed without writing anything.
    poetry run python scripts/dev/push_analysis_to_prod.py --dry-run
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
        help="Specific appids to push. Defaults to all appids in local reports table.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be pushed without writing to prod.",
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


def _push_chunk_summaries(
    local: psycopg2.extensions.connection,
    prod: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with local.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_CHUNK_COLUMNS)} FROM chunk_summaries WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] chunk_summaries: {len(rows)} row(s) would be upserted")
        return

    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _CHUNK_COLUMNS if c != "id"
    )
    json_cols = {"summary_json"}
    with prod.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO chunk_summaries ({_cols(_CHUNK_COLUMNS)})
                VALUES ({_placeholders(_CHUNK_COLUMNS)})
                ON CONFLICT (appid, chunk_hash, prompt_version) DO UPDATE SET {updates}
                """,
                _row_values(row, _CHUNK_COLUMNS, json_cols),
            )
    prod.commit()
    print(f"  ✓ chunk_summaries: {len(rows)} row(s) upserted")


def _push_merged_summaries(
    local: psycopg2.extensions.connection,
    prod: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with local.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_MERGED_COLUMNS)} FROM merged_summaries WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] merged_summaries: {len(rows)} row(s) would be upserted")
        return

    json_cols = {"summary_json"}
    with prod.cursor() as cur:
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
                _row_values(row, _MERGED_COLUMNS, json_cols),
            )
    prod.commit()
    print(f"  ✓ merged_summaries: {len(rows)} row(s) upserted")


def _push_reports(
    local: psycopg2.extensions.connection,
    prod: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with local.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_REPORT_COLUMNS)} FROM reports WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] reports: {len(rows)} row(s) would be upserted")
        return

    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _REPORT_COLUMNS if c != "appid"
    )
    json_cols = {"report_json"}
    with prod.cursor() as cur:
        for row in rows:
            cur.execute(
                f"""
                INSERT INTO reports ({_cols(_REPORT_COLUMNS)})
                VALUES ({_placeholders(_REPORT_COLUMNS)})
                ON CONFLICT (appid) DO UPDATE SET {updates}
                """,
                _row_values(row, _REPORT_COLUMNS, json_cols),
            )
    prod.commit()
    print(f"  ✓ reports: {len(rows)} row(s) upserted")


def _push_analysis_jobs(
    local: psycopg2.extensions.connection,
    prod: psycopg2.extensions.connection,
    appids: list[int],
    dry_run: bool,
) -> None:
    with local.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"SELECT {_cols(_JOB_COLUMNS)} FROM analysis_jobs WHERE appid = ANY(%s)",
            (appids,),
        )
        rows = cur.fetchall()

    if dry_run:
        print(f"  [dry-run] analysis_jobs: {len(rows)} row(s) would be upserted")
        return

    with prod.cursor() as cur:
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
    prod.commit()
    print(f"  ✓ analysis_jobs: {len(rows)} row(s) upserted")


def main() -> None:
    args = _parse_args()

    print("▶ Connecting to local + prod (write intent)...")
    local = psycopg2.connect(args.local_url)

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

    try:
        if args.appids:
            appids = args.appids
            print(f"  Using explicit appids: {appids}")
        else:
            with local.cursor() as cur:
                cur.execute("SELECT appid FROM reports ORDER BY appid")
                appids = [row[0] for row in cur.fetchall()]
            print(f"  Found {len(appids)} appid(s) in local reports table")

        if not appids:
            print("No reports found locally — exiting.")
            return

        if args.dry_run:
            print("\n▶ DRY RUN — nothing will be written to prod\n")

        print("\n▶ Pushing chunk_summaries...")
        _push_chunk_summaries(local, prod, appids, args.dry_run)

        print("\n▶ Pushing merged_summaries...")
        _push_merged_summaries(local, prod, appids, args.dry_run)

        print("\n▶ Pushing reports...")
        _push_reports(local, prod, appids, args.dry_run)

        print("\n▶ Pushing analysis_jobs...")
        _push_analysis_jobs(local, prod, appids, args.dry_run)

        if not args.dry_run:
            print(f"\n✔ Done. {len(appids)} game(s) pushed to prod.")
        else:
            print(f"\n✔ Dry run complete. {len(appids)} game(s) would be pushed.")
    finally:
        local.close()
        prod.close()


if __name__ == "__main__":
    main()
