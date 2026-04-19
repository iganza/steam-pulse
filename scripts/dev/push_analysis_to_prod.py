#!/usr/bin/env python3
"""DISABLED as of 2026-04-18 — do not push analysis artifacts to prod.

Prod is now the source of truth for chunk_summaries, merged_summaries, and
reports. This script used to copy those tables from local → prod with the
`id` column preserved, which silently desynced `chunk_summaries_id_seq` and
`merged_summaries_id_seq` against their tables (rows landed with explicit
ids that the sequence never advanced past). The next real pipeline run
would then hit PK collisions on nextval(), failing with `UniqueViolation:
chunk_summaries_pkey`. Slay the Spire (appid 646570) was the first to trip
it during the roguelike-deckbuilder wedge run.

If you need analysis artifacts locally, pull them FROM prod with
`scripts/dev/pull_analysis_from_prod.py`, do not push upward.
"""

import sys


_DISABLED_REASONS = """\
push_analysis_to_prod is disabled. Do not push to prod.

Why:
  1. Prod is the source of truth for analysis artifacts
     (chunk_summaries, merged_summaries, reports) as of 2026-04-18.
  2. This script copied those tables with explicit `id` values, which
     does NOT advance the table's sequence. Prod ended up with
     max(id) > last_value on chunk_summaries_id_seq and
     merged_summaries_id_seq.
  3. Every subsequent real pipeline run then hit PK collisions on
     nextval() — failing with `UniqueViolation: chunk_summaries_pkey`
     and burning batch budget before producing any report.
  4. The setval fix is a symptom patch; this script is the root cause.

If you need prod analysis locally, use
`scripts/dev/pull_analysis_from_prod.py` instead.
"""


def main() -> None:
    sys.stderr.write(_DISABLED_REASONS)
    sys.exit(1)


if __name__ == "__main__":
    main()


# ── Legacy implementation retained below for reference only ──────────────────
# The original push logic is preserved here in case a future migration needs
# to reference the column lists or SQL shape. Nothing below runs — main()
# above exits before import-time side effects matter.


import argparse  # noqa: E402
import getpass  # noqa: E402
import os  # noqa: E402

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

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


def _legacy_main() -> None:
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
