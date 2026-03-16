#!/usr/bin/env python3
"""sp.py — SteamPulse local CLI.

Usage:
  poetry run python scripts/sp.py catalog update [--dry-run] [--limit N]
  poetry run python scripts/sp.py catalog status

  poetry run python scripts/sp.py game info <appid>
  poetry run python scripts/sp.py game crawl <appid...>
  poetry run python scripts/sp.py game crawl --all [-c N]

  poetry run python scripts/sp.py reviews crawl <appid...>
  poetry run python scripts/sp.py reviews crawl --eligible [-c N]

  poetry run python scripts/sp.py analyze <appid...>
  poetry run python scripts/sp.py analyze --ready

  poetry run python scripts/sp.py seed [appid...]   # default: TF2, CS2, Dota2, Cyberpunk, Stardew

Requires:
  DATABASE_URL  (defaults to postgresql://steampulse:dev@127.0.0.1:5432/steampulse)
  STEAM_API_KEY in .env  (catalog / game / reviews commands)
  ANTHROPIC_API_KEY in .env  (analyze command)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "library-layer"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "lambda-functions"))

load_dotenv(os.path.join(REPO_ROOT, ".env"))

# Disable cloud triggers — we drive the pipeline manually
os.environ.setdefault("SFN_ARN", "")
os.environ.setdefault("REVIEW_CRAWL_QUEUE_URL", "")
os.environ.setdefault("DB_SECRET_ARN", "")

from library_layer.steam_source import DirectSteamSource  # noqa: E402
from lambda_functions.crawler.app_crawl import crawl_app  # noqa: E402
from lambda_functions.crawler.review_crawl import crawl_reviews  # noqa: E402
from lambda_functions.crawler.catalog_refresh import fetch_app_list, upsert_catalog  # noqa: E402

try:
    from rich.console import Console
    from rich.table import Table
    _con = Console()

    def _table(headers: list[str], rows: list[list[str]]) -> None:
        t = Table(*headers, show_header=True, header_style="bold cyan")
        for row in rows:
            t.add_row(*[str(c) for c in row])
        _con.print(t)

    def _info(msg: str) -> None: _con.print(f"[cyan]▶[/cyan] {msg}")
    def _ok(msg: str) -> None:   _con.print(f"[green]✓[/green] {msg}")
    def _warn(msg: str) -> None: _con.print(f"[yellow]⚠[/yellow]  {msg}")
    def _err(msg: str) -> None:  _con.print(f"[red]✗[/red] {msg}")

except ImportError:
    def _table(headers: list[str], rows: list[list[str]]) -> None:
        print("  ".join(f"{h:<20}" for h in headers))
        for row in rows:
            print("  ".join(f"{c:<20}" for c in row))

    def _info(msg: str) -> None: print(f"▶ {msg}")
    def _ok(msg: str) -> None:   print(f"✓ {msg}")
    def _warn(msg: str) -> None: print(f"⚠  {msg}")
    def _err(msg: str) -> None:  print(f"✗ {msg}", file=sys.stderr)


DB_URL = os.getenv("DATABASE_URL", "postgresql://steampulse:dev@127.0.0.1:5432/steampulse")

DEFAULT_SEED_APPIDS = [440, 730, 570, 1091500, 413150]  # TF2, CS2, Dota2, Cyberpunk, Stardew


def _conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DB_URL)


# ── catalog ──────────────────────────────────────────────────────────────────

def cmd_catalog_update(dry_run: bool, limit: int | None) -> None:
    api_key = os.getenv("STEAM_API_KEY")
    if not api_key:
        _warn("STEAM_API_KEY not set — Steam may reject the request")

    _info("Fetching Steam app list…")
    with httpx.Client(timeout=30) as client:
        apps = fetch_app_list(client, api_key=api_key)

    apps = [a for a in apps if a.get("name", "").strip()]
    _info(f"Fetched {len(apps):,} named apps")

    if limit:
        apps = apps[:limit]
        _info(f"Limited to first {limit:,}")

    if dry_run:
        print(f"\n[dry-run] Would upsert {len(apps):,} apps")
        for a in apps[:10]:
            print(f"  {a['appid']:<10} {a['name']!r}")
        if len(apps) > 10:
            print(f"  … and {len(apps) - 10:,} more")
        return

    c = _conn()
    new_rows = upsert_catalog(c, apps)
    c.close()
    _ok(f"Upserted {len(apps):,} apps — {new_rows:,} new, {len(apps) - new_rows:,} existing")


def cmd_catalog_status() -> None:
    with _conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT
              COUNT(*) FILTER (WHERE meta_status   = 'pending')                        AS meta_pending,
              COUNT(*) FILTER (WHERE meta_status   = 'done')                           AS meta_done,
              COUNT(*) FILTER (WHERE meta_status   = 'failed')                         AS meta_failed,
              COUNT(*) FILTER (WHERE review_status = 'pending' AND meta_status='done') AS rev_pending,
              COUNT(*) FILTER (WHERE review_status = 'done')                           AS rev_done,
              COUNT(*) FILTER (WHERE review_status = 'failed')                         AS rev_failed,
              COUNT(*)                                                                  AS total
            FROM app_catalog
        """)
        mp, md, mf, rp, rd, rf, total = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM reports")
        reports = cur.fetchone()[0]

    _table(
        ["Phase", "Pending", "Done", "Failed", "Total"],
        [
            ["metadata", f"{mp:,}", f"{md:,}", f"{mf:,}", f"{total:,}"],
            ["reviews",  f"{rp:,}", f"{rd:,}", f"{rf:,}", "—"],
            ["analysis", "—",       f"{reports:,}", "—",  "—"],
        ],
    )


