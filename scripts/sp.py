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

  poetry run python scripts/sp.py queue metadata <appid...>   # publish to deployed app-crawl queue
  poetry run python scripts/sp.py queue reviews <appid...>    # publish to deployed review-crawl queue
  poetry run python scripts/sp.py queue metadata --all        # all pending from app_catalog
  poetry run python scripts/sp.py queue reviews --eligible    # all eligible from app_catalog
  poetry run python scripts/sp.py queue tags <appid...>      # publish tag backfill for specific games
  poetry run python scripts/sp.py queue tags --all           # all games for Steam tag crawl
  poetry run python scripts/sp.py queue refresh-meta [--limit N]     # tier-due metadata + tags
  poetry run python scripts/sp.py queue refresh-reviews [--limit N]  # tier-due review refresh

  poetry run python scripts/sp.py db init [--env staging|production]
  poetry run python scripts/sp.py db status [--env staging|production]
  poetry run python scripts/sp.py db query "SELECT * FROM games LIMIT 5" [--env staging|production]

  poetry run python scripts/sp.py spokes status [--env staging|production]

  poetry run python scripts/sp.py logs errors [--env staging|production] [--minutes N] [--region REGION]

  poetry run python scripts/sp.py batch <appid...> [--env staging|production] [--watch] [--dry-run]
  poetry run python scripts/sp.py batch --all-eligible [--env staging|production] [--watch]

  poetry run python scripts/sp.py dispatch --env staging [--batch-size N] [--dry-run] [--watch]

  poetry run python scripts/sp.py matview-refresh --env staging [--force]

Requires:
  DATABASE_URL  (defaults to postgresql://steampulse:dev@127.0.0.1:5432/steampulse)
  STEAM_API_KEY in .env  (catalog / game / reviews commands)
  ANTHROPIC_API_KEY in .env  (analyze command)
  AWS credentials        (queue commands — publishes to deployed SQS)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "library-layer"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "lambda-functions"))

# Commands that resolve config from .env.{environment} via for_environment().
# Skipping load_dotenv for these prevents dummy .env values from overriding
# real SSM paths that pydantic-settings would read from the env file.
_DEPLOYED_COMMANDS = {"spokes", "queue", "db", "batch", "dispatch", "logs", "matview-refresh"}
_cmd = sys.argv[1] if len(sys.argv) >= 2 else ""

