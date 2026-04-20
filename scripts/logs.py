#!/usr/bin/env python3
"""CloudWatch Log Insights query runner + batch status monitor for SteamPulse.

Runs named or raw queries against CloudWatch Log Insights and displays results
in a Rich-formatted table. Supports periodic tail mode.

Also supports --batches mode to query batch_executions directly from the DB.

Usage:
    poetry run python scripts/logs.py --env production --query errors
    poetry run python scripts/logs.py --env production --query catalog-refresh --since 6h
    poetry run python scripts/logs.py --env production --query ingest-throughput --tail 30
    poetry run python scripts/logs.py --env production --query all --log-group ingest --since 1h
    poetry run python scripts/logs.py --env production --list
    poetry run python scripts/logs.py --env production --raw "fields @timestamp, message | limit 20" --log-group crawler

    # Batch status (reads from DB — set DATABASE_URL for prod tunnel):
    poetry run python scripts/logs.py --batches
    poetry run python scripts/logs.py --batches --all
    poetry run python scripts/logs.py --batches --tail 30
    DATABASE_URL="host=localhost port=5433 dbname=production_steampulse user=postgres sslmode=verify-ca sslrootcert=./global-bundle.pem" \\
        poetry run python scripts/logs.py --batches --all --tail 15

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
from datetime import UTC, datetime
from typing import Any

import boto3

try:
    import psycopg2
    import psycopg2.extras

    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("ERROR: rich not installed. Run: poetry install")
    sys.exit(1)

console = Console()

REGION = os.getenv("AWS_DEFAULT_REGION", "us-west-2")

# ── Log Group Shorthands ───────────────────────────────────────────────────────


def log_group(name: str, env: str) -> str:
    groups = {
        "crawler": f"/steampulse/{env}/crawler",
        "ingest": f"/steampulse/{env}/ingest",
        "api": f"/steampulse/{env}/api",
        "spoke": f"/steampulse/{env}/spoke",
        "admin": f"/steampulse/{env}/admin",
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
    "refresh": {
        "description": "Tiered refresh dispatcher runs (metadata + reviews)",
        "log_group": "crawler",
        "query": """
fields @timestamp, message, enqueued, limit
| filter message = "refresh_meta complete"
    or message = "refresh_reviews complete"
    or message = "refresh_meta enqueued"
    or message = "refresh_reviews enqueued"
