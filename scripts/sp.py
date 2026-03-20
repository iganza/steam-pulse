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
os.environ.setdefault("SFN_ARN", "local")
os.environ.setdefault("REVIEW_CRAWL_QUEUE_URL", "local")
os.environ.setdefault("DB_SECRET_ARN", "local")
os.environ.setdefault("APP_CRAWL_QUEUE_URL", "local")
os.environ.setdefault("STEAM_API_KEY_SECRET_ARN", "local")
os.environ.setdefault("ASSETS_BUCKET_NAME", "local")
os.environ.setdefault("STEP_FUNCTIONS_ARN", "local")
os.environ.setdefault("GAME_EVENTS_TOPIC_ARN", "local")
os.environ.setdefault("CONTENT_EVENTS_TOPIC_ARN", "local")
os.environ.setdefault("SYSTEM_EVENTS_TOPIC_ARN", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")

from library_layer.repositories.catalog_repo import CatalogRepository  # noqa: E402
from library_layer.repositories.game_repo import GameRepository  # noqa: E402
from library_layer.repositories.report_repo import ReportRepository  # noqa: E402
from library_layer.repositories.review_repo import ReviewRepository  # noqa: E402
from library_layer.repositories.tag_repo import TagRepository  # noqa: E402
from library_layer.config import SteamPulseConfig  # noqa: E402
from library_layer.services.crawl_service import CrawlService  # noqa: E402
from library_layer.steam_source import DirectSteamSource  # noqa: E402

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

APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"


def _conn() -> psycopg2.extensions.connection:
    return psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def _get_repos() -> tuple[
    psycopg2.extensions.connection,
    GameRepository,
    CatalogRepository,
    ReportRepository,
    ReviewRepository,
]:
    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return (
        conn,
        GameRepository(conn),
        CatalogRepository(conn),
        ReportRepository(conn),
        ReviewRepository(conn),
    )



class _NoOpSnsClient:
    """Silently discards all SNS publish calls — used when running locally."""
    def publish(self, **kwargs: object) -> dict:
        return {"MessageId": "no-op"}


def _has_real_aws_credentials() -> bool:
    """Return True if real AWS credentials are available (not the local dummy values)."""
    return os.environ.get("AWS_ACCESS_KEY_ID", "local") not in ("local", "testing", "")


def _build_crawl_service(
    conn: psycopg2.extensions.connection,
    http_async: httpx.AsyncClient,
) -> CrawlService:
    import boto3
    real_aws = _has_real_aws_credentials()
    return CrawlService(
        game_repo=GameRepository(conn),
        review_repo=ReviewRepository(conn),
        catalog_repo=CatalogRepository(conn),
        tag_repo=TagRepository(conn),
        steam=DirectSteamSource(http_async),
        sns_client=_NoOpSnsClient(),
        config=SteamPulseConfig(),
        game_events_topic_arn="noop",
        content_events_topic_arn="noop",
        sqs_client=None,
        review_queue_url="",
        sfn_arn=None,
        sfn_client=None,
        s3_client=boto3.client("s3") if real_aws else None,
        archive_bucket=os.getenv("ARCHIVE_BUCKET", "steampulse-raw-archive-v1") if real_aws else None,
    )


def _fetch_app_list(client: httpx.Client, api_key: str | None = None) -> list[dict]:
    """Return [{appid, name}, ...] from IStoreService/GetAppList (cursor-paginated)."""
    if not api_key:
        raise ValueError("STEAM_API_KEY is required for IStoreService/GetAppList/v1/")
    apps: list[dict] = []
    last_appid: int | None = None
    while True:
        params: dict = {"key": api_key, "max_results": 50000, "include_games": 1}
        if last_appid is not None:
            params["last_appid"] = last_appid
        resp = client.get(APP_LIST_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("response", {})
        batch = data.get("apps", [])
        apps.extend({"appid": a["appid"], "name": a.get("name", "")} for a in batch)
        if not data.get("have_more_results"):
            break
        last_appid = data.get("last_appid")
    return apps


# ── catalog ──────────────────────────────────────────────────────────────────

def cmd_catalog_update(dry_run: bool, limit: int | None) -> None:
    api_key = os.getenv("STEAM_API_KEY")
    if not api_key:
        _warn("STEAM_API_KEY not set — Steam may reject the request")

    _info("Fetching Steam app list…")
    with httpx.Client(timeout=30) as client:
        apps = _fetch_app_list(client, api_key=api_key)

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

    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        new_rows = catalog_repo.bulk_upsert(apps)
    finally:
        conn.close()
    _ok(f"Upserted {len(apps):,} apps — {new_rows:,} new, {len(apps) - new_rows:,} existing")


def cmd_catalog_status() -> None:
    conn, _, catalog_repo, report_repo, _ = _get_repos()
    try:
        summary = catalog_repo.status_summary()
        reports = report_repo.count_all()
    finally:
        conn.close()

    meta = summary.get("meta", {})
    review = summary.get("review", {})
    total = sum(meta.values())

    _table(
        ["Phase", "Pending", "Done", "Failed", "Total"],
        [
            ["metadata", f"{meta.get('pending', 0):,}", f"{meta.get('done', 0):,}",
             f"{meta.get('failed', 0):,}", f"{total:,}"],
            ["reviews", f"{review.get('pending', 0):,}", f"{review.get('done', 0):,}",
             f"{review.get('failed', 0):,}", "—"],
            ["analysis", "—", f"{reports:,}", "—", "—"],
        ],
    )


# ── game ─────────────────────────────────────────────────────────────────────

def cmd_game_info(appid: int) -> None:
    conn, game_repo, catalog_repo, report_repo, review_repo = _get_repos()
    try:
        game = game_repo.find_by_appid(appid)
        catalog = catalog_repo.find_by_appid(appid)
        reviews_in_db = review_repo.count_by_appid(appid)
        report = report_repo.find_by_appid(appid)
    finally:
        conn.close()

    if not catalog:
        _err(f"appid {appid} not in app_catalog")
        return

    rows: list[list[str]] = [
        ["appid",               str(appid)],
        ["meta_status",         catalog.meta_status or "—"],
        ["review_status",       catalog.review_status or "—"],
    ]
    if game:
        rows += [
            ["name",            game.name or "—"],
            ["slug",            game.slug or "—"],
            ["steam reviews",   f"{game.review_count:,}" if game.review_count else "—"],
            ["price",           f"${game.price_usd:.2f}" if game.price_usd else "—"],
        ]
    rows.append(["reviews in DB", f"{reviews_in_db:,}"])
    if report:
        report_data = report.report_json if isinstance(report.report_json, dict) else {}
        rows += [
            ["last_analyzed",   str(report.last_analyzed)],
            ["sentiment",       report_data.get("overall_sentiment") or "—"],
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
        c = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            svc = _build_crawl_service(c, steam._client)  # type: ignore[attr-defined]
            if phase == "metadata":
                result = await svc.crawl_app(appid)
                return "done" if result else "skipped"
            else:
                n = await svc.crawl_reviews(appid)
                return "done" if n >= 0 else "skipped"
        except Exception as exc:
            _warn(f"appid={appid} error: {exc}")
            return "failed"
        finally:
            c.close()


async def _crawl_specific(appids: list[int], phase: str) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        for appid in appids:
            c = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
            try:
                svc = _build_crawl_service(c, client)
                if phase == "metadata":
                    result = await svc.crawl_app(appid)
                    _ok(f"appid={appid} metadata={'done' if result else 'skipped'}")
                else:
                    n = await svc.crawl_reviews(appid)
                    _ok(f"appid={appid} reviews={n}")
            except Exception as exc:
                _err(f"appid={appid} failed: {exc}")
            finally:
                c.close()


async def _crawl_bulk(phase: str, fetch_fn: object, concurrency: int) -> None:
    """Process all pending items for a phase with rate-limited concurrency."""
    batch_size = concurrency * 4
    sem = asyncio.Semaphore(concurrency)
    n_done = n_skipped = n_failed = 0
    start = time.monotonic()
    last_log = start

    # Fetch total pending count upfront for ETA calculation
    total_pending = len(fetch_fn(999_999))
    _info(f"[{phase}] starting — {total_pending:,} items pending")

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
                if r == "done":
                    n_done += 1
                elif r == "skipped":
                    n_skipped += 1
                else:
                    n_failed += 1

            now = time.monotonic()
            if now - last_log >= 30:
                processed = n_done + n_skipped + n_failed
                elapsed = now - start
                rate = processed / elapsed * 60 if elapsed > 0 else 0
                remaining = max(0, total_pending - processed)
                eta_min = remaining / rate if rate > 0 else 0
                eta_str = f"{eta_min/60:.1f}h" if eta_min >= 60 else f"{eta_min:.0f}m"
                pct = processed / total_pending * 100 if total_pending else 0
                _info(
                    f"[{phase}] {processed:,}/{total_pending:,} ({pct:.1f}%) | "
                    f"done={n_done:,} skipped={n_skipped:,} failed={n_failed:,} | "
                    f"{rate:.0f}/min | ETA {eta_str}"
                )
                last_log = now

    elapsed = time.monotonic() - start
    _ok(f"[{phase}] done={n_done:,} skipped={n_skipped:,} failed={n_failed:,} in {elapsed/60:.1f} min")


# ── fetch helpers for bulk modes ─────────────────────────────────────────────

def _pending_meta(n: int) -> list[int]:
    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        entries = catalog_repo.find_pending_meta(limit=n)
    finally:
        conn.close()
    return [e.appid for e in entries]


def _eligible_reviews(n: int) -> list[int]:
    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        entries = catalog_repo.find_pending_reviews(limit=n)
    finally:
        conn.close()
    return [e.appid for e in entries]


def _ready_for_analysis(n: int = 1000) -> list[int]:
    with psycopg2.connect(DB_URL) as c, c.cursor() as cur:
        cur.execute(
            """SELECT g.appid FROM games g
               JOIN app_catalog ac ON ac.appid = g.appid
               WHERE ac.review_status = 'done'
                 AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.appid = g.appid)
               ORDER BY g.review_count DESC NULLS LAST LIMIT %s""",
            (n,),
        )
        return [row[0] for row in cur.fetchall()]


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
    conn, game_repo, _, _, _ = _get_repos()
    try:
        game = game_repo.find_by_appid(appid)
    finally:
        conn.close()
    name = game.name if game else ""
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
