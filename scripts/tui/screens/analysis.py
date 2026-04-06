"""Analysis screen — monitor and trigger LLM analysis jobs."""

import asyncio
import json

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Static

from tui.queries import ANALYSIS_BACKLOG, REPORT_FULL_JSON
from tui.widgets.confirm_dialog import ConfirmDialog


class ReportViewer(VerticalScroll):
    """Scrollable panel showing formatted report JSON."""

    DEFAULT_CSS = """
    ReportViewer {
        height: 1fr;
        border: round $accent;
        padding: 1 2;
        margin: 0 1;
        display: none;
    }

    ReportViewer.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="report-content")


class AnalysisScreen(Widget):
    """Analysis backlog, job triggering, and report viewer."""

    DEFAULT_CSS = """
    AnalysisScreen {
        height: 100%;
        layout: vertical;
    }

    #analysis-header {
        height: 3;
        padding: 0 1;
        content-align: left middle;
    }

    #analysis-table-area {
        height: 1fr;
        margin: 0 1;
    }

    #analysis-status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("1", "analyze_selected", "Analyze", show=False),
        Binding("2", "batch_analyze", "Batch Analyze", show=False),
        Binding("enter", "view_report", "View Report", show=False),
        Binding("escape", "close_viewer", "Close", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]Analysis Backlog[/bold]  "
            "[dim]1[/dim] Analyze  [dim]2[/dim] Batch  [dim]Enter[/dim] View report  "
            "[dim]Esc[/dim] Close viewer",
            id="analysis-header",
        )

        with Vertical(id="analysis-table-area"):
            yield DataTable(id="analysis-table")

        yield ReportViewer(id="report-viewer")
        yield Static("", id="analysis-status")

    def on_mount(self) -> None:
        table = self.query_one("#analysis-table", DataTable)
        table.add_columns("AppID", "Name", "Steam Reviews", "DB Reviews", "Last Analyzed", "Status")
        table.cursor_type = "row"
        self.run_worker(self._load_backlog, exclusive=True)

    def action_refresh(self) -> None:
        self.run_worker(self._load_backlog, exclusive=True)

    def action_analyze_selected(self) -> None:
        table = self.query_one("#analysis-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0 or row_idx >= len(self._rows):
            return

        row = self._rows[row_idx]
        appid = row["appid"]
        name = row.get("name", str(appid))

        if not self.app.aws_available:  # type: ignore[attr-defined]
            self.app.notify("AWS not available in local mode", severity="warning")
            return

        async def _do_analyze(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                input_json = json.dumps({"appid": appid, "game_name": name})
                arn = await asyncio.to_thread(
                    self.app.aws.start_sfn_execution, input_json  # type: ignore[attr-defined]
                )
                self.app.notify(f"Started analysis for {name} ({appid})")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Start analysis for [bold]{name}[/bold] ({appid})?"),
            _do_analyze,
        )

    def action_batch_analyze(self) -> None:
        if not self.app.aws_available:  # type: ignore[attr-defined]
            self.app.notify("AWS not available in local mode", severity="warning")
            return

        # Queue top N unanalyzed games
        unanalyzed = [r for r in self._rows if r.get("status") == "no report"]
        if not unanalyzed:
            self.app.notify("No unanalyzed games in backlog")
            return

        count = min(10, len(unanalyzed))

        async def _do_batch(confirmed: bool) -> None:
            if not confirmed:
                return
            queued = 0
            for row in unanalyzed[:count]:
                try:
                    input_json = json.dumps({
                        "appid": row["appid"],
                        "game_name": row.get("name", str(row["appid"])),
                    })
                    await asyncio.to_thread(
                        self.app.aws.start_sfn_execution, input_json  # type: ignore[attr-defined]
                    )
                    queued += 1
                except Exception as exc:  # noqa: BLE001
                    self.app.notify(f"Error on {row['appid']}: {exc}", severity="error")
                    break
            self.app.notify(f"Started analysis for {queued} games")

        self.app.push_screen(
            ConfirmDialog(f"Batch analyze top {count} unanalyzed games?"),
            _do_batch,
        )

    def action_view_report(self) -> None:
        table = self.query_one("#analysis-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0 or row_idx >= len(self._rows):
            return

        row = self._rows[row_idx]
        if row.get("status") == "no report":
            self.app.notify("No report available for this game", severity="warning")
            return

        self.run_worker(self._load_report(row["appid"]), exclusive=True)

    def action_close_viewer(self) -> None:
        self.query_one("#report-viewer").remove_class("visible")

    async def _load_backlog(self) -> None:
        if not self.app.db_dsn:  # type: ignore[attr-defined]
            return
        conn = self.app.get_db()  # type: ignore[attr-defined]

        try:
            rows = await asyncio.to_thread(self._query_all, conn, ANALYSIS_BACKLOG)
            self._rows = rows or []

            table = self.query_one("#analysis-table", DataTable)
            table.clear()
            for row in self._rows:
                status = row.get("status", "")
                status_display = {
                    "no report": "[red]no report[/red]",
                    "stale": "[yellow]stale[/yellow]",
                    "current": "[green]current[/green]",
                }.get(status, status)

                table.add_row(
                    str(row.get("appid", "")),
                    (row.get("name", "") or "")[:35],
                    f"{row.get('review_count', 0):,}",
                    f"{row.get('reviews_in_db', 0):,}",
                    str(row.get("last_analyzed", "never"))[:19],
                    status_display,
                )

            no_report = sum(1 for r in self._rows if r.get("status") == "no report")
            stale = sum(1 for r in self._rows if r.get("status") == "stale")
            self.query_one("#analysis-status", Static).update(
                f"  {len(self._rows)} games  \u2502  "
                f"[red]{no_report} no report[/red]  \u2502  "
                f"[yellow]{stale} stale[/yellow]"
            )
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Query error: {exc}", severity="error")
        finally:
            conn.close()

    async def _load_report(self, appid: int) -> None:
        if not self.app.db_dsn:  # type: ignore[attr-defined]
            return
        conn = self.app.get_db()  # type: ignore[attr-defined]

        try:
            row = await asyncio.to_thread(self._query_one, conn, REPORT_FULL_JSON, (appid,))
            if not row or not row.get("report_json"):
                self.app.notify("No report found", severity="warning")
                return

            report = row["report_json"]
            if isinstance(report, str):
                report = json.loads(report)

            formatted = json.dumps(report, indent=2, default=str)

            viewer = self.query_one("#report-viewer", ReportViewer)
            viewer.query_one("#report-content", Static).update(
                f"[bold]Report for {report.get('game_name', appid)}[/bold]\n\n{formatted}"
            )
            viewer.add_class("visible")
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Error loading report: {exc}", severity="error")
        finally:
            conn.close()

    @staticmethod
    def _query_one(conn: object, sql: str, params: object = None) -> dict | None:
        cur = conn.cursor()  # type: ignore[union-attr]
        try:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()

    @staticmethod
    def _query_all(conn: object, sql: str, params: object = None) -> list[dict]:
        cur = conn.cursor()  # type: ignore[union-attr]
        try:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