if _cmd not in _DEPLOYED_COMMANDS:
    # All local and analyze/seed commands read from .env
    load_dotenv(os.path.join(REPO_ROOT, ".env"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("LLM_MODEL__CHUNKING", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
os.environ.setdefault("LLM_MODEL__SUMMARIZER", "us.anthropic.claude-sonnet-4-6")

if _cmd not in _DEPLOYED_COMMANDS and _cmd not in {"analyze", "seed"}:
    # Local-only commands: inject dummy infra config so SteamPulseConfig()
    # instantiates without real AWS. analyze/seed use real Bedrock creds.
    os.environ.setdefault("DB_SECRET_NAME", "local")
    os.environ.setdefault("STEAM_API_KEY_SECRET_NAME", "local")
    os.environ.setdefault("SFN_PARAM_NAME", "local")
    os.environ.setdefault("STEP_FUNCTIONS_PARAM_NAME", "local")
    os.environ.setdefault("APP_CRAWL_QUEUE_PARAM_NAME", "local")
    os.environ.setdefault("REVIEW_CRAWL_QUEUE_PARAM_NAME", "local")
    os.environ.setdefault("ASSETS_BUCKET_PARAM_NAME", "local")
    os.environ.setdefault("GAME_EVENTS_TOPIC_PARAM_NAME", "local")
    os.environ.setdefault("CONTENT_EVENTS_TOPIC_PARAM_NAME", "local")
    os.environ.setdefault("SYSTEM_EVENTS_TOPIC_PARAM_NAME", "local")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")

from datetime import UTC

from library_layer.config import SteamPulseConfig  # noqa: E402
from library_layer.repositories.catalog_repo import CatalogRepository  # noqa: E402
from library_layer.repositories.game_repo import GameRepository  # noqa: E402
from library_layer.repositories.report_repo import ReportRepository  # noqa: E402
from library_layer.repositories.review_repo import ReviewRepository  # noqa: E402
from library_layer.repositories.tag_repo import TagRepository  # noqa: E402
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

    def _info(msg: str) -> None:
        _con.print(f"[cyan]▶[/cyan] {msg}")

    def _ok(msg: str) -> None:
        _con.print(f"[green]✓[/green] {msg}")

    def _warn(msg: str) -> None:
        _con.print(f"[yellow]⚠[/yellow]  {msg}")

    def _err(msg: str) -> None:
        _con.print(f"[red]✗[/red] {msg}")

except ImportError:

    def _table(headers: list[str], rows: list[list[str]]) -> None:
        print("  ".join(f"{h:<20}" for h in headers))
        for row in rows:
            print("  ".join(f"{c:<20}" for c in row))

    def _info(msg: str) -> None:
        print(f"▶ {msg}")

    def _ok(msg: str) -> None:
        print(f"✓ {msg}")

    def _warn(msg: str) -> None:
        print(f"⚠  {msg}")

    def _err(msg: str) -> None:
        print(f"✗ {msg}", file=sys.stderr)


DB_URL = os.getenv("DATABASE_URL", "postgresql://steampulse:dev@127.0.0.1:5432/steampulse")
_REVIEW_ELIGIBILITY_THRESHOLD = int(os.getenv("REVIEW_ELIGIBILITY_THRESHOLD", "50"))

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
    get_conn = lambda: conn  # noqa: E731
    return (
        conn,
        GameRepository(get_conn),
        CatalogRepository(get_conn),
        ReportRepository(get_conn),
        ReviewRepository(get_conn),
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
    http_client: httpx.Client,
) -> CrawlService:
    import boto3

    real_aws = _has_real_aws_credentials()
    get_conn = lambda: conn  # noqa: E731
    return CrawlService(
        game_repo=GameRepository(get_conn),
        review_repo=ReviewRepository(get_conn),
        catalog_repo=CatalogRepository(get_conn),
        tag_repo=TagRepository(get_conn),
        steam=DirectSteamSource(http_client),
        sns_client=_NoOpSnsClient(),
        config=SteamPulseConfig(),
        game_events_topic_arn="noop",
        content_events_topic_arn="noop",
        sqs_client=None,
        review_queue_url="",
        sfn_arn=None,
        sfn_client=None,
        s3_client=boto3.client("s3") if real_aws else None,
        archive_bucket=os.getenv("ARCHIVE_BUCKET", "steampulse-raw-archive-v1")
        if real_aws
        else None,
    )


def _fetch_app_list(client: httpx.Client, api_key: str | None = None) -> list[dict]:
    """Return [{appid, name, steam_last_modified, price_change_number}, ...] from IStoreService/GetAppList (cursor-paginated)."""
    from datetime import datetime

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
        apps.extend(
            {
                "appid": a["appid"],
                "name": a.get("name", ""),
                "steam_last_modified": (
                    datetime.fromtimestamp(a["last_modified"], tz=UTC)
                    if a.get("last_modified")
                    else None
                ),
                "price_change_number": a.get("price_change_number"),
            }
            for a in batch
        )
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
            [
                "metadata",
                f"{meta.get('pending', 0):,}",
                f"{meta.get('done', 0):,}",
                f"{meta.get('failed', 0):,}",
                f"{total:,}",
            ],
            [
                "reviews",
                f"{review.get('pending', 0):,}",
                f"{review.get('done', 0):,}",
                f"{review.get('failed', 0):,}",
                "—",
            ],
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
        ["appid", str(appid)],
        ["meta_status", catalog.meta_status or "—"],
        ["review_status", catalog.review_status or "—"],
    ]
    if game:
        rows += [
            ["name", game.name or "—"],
            ["slug", game.slug or "—"],
            ["steam reviews", f"{game.review_count:,}" if game.review_count else "—"],
            ["price", f"${game.price_usd:.2f}" if game.price_usd else "—"],
        ]
    rows.append(["reviews in DB", f"{reviews_in_db:,}"])
    if report:
        report_data = report.report_json if isinstance(report.report_json, dict) else {}
        rows += [
            ["last_analyzed", str(report.last_analyzed)],
            ["sentiment", report_data.get("overall_sentiment") or "—"],
        ]
    else:
        rows.append(["report", "none"])

    _table(["Field", "Value"], rows)


# ── shared crawl machinery ────────────────────────────────────────────────────


def _crawl_one(appid: int, phase: str, client: httpx.Client) -> str:
    c = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        svc = _build_crawl_service(c, client)
        if phase == "metadata":
            result = svc.crawl_app(appid)
            return "done" if result else "skipped"
        else:
            n = svc.crawl_reviews(appid)
            if n >= 0:
                CatalogRepository(lambda: c).mark_reviews_complete(appid)
                return "done"
            return "skipped"
    except Exception as exc:
        _warn(f"appid={appid} error: {exc}")
        return "failed"
    finally:
        c.close()


def _crawl_specific(appids: list[int], phase: str) -> None:
    client = httpx.Client(timeout=30.0)
    for appid in appids:
        c = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            svc = _build_crawl_service(c, client)
            if phase == "metadata":
                result = svc.crawl_app(appid)
                _ok(f"appid={appid} metadata={'done' if result else 'skipped'}")
            else:
                n = svc.crawl_reviews(appid)
                _ok(f"appid={appid} reviews={n}")
        except Exception as exc:
            _err(f"appid={appid} failed: {exc}")
        finally:
            c.close()
    client.close()


def _crawl_bulk(phase: str, fetch_fn: object, concurrency: int) -> None:
    """Process all pending items for a phase with thread-pool concurrency."""
    batch_size = concurrency * 4
    n_done = n_skipped = n_failed = 0
    start = time.monotonic()
    last_log = start

    # Fetch total pending count upfront for ETA calculation
    total_pending = len(fetch_fn(999_999))
    _info(f"[{phase}] starting — {total_pending:,} items pending")

    client = httpx.Client(timeout=30.0)
    try:
        while True:
            batch = fetch_fn(batch_size)
            if not batch:
                break
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_crawl_one, a, phase, client): a for a in batch}
                for future in as_completed(futures):
                    r = future.result()
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
                eta_str = f"{eta_min / 60:.1f}h" if eta_min >= 60 else f"{eta_min:.0f}m"
                pct = processed / total_pending * 100 if total_pending else 0
                _info(
                    f"[{phase}] {processed:,}/{total_pending:,} ({pct:.1f}%) | "
                    f"done={n_done:,} skipped={n_skipped:,} failed={n_failed:,} | "
                    f"{rate:.0f}/min | ETA {eta_str}"
                )
                last_log = now
    finally:
        client.close()

    elapsed = time.monotonic() - start
    _ok(
        f"[{phase}] done={n_done:,} skipped={n_skipped:,} failed={n_failed:,} in {elapsed / 60:.1f} min"
    )


