"""Update the operator-curated editorial columns on mv_genre_synthesis.

The Phase-4 synthesizer output is LLM-generated and auto-refreshed weekly;
`editorial_intro` and `churn_interpretation` are human prose layered on top
to satisfy the "substantially edited by a named human expert" signal and
to read as a peer-to-peer research page rather than a raw AI dump.

Usage:
    # Local dev (against docker compose Postgres)
    poetry run python scripts/ops/update_editorial.py roguelike-deckbuilder \\
        --intro-file /path/to/intro.md \\
        --churn "Unlock grind hits around the 8-hour mark."

    # Staging / production — open an SSH tunnel first
    bash scripts/dev/db-tunnel.sh
    DATABASE_URL=postgresql://... poetry run python scripts/ops/update_editorial.py \\
        roguelike-deckbuilder --intro-file intro.md --churn "..."

At least one of --intro-file or --churn must be provided. Pass only the
flag you want to update; the other column is left untouched.

Flags:
    slug              Genre slug (matches mv_genre_synthesis.slug).
    --intro-file P    Path to a UTF-8 text file holding the 200-300 word
                      editorial intro. Whitespace trimmed.
    --churn T         One-line churn interpretation (string, trimmed).
    --dry-run         Print what would change; make no DB writes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update editorial_intro / churn_interpretation for a genre synthesis row."
    )
    parser.add_argument("slug", help="Genre slug (primary key of mv_genre_synthesis).")
    parser.add_argument(
        "--intro-file",
        type=Path,
        default=None,
        help="Path to a UTF-8 text file with the 200-300 word editorial intro.",
    )
    parser.add_argument(
        "--churn",
        type=str,
        default=None,
        help="One-line churn interpretation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change; make no DB writes.",
    )
    args = parser.parse_args()

    if args.intro_file is None and args.churn is None:
        parser.error("pass at least one of --intro-file or --churn")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    updates: dict[str, str] = {}
    if args.intro_file is not None:
        if not args.intro_file.is_file():
            print(f"ERROR: intro file not found: {args.intro_file}", file=sys.stderr)
            sys.exit(1)
        updates["editorial_intro"] = args.intro_file.read_text(encoding="utf-8").strip()
    if args.churn is not None:
        updates["churn_interpretation"] = args.churn.strip()

    conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT slug, display_name FROM mv_genre_synthesis WHERE slug = %s",
                (args.slug,),
            )
            existing = cur.fetchone()
            if existing is None:
                print(
                    f"ERROR: no mv_genre_synthesis row for slug={args.slug!r}. "
                    "Run the Phase-4 synthesizer for this tag first.",
                    file=sys.stderr,
                )
                sys.exit(1)

            print(f"Target: {existing['display_name']} ({args.slug})")
            for col, val in updates.items():
                preview = val if len(val) <= 120 else val[:117] + "..."
                print(f"  {col}: {preview!r} ({len(val)} chars)")

            if args.dry_run:
                print("DRY RUN — no rows written")
                return

            set_clause = ", ".join(f"{col} = %s" for col in updates)
            params = (*updates.values(), args.slug)
            cur.execute(
                f"UPDATE mv_genre_synthesis SET {set_clause} WHERE slug = %s",
                params,
            )
        conn.commit()
        print(f"Updated {len(updates)} column(s) for {args.slug}.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