# ── game ─────────────────────────────────────────────────────────────────────

def cmd_game_info(appid: int) -> None:
    with _conn() as c:
        with c.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM games WHERE appid = %s", (appid,))
            game = cur.fetchone()
            cur.execute("SELECT meta_status, review_status FROM app_catalog WHERE appid = %s", (appid,))
            catalog = cur.fetchone()
            cur.execute("SELECT COUNT(*) AS n FROM reviews WHERE appid = %s", (appid,))
            reviews_in_db = cur.fetchone()["n"]
            cur.execute("SELECT last_analyzed, overall_sentiment FROM reports WHERE appid = %s", (appid,))
            report = cur.fetchone()

    if not catalog:
        _err(f"appid {appid} not in app_catalog")
        return

    rows: list[list[str]] = [
        ["appid",               str(appid)],
        ["meta_status",         catalog["meta_status"] or "—"],
        ["review_status",       catalog["review_status"] or "—"],
    ]
    if game:
        rows += [
            ["name",            game.get("name") or "—"],
            ["slug",            game.get("slug") or "—"],
            ["steam reviews",   f"{game['review_count']:,}" if game.get("review_count") else "—"],
            ["price",           f"${game['price_usd']:.2f}" if game.get("price_usd") else "—"],
        ]
    rows.append(["reviews in DB", f"{reviews_in_db:,}"])
    if report:
        rows += [
            ["last_analyzed",   str(report["last_analyzed"])],
            ["sentiment",       report["overall_sentiment"] or "—"],
        ]
    else:
        rows.append(["report", "none"])

    _table(["Field", "Value"], rows)


# ── shared async crawl machinery ─────────────────────────────────────────────

async def _crawl_one(
    appid: int,
    phase: str,
    steam: DirectSteamSource,
    sem: asyncio.Semaphore,
) -> str:
    async with sem:
        c = _conn()
        try:
            if phase == "metadata":
                result = await crawl_app(appid, steam, c)
                return "done" if result else "skipped"
            else:
                n = await crawl_reviews(appid, steam, c)
                return "done" if n >= 0 else "skipped"
        except Exception as exc:
            _warn(f"appid={appid} error: {exc}")
            return "failed"
        finally:
            c.close()