# ── fetch helpers for bulk modes ─────────────────────────────────────────────


def _pending_meta(n: int) -> list[int]:
    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        entries = catalog_repo.find_pending_meta(limit=n)
    finally:
        conn.close()
    return [e.appid for e in entries]


def _due_meta(n: int, config: SteamPulseConfig | None = None) -> list[int]:
    """Return appids whose metadata refresh slot has come due (dry-run).

    Pass `config` when calling from a deployed-command code path (`queue …`);
    in those contexts `.env` isn't auto-loaded, so constructing `SteamPulseConfig()`
    implicitly would fail on missing required fields. For local Python helpers
    the default `SteamPulseConfig()` works because module init sets dummy env vars.
    """
    config = config or SteamPulseConfig()
    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        entries = catalog_repo.find_due_meta(limit=n, config=config)
    finally:
        conn.close()
    return [e.appid for e in entries]


def _due_reviews(n: int, config: SteamPulseConfig | None = None) -> list[int]:
    """Return appids whose review refresh slot has come due (dry-run)."""
    config = config or SteamPulseConfig()
    conn, _, catalog_repo, _, _ = _get_repos()
    try:
        entries = catalog_repo.find_due_reviews(limit=n, config=config)
    finally:
        conn.close()
    return [e.appid for e in entries]


def refresh_meta_once(limit: int | None = None) -> list[int]:
    """Operator dry-run: appids the hourly meta-refresh dispatcher would enqueue.

    Defaults `limit` to `SteamPulseConfig.REFRESH_META_BATCH_LIMIT` so local
    dry-runs stay aligned with the deployed EventBridge rule payload.

    Use from a shell to sanity-check the tier query before flipping the
    EventBridge rule to enabled=True:
        poetry run python -c "from scripts.sp import refresh_meta_once; print(refresh_meta_once(limit=5))"
    """
    if limit is None:
        limit = SteamPulseConfig().REFRESH_META_BATCH_LIMIT
    return _due_meta(limit)


def refresh_reviews_once(limit: int | None = None) -> list[int]:
    """Operator dry-run: appids the hourly review-refresh dispatcher would enqueue."""
    if limit is None:
        limit = SteamPulseConfig().REFRESH_REVIEWS_BATCH_LIMIT
    return _due_reviews(limit)


def _eligible_reviews(n: int) -> list[int]:
    """Return appids that genuinely need review crawling, newest first.

    A game is skipped if it already has ≥95% of its target reviews stored
    (target = min(review_count_english, 2000)).  This avoids queueing thousands
    of Lambda invocations for games that are already complete or nearly complete
    but never had reviews_completed_at set (e.g. killed mid-pagination).
    """
    with psycopg2.connect(DB_URL) as c, c.cursor() as cur:
        cur.execute(
            """SELECT ac.appid FROM app_catalog ac
               JOIN games g ON g.appid = ac.appid
               LEFT JOIN mv_review_counts rc ON rc.appid = ac.appid
               WHERE ac.meta_status = 'done'
                 AND ac.reviews_completed_at IS NULL
                 AND g.coming_soon = false
                 AND g.review_count_english >= %s
                 AND g.release_date IS NOT NULL
                 AND COALESCE(rc.stored_count, 0) < LEAST(g.review_count_english, 2000) * 0.95
               ORDER BY g.release_date DESC NULLS LAST LIMIT %s""",
            (_REVIEW_ELIGIBILITY_THRESHOLD, n),
        )
        return [row[0] for row in cur.fetchall()]


def _all_games(n: int) -> list[int]:
    """Return all game appids ordered by review count (most reviewed first)."""
    with psycopg2.connect(DB_URL) as c, c.cursor() as cur:
        cur.execute(
            """SELECT appid FROM games
               WHERE type = 'game'
               ORDER BY review_count DESC NULLS LAST LIMIT %s""",
            (n,),
        )
        return [row[0] for row in cur.fetchall()]


def _ready_for_analysis(n: int = 1000) -> list[int]:
    with psycopg2.connect(DB_URL) as c, c.cursor() as cur:
        cur.execute(
            """SELECT g.appid FROM games g
               JOIN app_catalog ac ON ac.appid = g.appid
               WHERE ac.reviews_completed_at IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.appid = g.appid)
               ORDER BY g.review_count DESC NULLS LAST LIMIT %s""",
            (n,),
        )
        return [row[0] for row in cur.fetchall()]


# Auto-dispatch disabled — the matview-driven dispatch Lambda path is off.
# Batch analysis runs only via `scripts/trigger_batch_analysis.py` (or
# `sp.py batch <appids>`). Kept as comments in case we re-enable it later.
# def _resolve_dispatch_fn_name(env: str) -> str:
#     """Resolve the dispatch Lambda function name from SSM."""
#     import boto3
#
#     ssm = boto3.client("ssm", region_name="us-west-2")
#     return ssm.get_parameter(Name=f"/steampulse/{env}/batch/dispatch-fn-name")["Parameter"]["Value"]


# ── subcommand implementations ────────────────────────────────────────────────


