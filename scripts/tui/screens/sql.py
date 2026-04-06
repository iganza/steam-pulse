"""SQL Console screen — interactive read-only SQL query tool."""

import asyncio
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, OptionList, Static, TextArea

from tui.queries import SAVED_QUERIES

_WRITE_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_HISTORY_DIR = Path.home() / ".steampulse"
_HISTORY_FILE = _HISTORY_DIR / "query_history.json"
_MAX_HISTORY = 50


def _load_history() -> list[str]:
    try:
        if _HISTORY_FILE.exists():
            return json.loads(_HISTORY_FILE.read_text())[-_MAX_HISTORY:]
    except Exception:  # noqa: BLE001
        pass
    return []


def _save_history(history: list[str]) -> None:
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        _HISTORY_FILE.write_text(json.dumps(history[-_MAX_HISTORY:]))
    except Exception:  # noqa: BLE001
        pass


class SQLConsoleScreen(Widget):
    """Interactive read-only SQL console with query history and templates."""

    DEFAULT_CSS = """
    SQLConsoleScreen {
        height: 100%;
        layout: vertical;
    }

    #sql-input-area {
        height: 10;
        border: round $primary;
        margin: 0 1;
    }

    #sql-input {
        height: 100%;
    }

    #sql-toolbar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        margin-top: 0;
    }

    #sql-results-area {
        height: 1fr;
        margin: 0 1;
        border: round $accent;
    }

    #sql-status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #sql-error {
        color: $error;
        padding: 0 2;
        height: auto;
        display: none;
    }

    #sql-error.visible {
        display: block;
    }

    #sql-templates {
        display: none;
        height: 15;
        width: 60;
        border: solid $accent;
        margin: 0 1;
    }

    #sql-templates.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("ctrl+enter", "execute", "Run Query", show=True, priority=True),
        Binding("ctrl+l", "show_templates", "Templates", show=True),
        Binding("ctrl+s", "export_csv", "Export CSV", show=True),
        Binding("escape", "hide_panels", "Close", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._history = _load_history()
        self._history_idx = -1
        self._last_results: list[dict] = []
        self._last_columns: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="sql-input-area"):
            yield TextArea(language="sql", id="sql-input", show_line_numbers=True)

        with Horizontal(id="sql-toolbar"):
            yield Static(
                "[bold]Ctrl+Enter[/bold] Run  "
                "[bold]Ctrl+L[/bold] Templates  "
                "[bold]Ctrl+S[/bold] Export CSV  "
                "[bold]\u2191\u2193[/bold] History (when empty)",
            )

        yield Static("", id="sql-error")

        yield OptionList(id="sql-templates")

        with Vertical(id="sql-results-area"):
            yield DataTable(id="sql-results")

        yield Static("Ready", id="sql-status")

    def on_mount(self) -> None:
        # Populate template list
        template_list = self.query_one("#sql-templates", OptionList)
        for name in SAVED_QUERIES:
            template_list.add_option(name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        name = str(event.option.prompt)
        sql = SAVED_QUERIES.get(name, "")
        if sql:
            self.query_one("#sql-input", TextArea).text = sql
            self.query_one("#sql-templates").remove_class("visible")
            self.app.notify(f"Loaded: {name}")

    def action_execute(self) -> None:
        sql = self.query_one("#sql-input", TextArea).text.strip()
        if not sql:
            return

        # Reject write operations
        if _WRITE_PATTERN.search(sql):
            self._show_error("Write operations are not allowed. This is a read-only console.")
            return

        # Reject multi-statement input (semicolons outside string literals)
        # Strip trailing semicolons/whitespace, then check for remaining semicolons
        stripped = sql.rstrip().rstrip(";").strip()
        if ";" in stripped:
            self._show_error("Multi-statement queries are not allowed. Use a single statement.")
            return

        self._hide_error()

        # Add to history
        if not self._history or self._history[-1] != sql:
            self._history.append(sql)
            _save_history(self._history)
        self._history_idx = -1

        self.run_worker(self._run_query(sql), exclusive=True)

    def action_show_templates(self) -> None:
        templates = self.query_one("#sql-templates")
        if templates.has_class("visible"):
            templates.remove_class("visible")
        else:
            templates.add_class("visible")

    def action_hide_panels(self) -> None:
        self.query_one("#sql-templates").remove_class("visible")

    def action_export_csv(self) -> None:
        if not self._last_results or not self._last_columns:
            self.app.notify("No results to export", severity="warning")
            return

        downloads = Path.home() / "Downloads"
        downloads.mkdir(exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        filepath = downloads / f"steampulse-query-{ts}.csv"

        with filepath.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._last_columns)
            writer.writeheader()
            writer.writerows(self._last_results)

        self.app.notify(f"Exported to {filepath}")

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        text_area = self.query_one("#sql-input", TextArea)

        # History navigation: up = older, down = newer
        if key == "up" and (not text_area.text.strip() or self._history_idx >= 0):
            self._navigate_history(1)
        elif key == "down" and self._history_idx >= 0:
            self._navigate_history(-1)

    def _navigate_history(self, direction: int) -> None:
        """Navigate query history. direction=1 goes older, direction=-1 goes newer."""
        if not self._history:
            return
        self._history_idx += direction
        self._history_idx = max(-1, min(self._history_idx, len(self._history) - 1))

        text_area = self.query_one("#sql-input", TextArea)
        if self._history_idx < 0:
            text_area.text = ""
            self._history_idx = -1
        else:
            # Index from the end: 0 = most recent, 1 = second most recent, etc.
            idx = len(self._history) - 1 - self._history_idx
            if 0 <= idx < len(self._history):
                text_area.text = self._history[idx]

    async def _run_query(self, sql: str) -> None:
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn:
            self._show_error("No database connection")
            return

        status = self.query_one("#sql-status", Static)
        status.update("Running...")

        try:
            start = time.monotonic()
            columns, rows = await asyncio.to_thread(self._execute_readonly, conn, sql)
            elapsed = (time.monotonic() - start) * 1000

            self._last_columns = columns
            self._last_results = rows

            table = self.query_one("#sql-results", DataTable)
            table.clear(columns=True)

            if columns:
                table.add_columns(*columns)
                for row in rows[:500]:
                    table.add_row(*[self._format_cell(row.get(c)) for c in columns])

            row_note = f" (showing 500/{len(rows)})" if len(rows) > 500 else ""
            status.update(
                f"  {len(rows)} rows{row_note}  \u2502  {elapsed:.0f}ms  "
                f"\u2502  History: \u2191\u2193"
            )
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))
            status.update("Error")

    @staticmethod
    def _execute_readonly(conn: object, sql: str) -> tuple[list[str], list[dict]]:
        """Execute SQL in a read-only transaction with timeout."""
        cur = conn.cursor()  # type: ignore[union-attr]
        try:
            cur.execute("BEGIN TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            cur.execute(sql)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(row) for row in cur.fetchall()]
            cur.execute("COMMIT")
            return columns, rows
        except Exception:
            cur.execute("ROLLBACK")
            raise
        finally:
            cur.close()

    @staticmethod
    def _format_cell(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:.2f}"
        if isinstance(value, dict):
            return json.dumps(value, default=str)[:60]
        return str(value)[:60]

    def _show_error(self, msg: str) -> None:
        err = self.query_one("#sql-error", Static)
        err.update(f"[red]{msg}[/red]")
        err.add_class("visible")

    def _hide_error(self) -> None:
        self.query_one("#sql-error", Static).remove_class("visible")