async def _crawl_specific(appids: list[int], phase: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        steam = DirectSteamSource(client)
        for appid in appids:
            c = _conn()
            try:
                if phase == "metadata":
                    result = await crawl_app(appid, steam, c)
                    _ok(f"appid={appid} metadata={'done' if result else 'skipped'}")
                else:
                    n = await crawl_reviews(appid, steam, c)
                    _ok(f"appid={appid} reviews={n}")
            except Exception as exc:
                _err(f"appid={appid} failed: {exc}")
            finally:
                c.close()


async def _crawl_bulk(phase: str, fetch_fn, concurrency: int) -> None:
    """Process all pending items for a phase with rate-limited concurrency."""
    batch_size = concurrency * 4
    sem = asyncio.Semaphore(concurrency)
    n_done = n_skipped = n_failed = 0
    start = time.monotonic()
    last_log = start

    async with httpx.AsyncClient(timeout=30.0) as client:
        steam = DirectSteamSource(client)
        while True:
            batch = fetch_fn(batch_size)
            if not batch:
                break
            results = await asyncio.gather(
                *[_crawl_one(a, phase, steam, sem) for a in batch]
            )
            for r in results:
                if r == "done":    n_done += 1
                elif r == "skipped": n_skipped += 1
                else:              n_failed += 1

            now = time.monotonic()
            if now - last_log >= 30:
                processed = n_done + n_skipped + n_failed
                rate = processed / (now - start) * 60
                _info(f"[{phase}] {processed} | done={n_done} skipped={n_skipped} failed={n_failed} | {rate:.0f}/min")
                last_log = now

    elapsed = time.monotonic() - start
    _ok(f"[{phase}] done={n_done} skipped={n_skipped} failed={n_failed} in {elapsed/60:.1f} min")


# ── fetch helpers for bulk modes ─────────────────────────────────────────────

def _pending_meta(n: int) -> list[int]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT appid FROM app_catalog WHERE meta_status='pending' ORDER BY appid LIMIT %s", (n,)
        )
        return [r[0] for r in cur.fetchall()]


def _eligible_reviews(n: int) -> list[int]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT appid FROM app_catalog
               WHERE review_status='pending' AND meta_status='done'
               ORDER BY review_count DESC NULLS LAST LIMIT %s""",
            (n,),
        )
        return [r[0] for r in cur.fetchall()]


def _ready_for_analysis(n: int = 1000) -> list[int]:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT g.appid FROM games g
               JOIN app_catalog ac ON ac.appid = g.appid
               WHERE ac.review_status = 'done'
                 AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.appid = g.appid)
               ORDER BY g.review_count DESC NULLS LAST LIMIT %s""",
            (n,),
        )
        return [r[0] for r in cur.fetchall()]


# ── subcommand implementations ────────────────────────────────────────────────

def cmd_game_crawl(appids: list[int], all_pending: bool, concurrency: int) -> None:
    if all_pending:
        asyncio.run(_crawl_bulk("metadata", _pending_meta, concurrency))
    else:
        asyncio.run(_crawl_specific(appids, "metadata"))


def cmd_reviews_crawl(appids: list[int], eligible: bool, concurrency: int) -> None:
    if eligible:
        asyncio.run(_crawl_bulk("reviews", _eligible_reviews, concurrency))
    else:
        asyncio.run(_crawl_specific(appids, "reviews"))


class _MockLambdaContext:
    function_name = "local-analysis"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-west-2:000000000000:function:local"
    aws_request_id = "local"


def _analyze_one(appid: int) -> None:
    from lambda_functions.analysis.handler import handler  # lazy import (heavy)
    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT name FROM games WHERE appid = %s", (appid,))
        row = cur.fetchone()
    name = row[0] if row else ""
    result = handler({"appid": appid, "game_name": name}, _MockLambdaContext())
    sentiment = result.get("overall_sentiment", "?") if isinstance(result, dict) else "?"
    _ok(f"appid={appid} sentiment={sentiment}")


def cmd_analyze(appids: list[int], ready: bool) -> None:
    targets = appids
    if ready:
        targets = _ready_for_analysis()
        _info(f"{len(targets)} games ready for analysis")
    if not targets:
        _warn("Nothing to analyze")
        return
    for appid in targets:
        _info(f"Analyzing appid={appid}…")
        try:
            _analyze_one(appid)
        except Exception as exc:
            _err(f"appid={appid} failed: {exc}")


