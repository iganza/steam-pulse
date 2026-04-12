#!/usr/bin/env python3
"""
Backfill earliest Wayback Machine snapshot dates into app_catalog.discovered_at.

Only updates discovered_at when the Wayback date is OLDER than the current value,
preserving the earliest known date for each app.

Usage:
    # Local DB (default):
    poetry run python scripts/backfill_wayback_dates.py

    # Dry run (no DB writes, just print):
    poetry run python scripts/backfill_wayback_dates.py --dry-run

    # Limit to N apps:
    poetry run python scripts/backfill_wayback_dates.py --limit 100

    # Resume from a specific appid:
    poetry run python scripts/backfill_wayback_dates.py --start-from 440
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import httpx
import psycopg2

CDX_URL = "https://web.archive.org/cdx/search/cdx"
RATE_LIMIT = 0.5  # seconds between requests (2 req/sec)
HTTP_TIMEOUT = 120  # Wayback API can be very slow


def log(msg: str) -> None:
    """Print with timestamp and flush immediately so output is visible in real time."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def parse_wayback_timestamp(ts: str) -> datetime:
    """Parse Wayback CDX timestamp (YYYYMMDDHHmmss) to UTC datetime."""
    return datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def fetch_earliest_snapshot(client: httpx.Client, appid: int) -> datetime | None:
    """Query Wayback CDX for the earliest snapshot of a Steam store page."""
    url = f"store.steampowered.com/app/{appid}"
    params = {
        "url": url,
        "output": "json",
        "limit": "1",
        "fl": "timestamp,statuscode",
        "sort": "asc",
    }
    log(f"    GET {CDX_URL}?url={url} ...")
    t0 = time.monotonic()
    resp = client.get(CDX_URL, params=params)
    elapsed = time.monotonic() - t0
    log(f"    <- HTTP {resp.status_code} in {elapsed:.1f}s ({len(resp.content)} bytes)")
    resp.raise_for_status()

    rows = resp.json()
    if len(rows) < 2:
        log(f"    no archived snapshots for appid={appid}")
        return None

    ts, status = rows[1]
    log(f"    earliest snapshot: {ts} (HTTP {status})")
    if status in ("200", "301", "302"):
        return parse_wayback_timestamp(ts)
    log(f"    skipping — status {status} not usable")
    return None


def get_appids(conn: psycopg2.extensions.connection, *, start_from: int, limit: int | None) -> list[int]:
    """Fetch appids ordered by appid."""
    log(f"Querying app_catalog for appids >= {start_from} ...")
    sql = """
        SELECT appid FROM app_catalog
        WHERE appid >= %s
        ORDER BY appid
    """
    params: list[object] = [start_from]
    if limit:
        sql += " LIMIT %s"
        params.append(limit)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = [row[0] for row in cur.fetchall()]
    log(f"Found {len(rows)} appids to process")
    return rows


def update_discovered_at(conn: psycopg2.extensions.connection, appid: int, dt: datetime) -> int:
    """Update discovered_at only if the Wayback date is older. Returns rows affected."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE app_catalog SET discovered_at = %s WHERE appid = %s AND discovered_at > %s",
            (dt, appid, dt),
        )
        updated = cur.rowcount
    conn.commit()
    return updated


def fmt_eta(remaining: int, rate: float) -> str:
    """Format estimated time remaining."""
    if rate <= 0:
        return "?"
    secs = remaining / rate
    if secs < 60:
        return f"{secs:.0f}s"
    if secs < 3600:
        return f"{secs / 60:.0f}m"
    return f"{secs / 3600:.1f}h"


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Wayback Machine dates for Steam apps")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to DB")
    parser.add_argument("--limit", type=int, default=None, help="Max number of apps to process")
    parser.add_argument("--start-from", type=int, default=0, help="Start from this appid (for resuming)")
    args = parser.parse_args()

    log("=" * 60)
    log("Wayback Machine backfill starting")
    log(f"  dry_run={args.dry_run}  limit={args.limit}  start_from={args.start_from}")
    log(f"  rate_limit={RATE_LIMIT}s  timeout={HTTP_TIMEOUT}s")
    log("=" * 60)

    db_url = os.environ.get("DATABASE_URL", "postgresql://steampulse:dev@127.0.0.1:5432/steampulse")
    log(f"Connecting to DB: {db_url.split('@')[1] if '@' in db_url else db_url} ...")
    try:
        conn = psycopg2.connect(db_url, connect_timeout=10)
    except Exception as exc:
        log(f"FATAL: cannot connect to DB: {exc}")
        sys.exit(1)
    log("DB connected")

    appids = get_appids(conn, start_from=args.start_from, limit=args.limit)
    total = len(appids)
    if total == 0:
        log("Nothing to do — no appids matched")
        conn.close()
        return

    found = 0
    missed = 0
    errors = 0
    updated = 0
    start_time = time.monotonic()

    client = httpx.Client(
        headers={"User-Agent": "SteamPulse-Backfill/1.0 (steampulse.io)"},
        follow_redirects=True,
        timeout=HTTP_TIMEOUT,
    )

    log(f"Starting scan of {total} apps ...")
    log("-" * 60)

    try:
        for i, appid in enumerate(appids, 1):
            elapsed_total = time.monotonic() - start_time
            rate = i / elapsed_total if elapsed_total > 0 else 0
            eta = fmt_eta(total - i, rate)

            log(f"[{i}/{total}] appid={appid}  ({rate:.1f} apps/s, ETA {eta})")

            try:
                dt = fetch_earliest_snapshot(client, appid)

                if dt:
                    found += 1
                    if args.dry_run:
                        log(f"    FOUND {dt.strftime('%Y-%m-%d %H:%M')} UTC  (dry run, not writing)")
                    else:
                        rows = update_discovered_at(conn, appid, dt)
                        if rows:
                            updated += 1
                            log(f"    UPDATED discovered_at -> {dt.strftime('%Y-%m-%d %H:%M')} UTC")
                        else:
                            log(f"    FOUND {dt.strftime('%Y-%m-%d %H:%M')} UTC  (current discovered_at is already older)")
                else:
                    missed += 1

            except httpx.HTTPStatusError as exc:
                errors += 1
                status = exc.response.status_code
                log(f"    HTTP ERROR {status}")
                if status == 429:
                    log("    Rate limited by Wayback — sleeping 30s ...")
                    time.sleep(30)
            except httpx.TimeoutException:
                errors += 1
                log(f"    TIMEOUT after {HTTP_TIMEOUT}s — skipping")
            except (httpx.RequestError, ValueError) as exc:
                errors += 1
                log(f"    ERROR: {type(exc).__name__}: {exc}")

            # Progress summary every 50 apps
            if i % 50 == 0:
                log("-" * 60)
                log(f"  PROGRESS: {i}/{total} processed | found={found} missed={missed} updated={updated} errors={errors}")
                log("-" * 60)

            time.sleep(RATE_LIMIT)

    except KeyboardInterrupt:
        log("")
        log(f"INTERRUPTED at appid={appid}")
        log(f"Resume with: --start-from {appid}")
    finally:
        client.close()
        conn.close()

    elapsed_total = time.monotonic() - start_time
    log("=" * 60)
    log("DONE")
    log(f"  processed: {i}/{total}")
    log(f"  found:     {found}  ({found * 100 / max(i, 1):.0f}% hit rate)")
    log(f"  missed:    {missed}")
    log(f"  updated:   {updated}  (discovered_at moved earlier)")
    log(f"  errors:    {errors}")
    log(f"  elapsed:   {elapsed_total / 60:.1f} min")
    log("=" * 60)


if __name__ == "__main__":
    main()