def cmd_game_crawl(appids: list[int], all_pending: bool, concurrency: int) -> None:
    if all_pending:
        _crawl_bulk("metadata", _pending_meta, concurrency)
    else:
        _crawl_specific(appids, "metadata")


def cmd_reviews_crawl(appids: list[int], eligible: bool, concurrency: int) -> None:
    if eligible:
        _crawl_bulk("reviews", _eligible_reviews, concurrency)
    else:
        _crawl_specific(appids, "reviews")


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
    _crawl_specific(appids, "metadata")
    _info("Stage 2/3 — review crawl")
    _crawl_specific(appids, "reviews")
    _info("Stage 3/3 — LLM analysis")
    cmd_analyze(appids, ready=False)
    _ok("Seed complete")


# ── Queue commands (publish to deployed SQS) ──────────────────────────────────


def _resolve_queue_url(param_name: str) -> str:
    """Resolve an SQS queue URL from SSM parameter store."""
    import boto3

    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=param_name)
    return resp["Parameter"]["Value"]


def _send_sqs_batch(queue_url: str, messages: list[dict]) -> int:
    """Send messages to SQS in batches of 10. Returns count successfully sent."""
    import boto3

    sqs = boto3.client("sqs")
    sent = 0
    for i in range(0, len(messages), 10):
        batch = messages[i : i + 10]
        entries = [{"Id": str(j), "MessageBody": json.dumps(msg)} for j, msg in enumerate(batch)]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        failed = resp.get("Failed", [])
        if failed:
            for f in failed:
                _warn(f"SQS send failed for Id={f['Id']}: [{f['Code']}] {f['Message']}")
            raise RuntimeError(f"{len(failed)} message(s) failed to enqueue in this batch")
        sent += len(batch)
    return sent


def cmd_queue(
    task: str,
    appids: list[int],
    dry_run: bool,
    env: str = "staging",
    max_reviews: int | None = None,
    source: str | None = None,
) -> None:
    """Publish appids to deployed SQS queues for the spoke pipeline to process.

    `source` is written into each message body (e.g. "refresh" for tier-driven
    refresh). The primary crawler's dispatch handler logs this so dashboards
    can attribute queue volume to new-game onboarding vs tiered refresh.
    """
    config = SteamPulseConfig.for_environment(env)

    if task in ("metadata", "tags"):
        param = config.APP_CRAWL_QUEUE_PARAM_NAME
        label = "app-crawl-queue"
    else:
        param = config.REVIEW_CRAWL_QUEUE_PARAM_NAME
        label = "review-crawl-queue"

    _info(f"Publishing {len(appids)} appids → {label}")
    if max_reviews is not None:
        _info(f"  max_reviews={max_reviews}")
    if source is not None:
        _info(f"  source={source}")

    def _make_body(appid: int) -> dict:
        body: dict = {"appid": appid, "task": task}
        if task == "reviews" and max_reviews is not None:
            body["target"] = max_reviews
        if source is not None:
            body["source"] = source
        return body

    if dry_run:
        for appid in appids[:10]:
            _info(f"  {_make_body(appid)}")
        if len(appids) > 10:
            _info(f"  ... and {len(appids) - 10} more")
        _warn(f"[dry-run] Would publish {len(appids)} messages to {label}")
        return

    _info(f"Resolving queue URL from SSM: {param}")
    queue_url = _resolve_queue_url(param)
    _info(f"Queue: {queue_url}")

    messages = [_make_body(appid) for appid in appids]
    sent = _send_sqs_batch(queue_url, messages)
    _ok(f"Published {sent} {task} messages to {label}")


# ── Batch analysis ────────────────────────────────────────────────────────────


def cmd_batch(
    appids: list[int],
    concurrency: int,
    dry_run: bool,
    watch: bool,
    env: str,
) -> None:
    """Start a batch analysis orchestrator execution (fan-out over appids)."""
    import boto3

    payload = {"appids": appids, "max_concurrency": concurrency, "start_at": "chunk"}

    _info(f"Batch analysis → {env}")
    _info(f"  Appids:      {len(appids)}: {appids}")
    _info(f"  Concurrency: {concurrency}")

    if dry_run:
        _warn(f"[dry-run] Would start orchestrator with: {json.dumps(payload)}")
        return

    ssm = boto3.client("ssm")
    sfn_arn = ssm.get_parameter(Name=f"/steampulse/{env}/batch/orchestrator-sfn-arn")["Parameter"][
        "Value"
    ]
    _info(f"  SFN: {sfn_arn}")

    sfn = boto3.client("stepfunctions")
    resp = sfn.start_execution(stateMachineArn=sfn_arn, input=json.dumps(payload))
    execution_arn = resp["executionArn"]
    region = sfn_arn.split(":")[3]
    console_url = (
        f"https://{region}.console.aws.amazon.com/states/home"
        f"?region={region}#/executions/details/{execution_arn}"
    )

    _ok("Execution started")
    _info(f"  ARN:     {execution_arn}")
    _info(f"  Console: {console_url}")

    if not watch:
        return

    _info("Watching (Ctrl+C to stop)...")
    try:
        while True:
            time.sleep(30)
            desc = sfn.describe_execution(executionArn=execution_arn)
            status = desc["status"]
            _info(f"  [{time.strftime('%H:%M:%S')}] {status}")
            if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
                if status == "SUCCEEDED":
                    _ok("Execution succeeded")
                else:
                    _err(f"Execution {status.lower()}")
                    if desc.get("cause"):
                        _err(f"  Cause: {desc['cause']}")
                    if desc.get("error"):
                        _err(f"  Error: {desc['error']}")
                break
    except KeyboardInterrupt:
        _info("Stopped watching (execution still running)")


