#!/usr/bin/env python3
"""CloudWatch Log Insights query runner for SteamPulse.

Runs named or raw queries against CloudWatch Log Insights and displays results
in a Rich-formatted table. Supports periodic tail mode.

Usage:
    poetry run python scripts/logs.py --env production --query errors
    poetry run python scripts/logs.py --env production --query catalog-refresh --since 6h
    poetry run python scripts/logs.py --env production --query ingest-throughput --tail 30
    poetry run python scripts/logs.py --env production --query all --log-group ingest --since 1h
    poetry run python scripts/logs.py --env production --list
    poetry run python scripts/logs.py --env production --raw "fields @timestamp, message | limit 20" --log-group crawler

Log groups (--log-group shorthand):
    crawler     /steampulse/{env}/crawler
    ingest      /steampulse/{env}/ingest
    api         /steampulse/{env}/api
    spoke       /aws/lambda/steampulse-spoke-crawler-*-{env}
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import boto3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

try:
    from rich import print as rprint
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box
except ImportError:
    print("ERROR: rich not installed. Run: poetry install")
    sys.exit(1)

console = Console()

REGION = os.getenv("AWS_DEFAULT_REGION", "us-west-2")

# ── Log Group Shorthands ───────────────────────────────────────────────────────

def log_group(name: str, env: str) -> str:
    groups = {
        "crawler": f"/steampulse/{env}/crawler",
        "ingest":  f"/steampulse/{env}/ingest",
        "api":     f"/steampulse/{env}/api",
        "spoke":   f"/steampulse/{env}/spoke",
        "admin":   f"/steampulse/{env}/admin",
        "analysis": f"/steampulse/{env}/analysis",
    }
    if name in groups:
        return groups[name]
    # Allow full path passthrough
    return name


# ── Prepared Queries ───────────────────────────────────────────────────────────

QUERIES: dict[str, dict[str, Any]] = {

    # ── Errors & Health ───────────────────────────────────────────────────────

    "errors": {
        "description": "All ERROR and WARNING log lines across all services",
        "log_group": "crawler",
        "extra_groups": ["ingest", "api"],
        "query": """
