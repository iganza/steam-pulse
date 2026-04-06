"""Logs screen — CloudWatch log streaming."""

import asyncio
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Checkbox, RichLog, Select, Static

from tui.aws import AwsUnavailableError

SERVICES = ["crawler", "spoke", "ingest", "api", "analysis", "admin"]

TIME_RANGES = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "1d": 24 * 60 * 60,
}

SERVICE_COLORS = {
    "crawler": "blue",
    "spoke": "green",
    "ingest": "yellow",
    "api": "cyan",
    "analysis": "magenta",
    "admin": "white",
}


class LogsScreen(Widget):
    """Stream CloudWatch logs with service filtering. AWS-only."""

    DEFAULT_CSS = """
    LogsScreen {
        height: 100%;
        layout: vertical;
    }

    #logs-header {
        height: 3;
        layout: horizontal;
        padding: 0 1;
    }

    #logs-header Checkbox {
        margin: 0 1;
        width: auto;
    }

    #logs-time-range {
        width: 12;
    }

    #logs-stream {
        height: 1fr;
        margin: 0 1;
        border: round $primary;
    }

    #logs-status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("e", "toggle_errors", "Errors Only", show=False),
        Binding("f5", "refresh_logs", "Refresh", show=False),
        Binding("end", "scroll_bottom", "Resume Auto-scroll", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._active_services: set[str] = {"crawler", "spoke", "ingest"}
        self._errors_only = False
        self._time_range = "15m"
        self._polling = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="logs-header"):
            for svc in SERVICES:
                yield Checkbox(
                    svc,
                    value=svc in self._active_services,
                    id=f"logs-svc-{svc}",
                )
            yield Select(
                [(label, label) for label in TIME_RANGES],
                value="15m",
                id="logs-time-range",
                allow_blank=False,
            )

        yield RichLog(id="logs-stream", highlight=True, markup=True)
        yield Static("", id="logs-status")

    def on_mount(self) -> None:
        if not self.app.aws_available:  # type: ignore[attr-defined]
            log = self.query_one("#logs-stream", RichLog)
            log.write("[dim]Connect with --env staging or --env production for logs[/dim]")
            return

        self.set_interval(5, self._poll_logs)
        self.run_worker(self._initial_load, exclusive=True)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id or ""
        if checkbox_id.startswith("logs-svc-"):
            svc = checkbox_id.removeprefix("logs-svc-")
            if event.value:
                self._active_services.add(svc)
            else:
                self._active_services.discard(svc)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "logs-time-range":
            self._time_range = str(event.value)

            log = self.query_one("#logs-stream", RichLog)
            log.clear()
            self.run_worker(self._initial_load, exclusive=True)

    def action_toggle_errors(self) -> None:
        self._errors_only = not self._errors_only
        mode = "errors only" if self._errors_only else "all levels"
        self.app.notify(f"Log filter: {mode}")
        log = self.query_one("#logs-stream", RichLog)
        log.clear()
        self.run_worker(self._initial_load, exclusive=True)

    def action_refresh_logs(self) -> None:
        log = self.query_one("#logs-stream", RichLog)
        log.clear()
        self.run_worker(self._initial_load, exclusive=True)

    def action_scroll_bottom(self) -> None:
        self.query_one("#logs-stream", RichLog).scroll_end()

    async def _poll_logs(self) -> None:
        if self._polling or not self.app.aws_available:  # type: ignore[attr-defined]
            return
        self.run_worker(self._fetch_new_logs, exclusive=True)

    def _log_group_names(self) -> list[tuple[str, str, str]]:
        """Return (service, log_group_name, region) triples for active services."""
        env = self.app.env  # type: ignore[attr-defined]
        groups: list[tuple[str, str, str]] = []
        for svc in self._active_services:
            if svc == "spoke":
                spoke_regions = getattr(self.app, "spoke_regions", [])
                for spoke_region in spoke_regions:
                    groups.append((svc, f"/steampulse/{env}/spoke/{spoke_region}", spoke_region))
            else:
                groups.append((svc, f"/steampulse/{env}/{svc}", "us-west-2"))
        return groups

    async def _initial_load(self) -> None:
        """Load initial batch of logs."""
        if not self.app.aws_available:  # type: ignore[attr-defined]
            return

        self._polling = True
        try:
            seconds = TIME_RANGES.get(self._time_range, 900)
            start_ms = int((time.time() - seconds) * 1000)
            filter_pattern = '"ERROR"' if self._errors_only else ""

            log_widget = self.query_one("#logs-stream", RichLog)

            for svc, log_group, region in self._log_group_names():
                try:
                    events = await asyncio.to_thread(
                        self._fetch_log_events,
                        log_group,
                        start_ms,
                        filter_pattern,
                        region,
                    )
                    color = SERVICE_COLORS.get(svc, "white")
                    for event in events:
                        ts = event.get("timestamp", 0)
                        msg = event.get("message", "").strip()
                        time_str = time.strftime("%H:%M:%S", time.gmtime(ts / 1000))
                        level_color = self._level_color(msg)
                        log_widget.write(
                            f"[{color}][{svc}][/{color}] "
                            f"[dim]{time_str}[/dim] "
                            f"[{level_color}]{msg[:200]}[/{level_color}]"
                        )
                except Exception:  # noqa: BLE001
                    log_widget.write(f"[dim]Could not load logs for {log_group}[/dim]")

            self.query_one("#logs-status", Static).update(
                f"  Services: {', '.join(sorted(self._active_services))}  \u2502  "
                f"Range: {self._time_range}  \u2502  "
                f"{'[red]Errors only[/red]' if self._errors_only else 'All levels'}  \u2502  "
                f"Polling every 5s"
            )
        finally:
            self._polling = False

    async def _fetch_new_logs(self) -> None:
        """Fetch only new logs since last poll."""
        if not self.app.aws_available:  # type: ignore[attr-defined]
            return
        # For simplicity, re-fetch last 10 seconds of logs
        self._polling = True
        try:
            start_ms = int((time.time() - 10) * 1000)
            filter_pattern = '"ERROR"' if self._errors_only else ""
            log_widget = self.query_one("#logs-stream", RichLog)

            for svc, log_group, region in self._log_group_names():
                try:
                    events = await asyncio.to_thread(
                        self._fetch_log_events,
                        log_group,
                        start_ms,
                        filter_pattern,
                        region,
                    )
                    color = SERVICE_COLORS.get(svc, "white")
                    for event in events:
                        ts = event.get("timestamp", 0)
                        msg = event.get("message", "").strip()
                        time_str = time.strftime("%H:%M:%S", time.gmtime(ts / 1000))
                        level_color = self._level_color(msg)
                        log_widget.write(
                            f"[{color}][{svc}][/{color}] "
                            f"[dim]{time_str}[/dim] "
                            f"[{level_color}]{msg[:200]}[/{level_color}]"
                        )
                except Exception:  # noqa: BLE001
                    pass
        finally:
            self._polling = False

    def _fetch_log_events(
        self, log_group: str, start_ms: int, filter_pattern: str, region: str = "us-west-2"
    ) -> list[dict]:
        """Fetch log events from CloudWatch (sync, runs in thread)."""
        aws = self.app.aws  # type: ignore[attr-defined]
        logs_client = aws.logs_for_region(region)
        kwargs: dict = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "limit": 100,
            "interleaved": True,
        }
        if filter_pattern:
            kwargs["filterPattern"] = filter_pattern
        try:
            result = logs_client.filter_log_events(**kwargs)
            return result.get("events", [])
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _level_color(msg: str) -> str:
        upper = msg[:50].upper()
        if "ERROR" in upper:
            return "red"
        if "WARN" in upper:
            return "yellow"
        return "white"