# Auto-dispatch disabled — see note on _resolve_dispatch_fn_name above.
# def cmd_dispatch(
#     batch_size: int | None,
#     dry_run: bool,
#     watch: bool,
#     env: str,
# ) -> None:
#     """Invoke the deployed dispatch Lambda to start the next batch."""
#     fn_name = _resolve_dispatch_fn_name(env)
#     payload: dict[str, object] = {"dry_run": dry_run}
#     if batch_size is not None:
#         payload["batch_size"] = batch_size
#
#     _info(f"Invoking {fn_name} (batch_size={batch_size or 'default'}, dry_run={dry_run})")
#     result = _invoke_lambda(fn_name, payload)
#
#     dispatched = result.get("dispatched", 0)
#     appids = result.get("appids", [])
#
#     if not appids:
#         _warn("No candidates — matview is empty or fully analyzed")
#         return
#
#     if dry_run:
#         for i, appid in enumerate(appids, 1):
#             _info(f"  {i:>4}. {appid}")
#         _warn(f"[dry-run] Would dispatch {dispatched} games to orchestrator")
#         return
#
#     execution_arn = result.get("execution_arn", "")
#     _ok(f"Dispatched {dispatched} games")
#     _info(f"  Execution ARN: {execution_arn}")
#
#     if not watch or not execution_arn:
#         return
#
#     import boto3
#
#     sfn = boto3.client("stepfunctions")
#     _info("Watching (Ctrl+C to stop)...")
#     try:
#         while True:
#             time.sleep(30)
#             desc = sfn.describe_execution(executionArn=execution_arn)
#             status = desc["status"]
#             _info(f"  [{time.strftime('%H:%M:%S')}] {status}")
#             if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
#                 if status == "SUCCEEDED":
#                     _ok("Execution succeeded")
#                 else:
#                     _err(f"Execution {status.lower()}")
#                 break
#     except KeyboardInterrupt:
#         _info("Stopped watching (execution still running)")


# ── matview-refresh (start the Step Functions state machine) ─────────────────


def cmd_matview_refresh(env: str, force: bool) -> None:
    """Start a matview-refresh Step Functions execution."""
    import boto3

    env_config = SteamPulseConfig.for_environment(env)
    ssm = boto3.client("ssm", region_name="us-west-2")
    arn = ssm.get_parameter(Name=env_config.MATVIEW_REFRESH_SFN_ARN_PARAM_NAME)[
        "Parameter"
    ]["Value"]
    sfn = boto3.client("stepfunctions", region_name="us-west-2")
    resp = sfn.start_execution(
        stateMachineArn=arn,
        input=json.dumps({"force": force, "trigger_event": ""}),
    )
    execution_arn = resp["executionArn"]
    _ok(f"Started matview-refresh execution (force={force})")
    _info(f"  Execution ARN: {execution_arn}")
    # us-west-2 console URL mirrors the region the ARN lives in.
    region = arn.split(":")[3]
    console_url = (
        f"https://{region}.console.aws.amazon.com/states/home?region={region}"
        f"#/v2/executions/details/{execution_arn}"
    )
    _info(f"  Console: {console_url}")


# ── DB ───────────────────────────────────────────────────────────────────────


def _resolve_admin_fn_name(env: str) -> str:
    """Resolve Admin Lambda name from SSM."""
    import boto3

    ssm = boto3.client("ssm", region_name="us-west-2")
    resp = ssm.get_parameter(Name=f"/steampulse/{env}/compute/admin-fn-name")
    return resp["Parameter"]["Value"]


