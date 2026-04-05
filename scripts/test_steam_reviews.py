#!/usr/bin/env python3
"""Test Steam review fetch — verifies full cursor chain exhaustion for a given appid.

Useful for checking how many English reviews Steam's API will actually return
vs the reported review_count_english in the games table.

Usage:
    poetry run python scripts/test_steam_reviews.py 934700
    poetry run python scripts/test_steam_reviews.py 934700 --max 500
"""

import argparse
import datetime
import json
import time
import urllib.parse
import urllib.request


def fetch_all(appid: int, max_reviews: int | None = None) -> None:
    cursor = "*"
    total = 0
    batch_num = 0
    oldest = "?"

    while True:
        if max_reviews and total >= max_reviews:
            print(f"\nStopped at cap: {total} reviews fetched")
            return

        url = (
            f"https://store.steampowered.com/appreviews/{appid}"
            f"?json=1&filter=recent&language=english"
            f"&num_per_page=100&purchase_type=all"
            f"&cursor={urllib.parse.quote(cursor)}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        reviews = data.get("reviews", [])
        if not reviews:
            print(f"\nExhausted (empty batch): {total} reviews, oldest={oldest}")
            return

        total += len(reviews)
        batch_num += 1
        oldest_ts = min(r["timestamp_created"] for r in reviews)
        oldest = datetime.datetime.fromtimestamp(oldest_ts).strftime("%Y-%m-%d")
        next_cursor = data.get("cursor", "")
        exhausted = not next_cursor or next_cursor == cursor

        print(
            f"batch {batch_num:3d}: +{len(reviews):3d} = {total:5d} total"
            f"cursor {cursor}"
            f"  oldest_in_batch={oldest}"
            f"{'  EXHAUSTED' if exhausted else ''}"
        )

        if exhausted:
            print(f"\nDone: {total} reviews fetched, oldest={oldest}")
            return

        cursor = next_cursor
        time.sleep(10.4)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Test Steam review fetch exhaustion")
    p.add_argument("appid", type=int, help="Steam appid to test")
    p.add_argument("--max", type=int, default=None, help="Stop after N reviews")
    args = p.parse_args()
    fetch_all(args.appid, args.max)
