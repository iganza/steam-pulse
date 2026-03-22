"""One-time migration: backfill all game slugs to {slug}-{appid} format.

Usage:
    poetry run python scripts/migrate_slugs.py
    poetry run python scripts/migrate_slugs.py --dry-run
"""
import argparse
import os
import re
import sys

import psycopg2
import psycopg2.extras


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT appid, name, slug FROM games ORDER BY appid")
        rows = cur.fetchall()

    print(f"Found {len(rows)} games to migrate")

    updates = []
    for row in rows:
        appid = row["appid"]
        name = row["name"] or f"App {appid}"
        new_slug = f"{slugify(name) or 'app'}-{appid}"
        if row["slug"] != new_slug:
            updates.append((new_slug, appid))

    print(f"{len(updates)} slugs need updating")
    if args.dry_run:
        for new_slug, appid in updates[:20]:
            print(f"  appid={appid}: {next((r['slug'] for r in rows if r['appid'] == appid), '?')} → {new_slug}")
        if len(updates) > 20:
            print(f"  ... and {len(updates) - 20} more")
        print("Dry run — no changes made")
        return

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "UPDATE games SET slug = data.slug FROM (VALUES %s) AS data(slug, appid) WHERE games.appid = data.appid",
            updates,
        )
        updated = cur.rowcount
    conn.commit()
    conn.close()
    print(f"Done — updated {updated} slugs")


if __name__ == "__main__":
    main()
