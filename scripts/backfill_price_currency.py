"""One-shot backfill: re-queue games with bogus non-USD `price_usd` values.

Reads bad-price appids from the local DB (DATABASE_URL, defaults to local
Postgres) and publishes each to the deployed app-crawl-queue so the spoke
pipeline re-crawls metadata under the new `cc=us` guard. Safe to re-run;
crawls are idempotent.

Disposable — delete after production verification.

Usage:
  poetry run python scripts/backfill_price_currency.py --env production --dry-run
  poetry run python scripts/backfill_price_currency.py --env production
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3
import psycopg2

PROD_DB_DSN = (
    "host=localhost port=5433 dbname=production_steampulse user=postgres "
    f"sslmode=verify-ca sslrootcert={os.path.expanduser('~/dev/git/saas/steam-pulse/global-bundle.pem')}"
)
DB_URL = os.getenv("DATABASE_URL", PROD_DB_DSN)
ADMIN_REGION = "us-west-2"

BAD_PRICE_SQL = (
    "SELECT appid FROM games WHERE is_free = false AND price_usd > 100 ORDER BY appid"
)


def _fetch_bad_appids() -> list[int]:
    with psycopg2.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(BAD_PRICE_SQL)
        return [row[0] for row in cur.fetchall()]


def _resolve_queue_url(env: str) -> str:
    ssm = boto3.client("ssm", region_name=ADMIN_REGION)
    param = f"/steampulse/{env}/messaging/app-crawl-queue-url"
    resp = ssm.get_parameter(Name=param)
    return resp["Parameter"]["Value"]


def _send_sqs_batch(queue_url: str, messages: list[dict]) -> int:
    sqs = boto3.client("sqs")
    sent = 0
    for i in range(0, len(messages), 10):
        batch = messages[i : i + 10]
        entries = [{"Id": str(j), "MessageBody": json.dumps(msg)} for j, msg in enumerate(batch)]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = resp.get("Failed", [])
        if failed:
            for f in failed:
                print(f"⚠  SQS send failed for Id={f['Id']}: [{f['Code']}] {f['Message']}")
            raise RuntimeError(f"{len(failed)} message(s) failed to enqueue in this batch")
        sent += len(batch)
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", default="staging", choices=["staging", "production"])
    parser.add_argument("--dry-run", action="store_true", help="List appids but don't enqueue")
    parser.add_argument(
        "--limit", type=int, metavar="N", help="Cap number of appids re-queued (for staged rollout)"
    )
    args = parser.parse_args()

    print(f"▶ Selecting bad-price rows from {DB_URL}")
    appids = _fetch_bad_appids()
    if args.limit:
        appids = appids[: args.limit]

    if not appids:
        print("✓ No rows match — nothing to backfill.")
        return 0

    print(f"▶ Found {len(appids)} appids with price_usd > 100")
    print(f"  first 10: {appids[:10]}")

    if args.dry_run:
        print(f"⚠  [dry-run] Would publish {len(appids)} messages to {args.env} app-crawl-queue")
        return 0

    queue_url = _resolve_queue_url(args.env)
    print(f"▶ Queue: {queue_url}")

    messages = [
        {"appid": appid, "task": "metadata", "source": "price_currency_backfill"}
        for appid in appids
    ]
    sent = _send_sqs_batch(queue_url, messages)
    print(f"✓ Published {sent} metadata messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