fields @timestamp, level, message, appid, error, @message
| filter level = "ERROR" or level = "WARNING"
    or @message like /[ERROR]/
    or @message like /HTTPStatusError|Traceback|Exception|timed out/
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "level", "message", "appid", "error"],
    },

    "errors-summary": {
        "description": "Error counts grouped by message type",
        "log_group": "crawler",
        "extra_groups": ["ingest", "api"],
        "query": """
fields level, message, error
| filter level = "ERROR" or level = "WARNING"
| stats count(*) as occurrences by level, message, error
| sort occurrences desc
""",
        "columns": ["level", "message", "error", "occurrences"],
    },

    "runtime-errors": {
        "description": "Raw Lambda runtime errors (unhandled exceptions, 403s, timeouts)",
        "log_group": "crawler",
        "extra_groups": ["ingest", "api"],
        "query": r"""
fields @timestamp, @message
| filter @message like /[ERROR]|HTTPStatusError|Traceback \(most recent|timed out|Task timed out/
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "@message"],
    },

    # ── Catalog Refresh ───────────────────────────────────────────────────────

    "catalog-refresh": {
        "description": "Catalog refresh runs — success/failure timeline",
        "log_group": "crawler",
        "query": """
fields @timestamp, message, new_games, queued, skipped, error
| filter message like /catalog.refresh|EventBridge trigger|GetAppList|403/
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "message", "new_games", "queued", "skipped"],
    },

    "catalog-refresh-stats": {
        "description": "Catalog refresh hourly success rate",
        "log_group": "crawler",
        "query": """
fields @timestamp, message
| filter message = "EventBridge trigger \u2014 running catalog refresh"
    or message = "catalog_refresh complete"
    or level = "ERROR"
| stats count(*) as count by bin(1h), message
| sort @timestamp desc
""",
        "columns": ["bin(1h)", "message", "count"],
    },

    "new-games": {
        "description": "Newly discovered games being queued for crawl",
        "log_group": "crawler",
        "query": """
fields @timestamp, message, appid, new_games, queued
| filter message = "catalog_refresh complete" or message like /game.discovered/
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "message", "new_games", "queued", "appid"],
    },

    # ── App Crawl (Metadata) ──────────────────────────────────────────────────

    "metadata-crawl": {
        "description": "App metadata crawl completions and failures",
        "log_group": "crawler",
        "query": """
fields @timestamp, message, appid, game_name, error
| filter message = "crawl_app complete"
    or message = "App fetched"
    or message = "Steam app_details error"
    or message = "App not found on Steam \u2014 skipping"
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "message", "appid", "game_name", "error"],
    },

    "stale-refresh": {
        "description": "Stale metadata re-crawl runs",
        "log_group": "crawler",
        "query": """
fields @timestamp, message, appids
| filter message = "stale_refresh complete" or message like /stale/
| sort @timestamp desc
| limit 30
""",
        "columns": ["@timestamp", "message", "appids"],
    },

    # ── Review Crawl ──────────────────────────────────────────────────────────

    "review-dispatch": {
        "description": "Review crawl tasks dispatched to spokes",
        "log_group": "crawler",
        "query": """
fields @timestamp, message, appid, queue_url
| filter message = "Dispatching to spoke queue"
    or message = "Skipping dispatch (budget exhausted)"
    or message = "crawl_reviews complete"
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "message", "appid", "queue_url"],
    },

    "review-completions": {
        "description": "Review crawl completions (exhausted / target_hit / early_stop)",
        "log_group": "ingest",
        "query": """
fields @timestamp, message, appid, reason, total, batch_count, target
| filter message = "Reviews complete"
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "appid", "reason", "total", "batch_count", "target"],
    },

    "review-throughput": {
        "description": "Reviews ingested per minute",
        "log_group": "ingest",
        "query": """
fields @timestamp, upserted
| filter message = "Reviews ingested"
| stats sum(upserted) as reviews_ingested, count(*) as batches by bin(5m)
| sort @timestamp desc
""",
        "columns": ["bin(5m)", "reviews_ingested", "batches"],
    },

    "review-failures": {
        "description": "Review crawl failures reported by spokes",
        "log_group": "ingest",
        "query": """
fields @timestamp, message, appid, error
| filter message = "Spoke reported review failure"
    or message = "Record processing failed"
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "message", "appid", "error"],
    },

    # ── Ingest (Spoke Results) ────────────────────────────────────────────────

    "ingest-throughput": {
        "description": "Ingest handler: records processed per minute",
        "log_group": "ingest",
        "query": """
fields @timestamp, task, success
| filter message = "Received spoke result"
| stats count(*) as processed,
        sum(success = 1) as succeeded,
        sum(success = 0) as failed
    by bin(5m)
| sort @timestamp desc
""",
        "columns": ["bin(5m)", "processed", "succeeded", "failed"],
    },

    "ingest-errors": {
        "description": "Ingest handler errors and spoke failures",
        "log_group": "ingest",
        "query": """
fields @timestamp, level, message, appid, task, error
| filter level = "ERROR" or level = "WARNING"
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "level", "message", "appid", "task", "error"],
    },

    "metadata-ingest": {
        "description": "Metadata records ingested from spokes",
        "log_group": "ingest",
        "query": """
fields @timestamp, message, appid
| filter message = "Ingested metadata"
    or message = "Spoke reported metadata failure"
    or message = "No tag data available"
    or message = "Tags upserted"
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "message", "appid"],
    },

    # ── Spoke Lambdas ─────────────────────────────────────────────────────────

    "spoke-activity": {
        "description": "Spoke Lambda activity (START/DONE per task type)",
        "log_group": "spoke",
        "query": """
fields @timestamp, message, appid, game_name, count, s3_key, spoke_region
| filter message like /^START|^DONE/
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "message", "appid", "game_name", "count"],
    },

    "spoke-errors": {
        "description": "Spoke Lambda warnings and errors",
        "log_group": "spoke",
        "query": """
fields @timestamp, level, message, appid, error
| filter level = "ERROR" or level = "WARNING"
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "level", "message", "appid", "error"],
    },

    # ── API ───────────────────────────────────────────────────────────────────

    "api-errors": {
        "description": "API 4xx/5xx errors",
        "log_group": "api",
        "query": """
fields @timestamp, level, message, appid, error
| filter level = "ERROR" or level = "WARNING"
| sort @timestamp desc
| limit 50
""",
        "columns": ["@timestamp", "level", "message", "appid", "error"],
    },

    "api-requests": {
        "description": "API request volume per endpoint per 5 minutes",
        "log_group": "api",
        "query": """
fields @timestamp, path, status_code
| filter ispresent(path)
| stats count(*) as requests by bin(5m), path
| sort @timestamp desc
""",
        "columns": ["bin(5m)", "path", "requests"],
    },

    # ── All ───────────────────────────────────────────────────────────────────

    "all": {
        "description": "All log lines from a single log group (use with --log-group)",
        "log_group": "crawler",
        "query": """
fields @timestamp, level, message, appid, @logStream
| sort @timestamp desc
| limit 100
""",
        "columns": ["@timestamp", "level", "message", "appid"],
    },
}


# ── Query Execution ────────────────────────────────────────────────────────────

def _since_seconds(since: str) -> int:
    units = {"m": 60, "h": 3600, "d": 86400}
    unit = since[-1]
    if unit not in units:
        raise ValueError(f"Invalid --since format: {since!r}. Use e.g. 30m, 6h, 1d")
    return int(since[:-1]) * units[unit]


def run_query(
    client: Any,
    log_groups: list[str],
    query_str: str,
    since_seconds: int,
) -> list[dict[str, str]]:
    end_time = int(datetime.now(timezone.utc).timestamp())
    start_time = end_time - since_seconds

    response = client.start_query(
        logGroupNames=log_groups,
        startTime=start_time,
        endTime=end_time,
        queryString=query_str.strip(),
    )
    query_id = response["queryId"]

    with console.status("[cyan]Running query...[/cyan]", spinner="dots"):
        while True:
            result = client.get_query_results(queryId=query_id)
            status = result["status"]
            if status in ("Complete", "Failed", "Cancelled", "Timeout"):
                break
            time.sleep(0.5)

    if result["status"] != "Complete":
        console.print(f"[red]Query {result['status']}[/red]")
        return []

    rows = []
    for record in result["results"]:
        row = {field["field"]: field["value"] for field in record}
        rows.append(row)
    return rows


# ── Display ────────────────────────────────────────────────────────────────────

def _level_style(level: str) -> str:
    return {
        "ERROR": "bold red",
        "WARNING": "yellow",
        "INFO": "green",
    }.get(level.upper(), "white")


def _format_ts(ts: str) -> str:
    try:
        # CloudWatch Insights returns @timestamp without timezone info (bare UTC string).
        # Explicitly mark as UTC before converting to local for display.
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%m-%d %H:%M:%S")
    except Exception:
        return ts[:19] if len(ts) >= 19 else ts


def render_table(
    rows: list[dict],
    columns: list[str],
    title: str,
    since: str,
    log_groups: list[str],
) -> None:
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
    )

    # Determine actual columns from result + requested columns
    all_keys = list(dict.fromkeys(columns + (list(rows[0].keys()) if rows else [])))
    # Only include columns that actually appear in results
    result_keys = set(rows[0].keys()) if rows else set()
    visible = [c for c in all_keys if c in result_keys]

    for col in visible:
        if col in ("@timestamp", "bin(1h)", "bin(5m)", "bin(1m)"):
            table.add_column(col.replace("@", "").replace("bin(", "").replace(")", ""), min_width=14, no_wrap=True)
        elif col == "level":
            table.add_column("level", width=8, no_wrap=True)
        elif col in ("appid",):
            table.add_column(col, width=8, no_wrap=True)
        elif col in ("occurrences", "count", "reviews_ingested", "batches", "processed", "succeeded", "failed", "requests"):
            table.add_column(col, justify="right", width=10)
        else:
            table.add_column(col)

    for row in rows:
        cells = []
        for col in visible:
            val = row.get(col, "")
            if col in ("@timestamp", "bin(1h)", "bin(5m)"):
                cells.append(Text(_format_ts(val), style="bright_black"))
            elif col == "level":
                cells.append(Text(val, style=_level_style(val)))
            elif col == "message":
                # Truncate long messages
                truncated = val[:80] + "…" if len(val) > 80 else val
                cells.append(Text(truncated))
            elif col == "error":
                cells.append(Text(val[:60] + "…" if len(val) > 60 else val, style="red" if val else ""))
            else:
                cells.append(val)
        table.add_row(*cells)

    subtitle = f"[bright_black]{len(rows)} rows · last {since} · {', '.join(lg.split('/')[-1] for lg in log_groups)}[/bright_black]"
    console.print()
    console.print(table)
    console.print(subtitle)


# ── Main ───────────────────────────────────────────────────────────────────────

def list_queries() -> None:
    table = Table(
        title="Available Prepared Queries",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
    )
    table.add_column("Name", style="bold yellow", no_wrap=True)
    table.add_column("Default Log Group", style="cyan", no_wrap=True)
    table.add_column("Description")

    for name, spec in sorted(QUERIES.items()):
        table.add_row(name, spec["log_group"], spec["description"])

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CloudWatch Log Insights query runner for SteamPulse"
    )
    parser.add_argument("--env", choices=["staging", "production"], default="production")
    parser.add_argument("--query", "-q", help="Named query to run (see --list)")
    parser.add_argument("--raw", help="Raw CloudWatch Insights query string")
    parser.add_argument(
        "--log-group", "-g",
        help="Log group shorthand or full path (overrides query default)",
    )
    parser.add_argument(
        "--since", "-s", default="1h",
        help="Lookback window: e.g. 30m, 6h, 1d (default: 1h)",
    )
    parser.add_argument(
        "--tail", "-t", type=int, metavar="SECONDS",
        help="Re-run query every N seconds (Ctrl-C to stop)",
    )
    parser.add_argument("--list", "-l", action="store_true", help="List available prepared queries")
    parser.add_argument("--region", default=REGION)

    args = parser.parse_args()

    if args.list:
        list_queries()
        return

    if not args.query and not args.raw:
        parser.error("Provide --query NAME or --raw 'query string'")

    client = boto3.client("logs", region_name=args.region)

    if args.raw:
        query_str = args.raw
        columns: list[str] = []
        title = "Raw Query"
        default_group = args.log_group or "crawler"
        extra_groups: list[str] = []
    else:
        if args.query not in QUERIES:
            console.print(f"[red]Unknown query: {args.query!r}[/red]. Use --list to see options.")
            sys.exit(1)
        spec = QUERIES[args.query]
        query_str = spec["query"]
        columns = spec.get("columns", [])
        title = f"{args.query}  —  {spec['description']}"
        default_group = spec["log_group"]
        extra_groups = spec.get("extra_groups", [])

    # Resolve log groups
    primary = log_group(args.log_group or default_group, args.env)
    all_groups = [primary] + [log_group(g, args.env) for g in extra_groups]

    since_sec = _since_seconds(args.since)

    def run_once() -> None:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        console.rule(f"[cyan]{title}[/cyan]  [bright_black]{ts}[/bright_black]")
        rows = run_query(client, all_groups, query_str, since_sec)
        if not rows:
            console.print("[yellow]No results.[/yellow]")
            return
        render_table(rows, columns, title, args.since, all_groups)

    if args.tail:
        try:
            while True:
                console.clear()
                run_once()
                console.print(f"\n[bright_black]Refreshing every {args.tail}s — Ctrl-C to stop[/bright_black]")
                time.sleep(args.tail)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped.[/yellow]")
    else:
        run_once()


if __name__ == "__main__":
    main()
