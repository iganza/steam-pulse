"""Dashboard screen — system overview with KPIs, pipeline status, and queue depths."""

import asyncio
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Static

from tui.queries import (
    DASHBOARD_FRESHNESS,
    DASHBOARD_KPI,
    DASHBOARD_MIGRATIONS,
    DASHBOARD_PIPELINE,
    DASHBOARD_REPORT_COUNT,
)
from tui.widgets.freshness import FreshnessLabel
from tui.widgets.kpi_card import KpiCard
from tui.widgets.pipeline_funnel import PipelineFunnel

# Count migration files on disk for comparison with DB state
_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "src" / "lambda-functions" / "migrations"
_TOTAL_MIGRATION_FILES = len(list(_MIGRATIONS_DIR.glob("*.sql"))) if _MIGRATIONS_DIR.exists() else 0


class DashboardScreen(Widget):
    """Landing screen with live system overview."""

    DEFAULT_CSS = """
    DashboardScreen {
        height: 100%;
        padding: 1;
    }

    #kpi-row {
        height: 7;
        layout: horizontal;
    }

    #kpi-row KpiCard {
        width: 1fr;
        margin: 0 1;
    }

    #middle-row {
        height: auto;
        margin-top: 1;
    }

    #bottom-row {
        layout: horizontal;
        height: auto;
        margin-top: 1;
    }

    #freshness-panel {
        width: 1fr;
        height: auto;
        border: round $primary;
        padding: 1 2;
    }

    #queue-panel {
        width: 1fr;
        height: auto;
        border: round $primary;
        padding: 1 2;
        margin-left: 1;
    }

    #migrations-panel {
        width: 1fr;
        height: auto;
        border: round $primary;
        padding: 1 2;
        margin-left: 1;
    }

    #refresh-hint {
        dock: bottom;
        height: 1;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("f5", "refresh", "Refresh", show=True),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._refresh_timer_id: object = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="kpi-row"):
            yield KpiCard("Games", id="kpi-games")
            yield KpiCard("Reviews", id="kpi-reviews")
            yield KpiCard("Reports", id="kpi-reports")
            yield KpiCard("Catalog", id="kpi-catalog")

        with Vertical(id="middle-row"):
            yield PipelineFunnel(id="pipeline-funnel")

        with Horizontal(id="bottom-row"):
            with Vertical(id="freshness-panel"):
                yield Static("[bold]Freshness[/bold]")
                yield FreshnessLabel("Last metadata crawl", id="fresh-meta")
                yield FreshnessLabel("Last review crawl", id="fresh-reviews")
                yield FreshnessLabel("Last analysis", id="fresh-analysis")
                yield FreshnessLabel("Last matview refresh", id="fresh-matview")

            with Vertical(id="queue-panel"):
                yield Static("[bold]Queue Depths[/bold]")
                yield DataTable(id="queue-table")

            with Vertical(id="migrations-panel"):
                yield Static("[bold]Migrations[/bold]")
                yield Static("", id="migrations-status")

        yield Static("Press [bold]F5[/bold] to refresh \u2022 Auto-refresh: 30s", id="refresh-hint")

    def on_mount(self) -> None:
        # Set up queue table columns
        table = self.query_one("#queue-table", DataTable)
        table.add_columns("Queue", "Available", "In Flight", "Delayed")
        table.show_cursor = False

        self.refresh_data()
        self.set_interval(30, self.refresh_data)

    def action_refresh(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        """Kick off a background data load."""
        self.run_worker(self._load_data)

    async def _load_data(self) -> None:
        """Load all dashboard data (runs in worker)."""
        app = self.app

        if app.db_dsn:  # type: ignore[attr-defined]
            conn = app.get_db()  # type: ignore[attr-defined]
            try:
                kpi, pipeline, freshness, migrations = await asyncio.gather(
                    asyncio.to_thread(self._query_db, conn, DASHBOARD_KPI),
                    asyncio.to_thread(self._query_db, conn, DASHBOARD_PIPELINE),
                    asyncio.to_thread(self._query_db, conn, DASHBOARD_FRESHNESS),
                    asyncio.to_thread(self._query_all, conn, DASHBOARD_MIGRATIONS),
                )
                report_count = await asyncio.to_thread(
                    self._query_db, conn, DASHBOARD_REPORT_COUNT
                )

                if kpi:
                    self.query_one("#kpi-games", KpiCard).value = f"{kpi['games']:,}"
                    self.query_one("#kpi-reviews", KpiCard).value = f"{kpi['reviews']:,}"
                    self.query_one("#kpi-reports", KpiCard).value = f"{kpi['reports']:,}"
                    self.query_one("#kpi-catalog", KpiCard).value = f"{kpi['catalog']:,}"

                if pipeline:
                    reports = report_count["reports"] if report_count else 0
                    self.query_one("#pipeline-funnel", PipelineFunnel).data = {
                        **pipeline,
                        "reports": reports,
                    }

                if freshness:
                    self.query_one("#fresh-meta", FreshnessLabel).timestamp = freshness[
                        "last_meta_crawl"
                    ]
                    self.query_one("#fresh-reviews", FreshnessLabel).timestamp = freshness[
                        "last_review_crawl"
                    ]
                    self.query_one("#fresh-analysis", FreshnessLabel).timestamp = freshness[
                        "last_analysis"
                    ]
                    self.query_one("#fresh-matview", FreshnessLabel).timestamp = freshness[
                        "last_matview_refresh"
                    ]

                # Migrations
                applied_count = len(migrations) if migrations else 0
                total_files = _TOTAL_MIGRATION_FILES
                if applied_count == total_files:
                    status_color = "green"
                    status_icon = "\u2713"
                else:
                    status_color = "red"
                    status_icon = "\u26a0"

                lines = [
                    f"[{status_color}]{status_icon}[/{status_color}] "
                    f"{applied_count}/{total_files} applied",
                ]
                if migrations:
                    lines.append("")
                    for row in migrations[:5]:
                        mid = row["migration_id"]
                        ts = str(row["applied_at_utc"])[:19]
                        lines.append(f"  [dim]{ts}[/dim]  {mid}")
                if applied_count < total_files:
                    # Find which migrations are missing
                    applied_ids = {r["migration_id"] for r in (migrations or [])}
                    pending = sorted(
                        f.stem for f in _MIGRATIONS_DIR.glob("*.sql")
                        if f.stem not in applied_ids
                    )
                    if pending:
                        lines.append("")
                        lines.append(f"[red]Pending ({len(pending)}):[/red]")
                        for p in pending[:5]:
                            lines.append(f"  [red]{p}[/red]")

                self.query_one("#migrations-status", Static).update("\n".join(lines))

            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"DB error: {exc}", severity="error")
            finally:
                conn.close()

        # Queue depths (AWS only)
        if app.aws_available:  # type: ignore[attr-defined]
            try:
                depths = await asyncio.to_thread(app.aws.get_all_queue_depths)  # type: ignore[attr-defined]
                table = self.query_one("#queue-table", DataTable)
                table.clear()
                for name, info in depths.items():
                    avail = str(info["available"]) if info["available"] >= 0 else "?"
                    inflight = str(info["in_flight"]) if info["in_flight"] >= 0 else "?"
                    delayed = str(info["delayed"]) if info["delayed"] >= 0 else "?"
                    warning = " \u26a0" if info["available"] > 0 and "dlq" in name else ""
                    table.add_row(f"{name}{warning}", avail, inflight, delayed)
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"AWS error: {exc}", severity="warning")
        else:
            table = self.query_one("#queue-table", DataTable)
            table.clear()
            table.add_row("[dim]Connect with --env for AWS ops[/dim]", "", "", "")

    @staticmethod
    def _query_db(conn: object, sql: str) -> dict | None:
        """Execute a query and return the first row as a dict."""
        cur = conn.cursor()  # type: ignore[union-attr]
        try:
            cur.execute(sql)
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()

    @staticmethod
    def _query_all(conn: object, sql: str) -> list[dict]:
        """Execute a query and return all rows as dicts."""
        cur = conn.cursor()  # type: ignore[union-attr]
        try:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