def _invoke_lambda(fn_name: str, payload: dict) -> dict:
    """Invoke a Lambda synchronously and return the parsed response."""
    import boto3

    client = boto3.client("lambda", region_name="us-west-2")
    resp = client.invoke(
        FunctionName=fn_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    result = json.loads(resp["Payload"].read())
    if resp.get("FunctionError"):
        error_msg = result.get("errorMessage", "Unknown error")
        raise RuntimeError(f"Lambda error: {error_msg}")
    return result


def _invoke_admin(env: str, payload: dict) -> dict:
    """Resolve and invoke the Admin Lambda for the given environment."""
    fn_name = _resolve_admin_fn_name(env)
    _info(f"Invoking {fn_name}...")
    return _invoke_lambda(fn_name, payload)


def cmd_db_init(env: str) -> None:
    """Create all tables in the deployed RDS database."""
    result = _invoke_admin(env, {"action": "init"})
    _ok(result.get("message", "done"))


def cmd_db_status(env: str) -> None:
    """Show tables and row counts in the deployed RDS database."""
    result = _invoke_admin(env, {"action": "status"})
    tables = result.get("tables", [])
    if not tables:
        _warn("No tables found")
        return
    rows = [[t["table"], f"{t['rows']:,}"] for t in tables]
    _table(["Table", "Rows"], rows)


def cmd_db_query(env: str, sql: str) -> None:
    """Run a read-only SQL query against the deployed RDS database."""
    result = _invoke_admin(env, {"action": "query", "sql": sql})
    if result.get("status") == "error":
        _err(result.get("message", "Unknown error"))
        return
    columns = result.get("columns", [])
    query_rows = result.get("rows", [])
    count = result.get("count", 0)
    if not query_rows:
        _warn("No rows returned")
        return
    display_rows = [[str(row.get(c, "")) for c in columns] for row in query_rows]
    _table(columns, display_rows)
    if result.get("truncated"):
        _warn(f"Showing first {count:,} rows — add LIMIT to your query for full control")
    else:
        _info(f"{count:,} row(s)")


# ── Spokes ───────────────────────────────────────────────────────────────────


def cmd_spokes_status(env: str) -> None:
    """Show deployed spoke Lambdas across all regions."""
    import boto3

    config = SteamPulseConfig.for_environment(env)
    regions = config.spoke_region_list
    if not regions:
        _warn(f"No spoke regions configured for {env} (SPOKE_REGIONS is empty)")
        return

    _info(f"Checking spokes for {env}: {', '.join(regions)}")
    rows: list[list[str]] = []

    for region in regions:
        fn_name = f"steampulse-spoke-crawler-{region}-{env}"
        lambda_client = boto3.client("lambda", region_name=region)
        try:
            fn = lambda_client.get_function(FunctionName=fn_name)
            cfg = fn["Configuration"]
            state = cfg.get("State", "?")
            last_modified = cfg.get("LastModified", "?")
            memory = str(cfg.get("MemorySize", "?"))
            timeout = str(cfg.get("Timeout", "?"))
            runtime = cfg.get("Runtime", "?")
            reserved = str(fn.get("Concurrency", {}).get("ReservedConcurrentExecutions", "—"))
            rows.append([region, fn_name, state, runtime, memory, timeout, reserved, last_modified])
        except lambda_client.exceptions.ResourceNotFoundException:
            rows.append([region, fn_name, "NOT FOUND", "—", "—", "—", "—", "—"])
        except Exception as exc:
            rows.append([region, fn_name, f"ERROR: {exc}", "—", "—", "—", "—", "—"])

    _table(
        [
            "Region",
            "Function",
            "State",
            "Runtime",
            "Memory",
            "Timeout",
            "Concurrency",
            "Last Modified",
        ],
        rows,
    )

    # Check SSM spoke status params — each spoke writes to its own region
    ssm_rows: list[list[str]] = []
    for region in regions:
        ssm_client = boto3.client("ssm", region_name=region)
        try:
            resp = ssm_client.get_parameters_by_path(
                Path=f"/steampulse/{env}/spokes/",
                Recursive=True,
            )
            for p in resp.get("Parameters", []):
                ssm_rows.append([region, p["Name"], p["Value"]])
        except Exception as exc:
            ssm_rows.append([region, "ERROR", str(exc)])
    if ssm_rows:
        _info("SSM spoke parameters:")
        _table(["Region", "Parameter", "Value"], ssm_rows)


# ── CLI wiring ────────────────────────────────────────────────────────────────


_SPOKE_REGIONS = [
    "us-west-2",
    "us-east-1",
    "us-east-2",
    "ca-central-1",
    "eu-west-1",
    "eu-central-1",
    "eu-north-1",
    "ap-south-1",
    "ap-southeast-1",
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-southeast-2",
]


def cmd_logs_errors(env: str, minutes: int, pattern: str, region: str | None) -> None:
    """Query spoke log groups across all regions for errors/warnings."""
    import boto3

    regions = [region] if region else _SPOKE_REGIONS
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - minutes * 60 * 1000

    all_rows: list[tuple[str, str]] = []  # (region, message)

    def _query_region(r: str) -> list[tuple[str, str]]:
        client = boto3.client("logs", region_name=r)
        log_group = f"/steampulse/{env}/spoke/{r}"
        try:
            rows: list[tuple[str, str]] = []
            next_token: str | None = None
            for _ in range(20):
                kwargs: dict = {
                    "logGroupName": log_group,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "filterPattern": pattern,
                    "limit": 100,
                }
                if next_token:
                    kwargs["nextToken"] = next_token
                resp = client.filter_log_events(**kwargs)
                rows.extend((r, e["message"]) for e in resp.get("events", []))
                prev_token = next_token
                next_token = resp.get("nextToken")
                if not next_token or next_token == prev_token:
                    break
            return rows
        except client.exceptions.ResourceNotFoundException:
            return []
        except Exception as exc:
            return [(r, f"ERROR querying logs: {exc}")]

    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(_query_region, r): r for r in regions}
        for f in as_completed(futures):
            all_rows.extend(f.result())

    if not all_rows:
        print(f"No matching events in the last {minutes} minutes across {len(regions)} region(s).")
        return

    all_rows.sort(key=lambda x: x[0])
    for r, msg in all_rows:
        try:
            data = json.loads(msg)
            ts = data.get("timestamp", "")
            level = data.get("level", "")
            message = data.get("message", msg)
            appid = data.get("appid", "")
            error = data.get("error", "")
            parts = [
                p for p in [ts, r, level, f"appid={appid}" if appid else "", message, error] if p
            ]
            print("  ".join(parts))
        except (json.JSONDecodeError, AttributeError):
            print(f"[{r}] {msg.strip()}")


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
    gc.add_argument("appids", type=int, nargs="*", metavar="appid", help="Specific appids to crawl")
    gc.add_argument(
        "--all",
        dest="all_pending",
        action="store_true",
        help="Crawl all pending entries in app_catalog",
    )
    gc.add_argument("-c", "--concurrency", type=int, default=1, metavar="N")

    # ── reviews
    rv = sub.add_parser("reviews", help="Review crawl operations")
    rv_sub = rv.add_subparsers(dest="reviews_cmd", required=True)

    rc = rv_sub.add_parser("crawl", help="Crawl Steam reviews")
    rc.add_argument("appids", type=int, nargs="*", metavar="appid")
    rc.add_argument(
        "--eligible",
        action="store_true",
        help="Crawl all games with metadata done and reviews pending",
    )
    rc.add_argument("-c", "--concurrency", type=int, default=1, metavar="N")

    # ── analyze
    az = sub.add_parser("analyze", help="Run LLM analysis (writes to reports table)")
    az.add_argument("appids", type=int, nargs="*", metavar="appid")
    az.add_argument(
        "--ready", action="store_true", help="Analyze all games that have reviews but no report yet"
    )

    # ── db
    db = sub.add_parser("db", help="Database operations on deployed RDS")
    db.add_argument(
        "--env",
        default="staging",
        choices=["staging", "production"],
        help="Environment (default: staging)",
    )
    db_sub = db.add_subparsers(dest="db_cmd", required=True)
    db_sub.add_parser("init", help="Create all tables (idempotent)")
    db_sub.add_parser("status", help="Show tables and row counts")
    db_q = db_sub.add_parser("query", help="Run a read-only SQL query")
    db_q.add_argument("sql", help="SQL query to execute")

    # ── seed
    sd = sub.add_parser("seed", help="Full pipeline: metadata → reviews → analysis")
    sd.add_argument(
        "appids",
        type=int,
        nargs="*",
        metavar="appid",
        help=f"Appids to seed (default: {DEFAULT_SEED_APPIDS})",
    )

    # ── batch
    ba = sub.add_parser("batch", help="Start a batch analysis orchestrator execution")
    ba.add_argument("appids", type=int, nargs="+", metavar="appid", help="Appids to analyze")
    ba.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Max concurrent per-game executions (default: 20)",
    )
    ba.add_argument(
        "--env",
        default="staging",
        choices=["staging", "production"],
        help="Environment (default: staging)",
    )
    ba.add_argument(
        "--dry-run", action="store_true", help="Print the payload without starting an execution"
    )
    ba.add_argument(
        "--watch",
        action="store_true",
        help="Poll execution status every 30s until complete (Ctrl+C to stop)",
    )

    # ── dispatch subcommand removed — auto-dispatch is disabled; use `sp.py batch` instead.
    # di = sub.add_parser("dispatch", help="Dispatch next batch from analysis candidate list")
    # di.add_argument(
    #     "--env",
    #     default="staging",
    #     choices=["staging", "production"],
    #     help="Environment (default: staging)",
    # )
    # di.add_argument(
    #     "--batch-size",
    #     type=int,
    #     default=None,
    #     metavar="N",
    #     help="Number of games to dispatch (omit to use the deployed default)",
    # )
    # di.add_argument(
    #     "--dry-run",
    #     action="store_true",
    #     help="Show candidates without starting an execution",
    # )
    # di.add_argument(
    #     "--watch",
    #     action="store_true",
    #     help="Poll execution status every 30s until complete (Ctrl+C to stop)",
    # )

    # ── matview-refresh (start the SFN directly)
    mr = sub.add_parser(
        "matview-refresh",
        help="Start a matview-refresh Step Functions execution",
    )
    mr.add_argument(
        "--env",
        default="staging",
        choices=["staging", "production"],
        help="Environment (default: staging)",
    )
    mr.add_argument(
        "--force",
        action="store_true",
        help="Bypass the 5-min debounce (Start step normally skips recent refreshes)",
    )

    # ── spokes
    sp = sub.add_parser("spokes", help="Spoke Lambda status across regions")
    sp_sub = sp.add_subparsers(dest="spokes_cmd", required=True)
    ss = sp_sub.add_parser("status", help="Show deployed spoke Lambdas")
    ss.add_argument(
        "--env",
        default="staging",
        choices=["staging", "production"],
        help="Environment to check (default: staging)",
    )

    # ── queue (publish to deployed SQS)
    qu = sub.add_parser("queue", help="Publish appids to deployed SQS queues")
    qu.add_argument(
        "--env",
        default="staging",
        choices=["staging", "production"],
        help="Environment to publish to (default: staging)",
    )
    qu_sub = qu.add_subparsers(dest="queue_cmd", required=True)

    qm = qu_sub.add_parser("metadata", help="Publish to app-crawl queue")
    qm.add_argument("appids", type=int, nargs="*", metavar="appid")
    qm.add_argument(
        "--all",
        dest="all_pending",
        action="store_true",
        help="Queue all pending entries from app_catalog",
    )
    qm.add_argument("--limit", type=int, metavar="N", help="Limit --all to N entries")
    qm.add_argument("--dry-run", action="store_true")

    qr = qu_sub.add_parser("reviews", help="Publish to review-crawl queue")
    qr.add_argument("appids", type=int, nargs="*", metavar="appid")
    qr.add_argument(
        "--eligible", action="store_true", help="Queue all review-eligible games from app_catalog"
    )
    qr.add_argument("--limit", type=int, metavar="N", help="Limit --eligible to N entries")
    qr.add_argument(
        "--max-reviews",
        type=int,
        metavar="N",
        help="Stop after fetching N reviews (default: fetch all)",
    )
    qr.add_argument("--dry-run", action="store_true")

    qt = qu_sub.add_parser("tags", help="Publish to app-crawl queue for Steam tag crawl")
    qt.add_argument("appids", type=int, nargs="*", metavar="appid")
    qt.add_argument(
        "--all", dest="all_games", action="store_true", help="Queue all games for tag backfill"
    )
    qt.add_argument("--limit", type=int, metavar="N", help="Limit --all to N entries")
    qt.add_argument("--dry-run", action="store_true")

    # Argparse defaults are literals, not SteamPulseConfig() lookups, because
    # this parser is also built for deployed commands (`queue`, `db`, `spokes`,
    # `logs`, `batch`, `dispatch`) where `.env` is not auto-loaded and module
    # init does NOT inject dummy infra defaults. Instantiating SteamPulseConfig
    # at parser-build time would crash even `--help`. The actual dispatcher
    # resolves env-specific defaults via SteamPulseConfig.for_environment(env).
    qrm = qu_sub.add_parser(
        "refresh-meta",
        help="Tier-due metadata refresh — enqueues metadata + tags tasks",
    )
    qrm.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max appids to enqueue (default: SteamPulseConfig.REFRESH_META_BATCH_LIMIT)",
    )
    qrm.add_argument("--dry-run", action="store_true")

    qrr = qu_sub.add_parser(
        "refresh-reviews",
        help="Tier-due review refresh — enqueues review-crawl tasks",
    )
    qrr.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max appids to enqueue (default: SteamPulseConfig.REFRESH_REVIEWS_BATCH_LIMIT)",
    )
    qrr.add_argument("--dry-run", action="store_true")

    # ── logs (query spoke logs across regions)
    lg = sub.add_parser("logs", help="Query spoke logs across all regions")
    lg.add_argument(
        "--env",
        default="staging",
        choices=["staging", "production"],
        help="Environment (default: staging)",
    )
    lg_sub = lg.add_subparsers(dest="logs_cmd", required=True)
    le = lg_sub.add_parser("errors", help="Show errors/warnings across all spoke regions")
    le.add_argument(
        "--minutes", type=int, default=60, metavar="N", help="Look back N minutes (default: 60)"
    )
    le.add_argument(
        "--pattern",
        default='?ERROR ?WARNING ?"Steam tag fetch error" ?"Steam reviews error"',
        help="CloudWatch filter pattern",
    )
    le.add_argument("--region", default=None, help="Limit to one region")

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

    elif args.cmd == "db":
        if args.db_cmd == "init":
            cmd_db_init(args.env)
        elif args.db_cmd == "status":
            cmd_db_status(args.env)
        elif args.db_cmd == "query":
            cmd_db_query(args.env, args.sql)

    elif args.cmd == "batch":
        cmd_batch(args.appids, args.concurrency, args.dry_run, args.watch, args.env)

    # elif args.cmd == "dispatch":
    #     cmd_dispatch(args.batch_size, args.dry_run, args.watch, args.env)

    elif args.cmd == "matview-refresh":
        cmd_matview_refresh(args.env, args.force)

    elif args.cmd == "spokes":
        if args.spokes_cmd == "status":
            cmd_spokes_status(args.env)

    elif args.cmd == "queue":
        appids = args.appids or []
        if args.queue_cmd == "metadata":
            if not appids and not args.all_pending:
                parser.error("queue metadata requires appids or --all")
            if args.all_pending:
                appids = _pending_meta(args.limit or 100_000)
            cmd_queue("metadata", appids, args.dry_run, args.env)
        elif args.queue_cmd == "reviews":
            if not appids and not args.eligible:
                parser.error("queue reviews requires appids or --eligible")
            if args.eligible:
                appids = _eligible_reviews(args.limit or 100_000)
            max_reviews = getattr(args, "max_reviews", None)
            cmd_queue("reviews", appids, args.dry_run, args.env, max_reviews=max_reviews)
        elif args.queue_cmd == "tags":
            if not appids and not args.all_games:
                parser.error("queue tags requires appids or --all")
            if args.all_games:
                appids = _all_games(args.limit or 200_000)
            cmd_queue("tags", appids, args.dry_run, args.env)
        elif args.queue_cmd == "refresh-meta":
            env_config = SteamPulseConfig.for_environment(args.env)
            limit = args.limit if args.limit is not None else env_config.REFRESH_META_BATCH_LIMIT
            due_ids = _due_meta(limit, config=env_config)
            _info(f"Found {len(due_ids)} tier-due appids for metadata refresh")
            cmd_queue("metadata", due_ids, args.dry_run, args.env, source="refresh")
            cmd_queue("tags", due_ids, args.dry_run, args.env, source="refresh")
        elif args.queue_cmd == "refresh-reviews":
            env_config = SteamPulseConfig.for_environment(args.env)
            limit = args.limit if args.limit is not None else env_config.REFRESH_REVIEWS_BATCH_LIMIT
            due_ids = _due_reviews(limit, config=env_config)
            _info(f"Found {len(due_ids)} tier-due appids for review refresh")
            cmd_queue("reviews", due_ids, args.dry_run, args.env, source="refresh")

    elif args.cmd == "logs":
        if args.logs_cmd == "errors":
            cmd_logs_errors(args.env, args.minutes, args.pattern, args.region)


if __name__ == "__main__":
    main()
