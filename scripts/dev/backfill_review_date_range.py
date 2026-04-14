#!/usr/bin/env python3
"""Backfill review_date_range_start/end into existing report_json.

The date range already lives in merged_summaries.summary_json→total_stats
but was never copied to the final GameReport. This script patches all
existing reports in a single UPDATE — no LLM calls, no re-analysis.

Prereqs:
  - Local Postgres: `./scripts/dev/start-local.sh`
  - For staging/prod: open a DB tunnel first (`scripts/dev/db-tunnel.sh`)

Usage:
    # Dry-run (default) — show how many reports would be patched.
    poetry run python scripts/dev/backfill_review_date_range.py

    # Apply the backfill.
    poetry run python scripts/dev/backfill_review_date_range.py --apply
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
sys.path.insert(0, str(_REPO_ROOT / "src" / "library-layer"))

from library_layer.utils.db import get_conn  # noqa: E402

_BACKFILL_SQL = """
UPDATE reports r
SET report_json = r.report_json
    || jsonb_build_object(
        'review_date_range_start',
        ms.summary_json -> 'total_stats' ->> 'date_range_start',
        'review_date_range_end',
        ms.summary_json -> 'total_stats' ->> 'date_range_end'
    )
FROM merged_summaries ms
WHERE r.merged_summary_id = ms.id
  AND ms.summary_json -> 'total_stats' ->> 'date_range_start' IS NOT NULL
  AND ms.summary_json -> 'total_stats' ->> 'date_range_end' IS NOT NULL
  AND r.report_json ->> 'review_date_range_start' IS NULL
  AND r.report_json ->> 'review_date_range_end' IS NULL
"""

_COUNT_SQL = """
SELECT count(*) AS n
FROM reports r
JOIN merged_summaries ms ON r.merged_summary_id = ms.id
WHERE ms.summary_json -> 'total_stats' ->> 'date_range_start' IS NOT NULL
  AND ms.summary_json -> 'total_stats' ->> 'date_range_end' IS NOT NULL
  AND r.report_json ->> 'review_date_range_start' IS NULL
  AND r.report_json ->> 'review_date_range_end' IS NULL
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill review date range into report_json")
    parser.add_argument("--apply", action="store_true", help="Actually run the UPDATE (default is dry-run)")
    args = parser.parse_args()

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(_COUNT_SQL)
        row = cur.fetchone()
        eligible = row["n"] if row else 0
        print(f"Reports eligible for backfill: {eligible}")

        if eligible == 0:
            print("Nothing to do.")
            return

        if not args.apply:
            print("Dry-run mode — pass --apply to execute the UPDATE.")
            return

        cur.execute(_BACKFILL_SQL)
        updated = cur.rowcount
        conn.commit()
        print(f"Updated {updated} reports.")


if __name__ == "__main__":
    main()
