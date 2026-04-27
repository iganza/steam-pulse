"""Warm CloudFront / OpenNext ISR cache for /games/{appid}/{slug} pages.

Pages through the same /api/games source the sitemap uses, then GETs each
canonical game URL with bounded concurrency. Run after a deploy that affects
rendered HTML so Googlebot's first crawl hits warm cache.

Usage:
    poetry run python scripts/warm_game_pages.py
    poetry run python scripts/warm_game_pages.py --base-url https://steampulse.io
    poetry run python scripts/warm_game_pages.py --concurrency 5 --limit 200

TODO: wire as scheduled EventBridge → Lambda gated on config.is_production.
"""

import argparse
import asyncio
import statistics
import sys
import time
from collections import Counter

import httpx

MIN_REVIEWS = 10
PAGE_SIZE = 1000
MAX_URLS = 49000  # mirrors frontend/app/sitemap.ts


async def _fetch_games_page(client: httpx.AsyncClient, base_url: str, offset: int) -> list[dict]:
    resp = await client.get(
        f"{base_url}/api/games",
        params={
            "sort": "review_count",
            "min_reviews": MIN_REVIEWS,
            "limit": PAGE_SIZE,
            "offset": offset,
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    games = payload.get("games") if isinstance(payload, dict) else payload
    return games or []


async def _collect_urls(client: httpx.AsyncClient, base_url: str, cap: int) -> list[str]:
    urls: list[str] = []
    offset = 0
    while len(urls) < cap:
        games = await _fetch_games_page(client, base_url, offset)
        if not games:
            break
        for g in games:
            appid = g.get("appid")
            slug = g.get("slug")
            if not isinstance(appid, int) or not isinstance(slug, str) or not slug:
                continue
            urls.append(f"{base_url}/games/{appid}/{slug}")
            if len(urls) >= cap:
                break
        if len(games) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return urls


async def _warm_one(
    client: httpx.AsyncClient, url: str
) -> tuple[str, int | None, float, str | None]:
    start = time.monotonic()
    try:
        resp = await client.get(url)
        ttfb_ms = (time.monotonic() - start) * 1000
        return url, resp.status_code, ttfb_ms, None
    except Exception as exc:
        ttfb_ms = (time.monotonic() - start) * 1000
        return url, None, ttfb_ms, type(exc).__name__


async def _worker(
    name: str,
    client: httpx.AsyncClient,
    queue: "asyncio.Queue[str]",
    ok_ttfb: list[float],
    fail_ttfb: list[float],
    status_counts: Counter[str],
    errors: Counter[str],
) -> None:
    while True:
        try:
            url = queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        url, status, ttfb_ms, err = await _warm_one(client, url)
        if err is not None:
            errors[err] += 1
            fail_ttfb.append(ttfb_ms)
            print(f"  FAIL {err:<25} {ttfb_ms:>7.0f} ms  {url}")
        else:
            status_counts[str(status)] += 1
            if status and 200 <= status < 400:
                ok_ttfb.append(ttfb_ms)
            else:
                fail_ttfb.append(ttfb_ms)
            print(f"  {status} {ttfb_ms:>7.0f} ms  {url}")
        queue.task_done()


async def _run(base_url: str, concurrency: int, read_timeout: float, cap: int) -> int:
    base_url = base_url.rstrip("/")
    timeout_cfg = httpx.Timeout(connect=5.0, read=read_timeout, write=5.0, pool=5.0)
    limits = httpx.Limits(max_connections=concurrency * 2, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(
        timeout=timeout_cfg, limits=limits, follow_redirects=True
    ) as client:
        print(f"Discovering URLs from {base_url}/api/games (min_reviews={MIN_REVIEWS}, cap={cap})…")
        urls = await _collect_urls(client, base_url, cap)
        print(f"Discovered {len(urls)} URLs. Warming with concurrency={concurrency}…")

        # Worker pool: N workers pull from a shared queue. Caps live tasks at N
        # regardless of URL count (avoids 49k concurrent task objects).
        queue: asyncio.Queue[str] = asyncio.Queue()
        for u in urls:
            queue.put_nowait(u)

        ok_ttfb: list[float] = []
        fail_ttfb: list[float] = []
        status_counts: Counter[str] = Counter()
        errors: Counter[str] = Counter()

        workers = [
            asyncio.create_task(
                _worker(f"w{i}", client, queue, ok_ttfb, fail_ttfb, status_counts, errors)
            )
            for i in range(concurrency)
        ]
        await asyncio.gather(*workers)

        total = len(urls)
        ok = len(ok_ttfb)
        failed = total - ok
        print()
        print("─" * 60)
        print(f"Total: {total}  OK: {ok}  Failed: {failed}")
        if status_counts:
            print(f"Status: {dict(status_counts)}")
        if errors:
            print(f"Errors: {dict(errors)}")
        if ok_ttfb:
            ok_ttfb.sort()
            p50 = statistics.median(ok_ttfb)
            p95 = ok_ttfb[max(0, int(len(ok_ttfb) * 0.95) - 1)]
            print(f"OK TTFB ms: p50={p50:.0f}  p95={p95:.0f}  max={ok_ttfb[-1]:.0f}")
        return 0 if total > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base-url", default="https://steampulse.io")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request read timeout (s)")
    parser.add_argument(
        "--limit", type=int, default=MAX_URLS, help=f"Max URLs to warm (cap {MAX_URLS})"
    )
    args = parser.parse_args()
    cap = max(1, min(args.limit, MAX_URLS))
    return asyncio.run(_run(args.base_url, args.concurrency, args.timeout, cap))


if __name__ == "__main__":
    sys.exit(main())
