#!/usr/bin/env python3
"""Export games that still need review crawling to a CSV file.

A game is included if:
  - meta_status = 'done' and reviews_completed_at IS NULL
  - stored review count is < 95% of target (min(review_count_english, 2000))

Uses mv_review_counts for stored counts — run REFRESH MATERIALIZED VIEW
mv_review_counts first if it may be stale.

Usage:
    # Against local DB (default)
    poetry run python scripts/review_backfill_gaps.py

    # Against production (tunnel must be open on port 5433)
    DATABASE_URL="postgresql://steampulse:<pass>@127.0.0.1:5433/production_steampulse" \
        poetry run python scripts/review_backfill_gaps.py

    # Custom output path
    poetry run python scripts/review_backfill_gaps.py --out /tmp/gaps.csv

    # Only show games missing ALL reviews (never started)
    poetry run python scripts/review_backfill_gaps.py --never-started
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

DB_URL = os.getenv("DATABASE_URL", "postgresql://steampulse:dev@127.0.0.1:5432/steampulse")
DEFAULT_OUT = Path("review_backfill_gaps.csv")
CRAWL_CAP = 2000  # max reviews we fetch per game
THRESHOLD_PCT = 0.95  # games below this are considered incomplete


QUERY = """
SELECT
    g.appid,
    g.name,
    g.review_count_english                              AS expected_steam,
    LEAST(g.review_count_english, %(cap)s)              AS target,
    COALESCE(rc.stored_count, 0)                        AS stored,
    LEAST(g.review_count_english, %(cap)s)
        - COALESCE(rc.stored_count, 0)                  AS gap,
    ROUND(
        COALESCE(rc.stored_count, 0)::numeric
        / NULLIF(LEAST(g.review_count_english, %(cap)s), 0) * 100,
        1
    )                                                   AS pct_complete,
    g.release_date,
    ac.reviews_completed_at
FROM app_catalog ac
JOIN games g ON g.appid = ac.appid
LEFT JOIN mv_review_counts rc ON rc.appid = ac.appid
WHERE ac.meta_status = 'done'
  AND ac.reviews_completed_at IS NULL
  AND g.coming_soon = false
  AND g.review_count_english >= 50
  AND g.release_date IS NOT NULL
  AND COALESCE(rc.stored_count, 0)
      < LEAST(g.review_count_english, %(cap)s) * %(threshold)s
ORDER BY gap DESC, g.review_count_english DESC
"""

NEVER_STARTED_FILTER = "  AND COALESCE(rc.stored_count, 0) = 0\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export review backfill gaps to CSV")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output CSV path")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Run REFRESH MATERIALIZED VIEW mv_review_counts before querying",
    )
    parser.add_argument(
        "--never-started",
        action="store_true",
        help="Only include games with zero stored reviews",
    )
    args = parser.parse_args()

    query = QUERY
    if args.never_started:
        # Inject extra filter before ORDER BY
        query = query.replace("ORDER BY gap DESC", NEVER_STARTED_FILTER + "ORDER BY gap DESC")

    try:
        conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception as e:
        print(f"ERROR: could not connect to DB: {e}", file=sys.stderr)
        print("Is the SSH tunnel open? Set DATABASE_URL env var.", file=sys.stderr)
        sys.exit(1)

    with conn, conn.cursor() as cur:
        if args.refresh:
            print("Refreshing mv_review_counts... ", end="", flush=True)
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_review_counts")
            conn.commit()
            print("done.")
        cur.execute(query, {"cap": CRAWL_CAP, "threshold": THRESHOLD_PCT})
        rows = cur.fetchall()
        cur.execute("SELECT COALESCE(SUM(stored_count), 0) AS total FROM mv_review_counts")
        total_stored = cur.fetchone()["total"]

    if not rows:
        print("No gaps found — all eligible games have sufficient reviews.")
        return

    out: Path = args.out
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    total_gap = sum(r["gap"] for r in rows)
    never_started = sum(1 for r in rows if r["stored"] == 0)

    print(f"Written {len(rows):,} games to {out}")
    print(f"  Total reviews in DB   : {total_stored:,}")
    print(f"  Total missing reviews : {total_gap:,}")
    print(f"  Never started (0 stored): {never_started:,}")
    print(f"  Partially crawled     : {len(rows) - never_started:,}")


if __name__ == "__main__":
    main()