| sort @timestamp desc
| limit 30
""",
        "columns": ["@timestamp", "message", "enqueued", "limit"],
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


# ── Batch Status (DB) ─────────────────────────────────────────────────────────

_STATUS_STYLE: dict[str, str] = {
    "submitted": "bold blue",
    "running": "bold cyan",
    "completed": "bold green",
    "failed": "bold red",
}

_STATUS_ICON: dict[str, str] = {
    "submitted": "⏳",
    "running": "🔄",
    "completed": "✅",
    "failed": "❌",
}


def _elapsed(submitted_at: datetime, completed_at: datetime | None = None) -> str:
    end = completed_at or datetime.now(UTC)
    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=UTC)
    secs = int((end - submitted_at).total_seconds())
    if secs < 60:
        return f"{secs}s"
    elif secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    else:
        h, rem = divmod(secs, 3600)
        return f"{h}h {rem // 60}m"


def _fetch_batches(db_url: str, *, show_all: bool, limit: int) -> list[dict]:
    if not _PSYCOPG2_AVAILABLE:
        console.print("[red]psycopg2 not available. Run: poetry install[/red]")
        sys.exit(1)

    if "host=" in db_url or db_url.startswith("postgresql"):
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        conn = psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)

    status_filter = "" if show_all else "WHERE be.status IN ('submitted', 'running')"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                be.id,
                be.appid,
                g.name          AS game_name,
                be.phase,
                be.backend,
                be.status,
                be.request_count,
                be.succeeded_count,
                be.failed_count,
                be.estimated_cost_usd,
                be.input_tokens,
                be.output_tokens,
                be.submitted_at,
                be.completed_at,
                be.failure_reason,
                be.batch_id,
                be.execution_id
            FROM batch_executions be
            LEFT JOIN games g ON g.appid = be.appid
            {status_filter}
            ORDER BY be.submitted_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


_PHASE_SHORT: dict[str, str] = {
    "chunk": "chunk",
    "merge-L1": "merge",
    "merge-L2": "mergeL2",
    "synthesis": "syn",
}

_OVERALL_PRIORITY = ["failed", "running", "submitted", "completed"]


def _overall_status(phase_statuses: list[str]) -> str:
    """Derive overall execution status from individual phase statuses."""
    for s in _OVERALL_PRIORITY:
        if s in phase_statuses:
            return s
    return phase_statuses[0] if phase_statuses else "submitted"


def _phase_badge(phase: str, status: str) -> str:
    short = _PHASE_SHORT.get(phase, phase)
    icon = _STATUS_ICON.get(status, "?")
    return f"{short} {icon}"


def _group_by_execution(rows: list[dict]) -> list[dict]:
    """
    Collapse per-phase rows into one summary dict per execution_id.
    Rows without an execution_id get their own singleton group keyed by row id.
    Groups are sorted by earliest submitted_at DESC (newest first).
    """
    groups: dict[str | int, dict] = {}
    for r in rows:
        key = r["execution_id"] or r["id"]
        if key not in groups:
            groups[key] = {
                "appid": r["appid"],
                "game_name": r["game_name"],
                "execution_id": r["execution_id"],
                "phases": [],
                "submitted_at": None,
                "completed_at": None,
                "total_cost": 0.0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "failure_reason": None,
            }
        g = groups[key]
        g["phases"].append({"phase": r["phase"], "status": r["status"]})

        sa = r["submitted_at"]
        if sa and sa.tzinfo is None:
            sa = sa.replace(tzinfo=UTC)
        ca = r["completed_at"]
        if ca and ca.tzinfo is None:
            ca = ca.replace(tzinfo=UTC)

        if sa and (g["submitted_at"] is None or sa < g["submitted_at"]):
            g["submitted_at"] = sa
        if ca and (g["completed_at"] is None or ca > g["completed_at"]):
            g["completed_at"] = ca

        g["total_cost"] += float(r["estimated_cost_usd"] or 0.0)
        g["total_input_tokens"] += r["input_tokens"] or 0
        g["total_output_tokens"] += r["output_tokens"] or 0

        if r["failure_reason"] and not g["failure_reason"]:
            g["failure_reason"] = r["failure_reason"]

    # Sort groups newest first
    sorted_groups = sorted(
        groups.values(),
        key=lambda g: g["submitted_at"] or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return sorted_groups


def render_batches(rows: list[dict], *, show_all: bool) -> Table:
    now = datetime.now(UTC)
    label = "all executions" if show_all else "active executions"

    if not rows:
        msg = "No active batches." if not show_all else "No batch executions found."
        t = Table(box=box.ROUNDED, border_style="bright_black", expand=True)
        t.add_column(msg, style="yellow")
        return t

    groups = _group_by_execution(rows)

    table = Table(
        title=f"batch_executions — {label}",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        border_style="bright_black",
        expand=True,
    )

    table.add_column("appid", width=8, no_wrap=True)
    table.add_column("game", min_width=20)
    table.add_column("phases", min_width=30)
    table.add_column("status", width=14, no_wrap=True)
    table.add_column("elapsed", width=9, justify="right", no_wrap=True)
    table.add_column("cost $", width=7, justify="right", no_wrap=True)
    table.add_column("tokens", width=12, justify="right", no_wrap=True)
    if show_all:
        table.add_column("submitted", width=14, no_wrap=True)
    table.add_column("failure", min_width=20)

    totals: dict[str, int] = {"submitted": 0, "running": 0, "completed": 0, "failed": 0}

    for g in groups:
        phase_statuses = [p["status"] for p in g["phases"]]
        overall = _overall_status(phase_statuses)
        totals[overall] = totals.get(overall, 0) + 1

        style = _STATUS_STYLE.get(overall, "white")
        icon = _STATUS_ICON.get(overall, "")

        game = (g["game_name"] or f"appid {g['appid']}")[:28]

        # Phase badges in canonical order
        order = list(_PHASE_SHORT.keys())
        sorted_phases = sorted(g["phases"], key=lambda p: order.index(p["phase"]) if p["phase"] in order else 99)
        badges = "  ·  ".join(_phase_badge(p["phase"], p["status"]) for p in sorted_phases)

        submitted_at = g["submitted_at"]
        completed_at = g["completed_at"]
        elapsed = _elapsed(submitted_at, completed_at) if submitted_at else ""
        elapsed_text = Text(elapsed, style="bright_black" if overall == "completed" else "white")

        cost_val = g["total_cost"]
        cost = f"{cost_val:.4f}" if cost_val else "—"

        tok_in = g["total_input_tokens"]
        tok_out = g["total_output_tokens"]
        tokens = f"{tok_in // 1000}k/{tok_out // 1000}k" if (tok_in or tok_out) else "—"

        failure_cell = Text(
            (g["failure_reason"] or "")[:50],
            style="red" if g["failure_reason"] else "bright_black",
        )

        submitted_str = ""
        if submitted_at:
            submitted_str = submitted_at.astimezone().strftime("%m-%d %H:%M")

        row_cells: list[Any] = [
            Text(str(g["appid"]), style="bright_black"),
            Text(game),
            Text(badges, style="magenta"),
            Text(f"{icon} {overall}", style=style),
            elapsed_text,
            Text(cost, style="yellow" if cost != "—" else "bright_black"),
            Text(tokens, style="bright_black"),
        ]
        if show_all:
            row_cells.append(Text(submitted_str, style="bright_black"))
        row_cells.append(failure_cell)

        table.add_row(*row_cells)

    parts = []
    for s, n in totals.items():
        if n:
            parts.append(f"[{_STATUS_STYLE[s]}]{n} {s}[/{_STATUS_STYLE[s]}]")
    ts = now.astimezone().strftime("%H:%M:%S")
    table.caption = f"{' · '.join(parts)}  [bright_black]{ts}[/bright_black]"

    return table


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
    end_time = int(datetime.now(UTC).timestamp())
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
            dt = dt.replace(tzinfo=UTC)
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
            table.add_column(
                col.replace("@", "").replace("bin(", "").replace(")", ""),
                min_width=14,
                no_wrap=True,
            )
        elif col == "level":
            table.add_column("level", width=8, no_wrap=True)
        elif col in ("appid",):
            table.add_column(col, width=8, no_wrap=True)
        elif col in (
            "occurrences",
            "count",
            "reviews_ingested",
            "batches",
            "processed",
            "succeeded",
            "failed",
            "requests",
        ):
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
                cells.append(
                    Text(val[:60] + "…" if len(val) > 60 else val, style="red" if val else "")
                )
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
        description="CloudWatch Log Insights query runner + batch status monitor for SteamPulse"
    )
    parser.add_argument("--env", choices=["staging", "production"], default="production")
    parser.add_argument("--query", "-q", help="Named query to run (see --list)")
    parser.add_argument("--raw", help="Raw CloudWatch Insights query string")
    parser.add_argument(
        "--log-group",
        "-g",
        help="Log group shorthand or full path (overrides query default)",
    )
    parser.add_argument(
        "--since",
        "-s",
        default="1h",
        help="Lookback window: e.g. 30m, 6h, 1d (default: 1h)",
    )
    parser.add_argument(
        "--tail",
        "-t",
        type=int,
        metavar="SECONDS",
        help="Re-run query every N seconds (Ctrl-C to stop)",
    )
    parser.add_argument("--list", "-l", action="store_true", help="List available prepared queries")
    parser.add_argument("--region", default=REGION)

    # Batch status mode
    parser.add_argument(
        "--batches",
        "-b",
        action="store_true",
        help="Show batch_executions status from DB (uses DATABASE_URL env var)",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="With --batches: show completed and failed batches too (default: active only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="With --batches: max rows to show (default: 50)",
    )

    args = parser.parse_args()

    if args.list:
        list_queries()
        return

    # ── Batch mode ─────────────────────────────────────────────────────────────
    if args.batches:
        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql://steampulse:dev@127.0.0.1:5432/steampulse",
        )
        scope = "all executions" if args.all else "active batches"

        if args.tail:
            SPINNERS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            try:
                with Live(console=console, refresh_per_second=4, screen=False) as live:
                    spin_i = 0
                    while True:
                        rows = _fetch_batches(db_url, show_all=args.all, limit=args.limit)
                        table = render_batches(rows, show_all=args.all)
                        spin = SPINNERS[spin_i % len(SPINNERS)]
                        spin_i += 1
                        table.title = (
                            f"[cyan]batch_executions — {scope}[/cyan]  "
                            f"[bright_black]{spin} every {args.tail}s · Ctrl-C to stop[/bright_black]"
                        )
                        live.update(table)
                        time.sleep(args.tail)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopped.[/yellow]")
        else:
            rows = _fetch_batches(db_url, show_all=args.all, limit=args.limit)
            console.print(render_batches(rows, show_all=args.all))
        return
    if not args.query and not args.raw:
        parser.error("Provide --query NAME, --raw 'query string', or --batches")

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
        ts = datetime.now(UTC).strftime("%H:%M:%S UTC")
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
                console.print(
                    f"\n[bright_black]Refreshing every {args.tail}s — Ctrl-C to stop[/bright_black]"
                )
                time.sleep(args.tail)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped.[/yellow]")
    else:
        run_once()


if __name__ == "__main__":
    main()