def cmd_seed(appids: list[int]) -> None:
    _info(f"Full pipeline for {len(appids)} games: {appids}")
    _info("Stage 1/3 — metadata crawl")
    asyncio.run(_crawl_specific(appids, "metadata"))
    _info("Stage 2/3 — review crawl")
    asyncio.run(_crawl_specific(appids, "reviews"))
    _info("Stage 3/3 — LLM analysis")
    cmd_analyze(appids, ready=False)
    _ok("Seed complete")


# ── CLI wiring ────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sp.py",
        description="SteamPulse local operations CLI",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # ── catalog
    cat = sub.add_parser("catalog", help="Manage the app_catalog table")
    cat_sub = cat.add_subparsers(dest="catalog_cmd", required=True)

    cup = cat_sub.add_parser("update", help="Fetch Steam app list → app_catalog")
    cup.add_argument("--dry-run", action="store_true", help="Fetch only, no DB writes")
    cup.add_argument("--limit", type=int, metavar="N", help="Process only the first N apps")

    cat_sub.add_parser("status", help="Show pending/done/failed counts by phase")

    # ── game
    gm = sub.add_parser("game", help="Game metadata operations")
    gm_sub = gm.add_subparsers(dest="game_cmd", required=True)

    gi = gm_sub.add_parser("info", help="Show everything we know about a game")
    gi.add_argument("appid", type=int)

    gc = gm_sub.add_parser("crawl", help="Crawl Steam metadata for games")
    gc.add_argument("appids", type=int, nargs="*", metavar="appid",
                    help="Specific appids to crawl")
    gc.add_argument("--all", dest="all_pending", action="store_true",
                    help="Crawl all pending entries in app_catalog")
    gc.add_argument("-c", "--concurrency", type=int, default=1, metavar="N")

    # ── reviews
    rv = sub.add_parser("reviews", help="Review crawl operations")
    rv_sub = rv.add_subparsers(dest="reviews_cmd", required=True)

    rc = rv_sub.add_parser("crawl", help="Crawl Steam reviews")
    rc.add_argument("appids", type=int, nargs="*", metavar="appid")
    rc.add_argument("--eligible", action="store_true",
                    help="Crawl all games with metadata done and reviews pending")
    rc.add_argument("-c", "--concurrency", type=int, default=1, metavar="N")

    # ── analyze
    az = sub.add_parser("analyze", help="Run LLM analysis (writes to reports table)")
    az.add_argument("appids", type=int, nargs="*", metavar="appid")
    az.add_argument("--ready", action="store_true",
                    help="Analyze all games that have reviews but no report yet")

    # ── seed
    sd = sub.add_parser("seed", help="Full pipeline: metadata → reviews → analysis")
    sd.add_argument("appids", type=int, nargs="*", metavar="appid",
                    help=f"Appids to seed (default: {DEFAULT_SEED_APPIDS})")

    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.cmd == "catalog":
        if args.catalog_cmd == "update":
            cmd_catalog_update(args.dry_run, args.limit)
        else:
            cmd_catalog_status()

    elif args.cmd == "game":
        if args.game_cmd == "info":
            cmd_game_info(args.appid)
        elif args.game_cmd == "crawl":
            if not args.appids and not args.all_pending:
                parser.error("game crawl requires appids or --all")
            cmd_game_crawl(args.appids, args.all_pending, args.concurrency)

    elif args.cmd == "reviews":
        if args.reviews_cmd == "crawl":
            if not args.appids and not args.eligible:
                parser.error("reviews crawl requires appids or --eligible")
            cmd_reviews_crawl(args.appids, args.eligible, args.concurrency)

    elif args.cmd == "analyze":
        if not args.appids and not args.ready:
            parser.error("analyze requires appids or --ready")
        cmd_analyze(args.appids, args.ready)

    elif args.cmd == "seed":
        cmd_seed(args.appids or DEFAULT_SEED_APPIDS)


if __name__ == "__main__":
    main()
