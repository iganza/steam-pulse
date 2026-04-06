"""Queues screen — SQS queue monitor and DLQ inspector."""

import asyncio
import json

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Static

from tui.aws import AwsUnavailableError
from tui.widgets.confirm_dialog import ConfirmDialog

# Map DLQ name → source queue name for retry routing
DLQ_TO_SOURCE = {
    "app-crawl-dlq": "app-crawl-queue",
    "review-crawl-dlq": "review-crawl-queue",
    "spoke-results-dlq": "spoke-results-queue",
    "email-dlq": "email-queue",
}


class DlqInspector(VerticalScroll):
    """Panel for inspecting DLQ messages."""

    DEFAULT_CSS = """
    DlqInspector {
        height: 15;
        border: round $error;
        padding: 1 2;
        margin: 0 1;
        display: none;
    }

    DlqInspector.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="dlq-content")
        yield Static(
            "\n[dim]1[/dim] Retry message  [dim]2[/dim] Delete message  [dim]Esc[/dim] Close",
            id="dlq-actions",
        )


class QueuesScreen(Widget):
    """Monitor SQS queues and inspect dead letters. AWS-only."""

    DEFAULT_CSS = """
    QueuesScreen {
        height: 100%;
        layout: vertical;
    }

    #queues-header {
        height: 3;
        padding: 0 1;
        content-align: left middle;
    }

    #queues-table-area {
        height: 1fr;
        margin: 0 1;
    }

    #queues-status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "inspect_dlq", "Inspect DLQ", show=False),
        Binding("1", "retry_dlq_message", "Retry", show=False),
        Binding("2", "delete_dlq_message", "Delete", show=False),
        Binding("escape", "close_inspector", "Close", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._queue_names: list[str] = []
        self._dlq_messages: list[dict] = []
        self._selected_dlq: str | None = None
        self._prev_depths: dict[str, int] = {}
        self._prev_time: float = 0.0
        self._last_rates: dict[str, float] = {}

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold]SQS Queues[/bold]  "
            "[dim]Enter[/dim] Inspect DLQ  "
            "Auto-refresh: 10s",
            id="queues-header",
        )

        with Vertical(id="queues-table-area"):
            yield DataTable(id="queues-table")

        yield DlqInspector(id="dlq-inspector")
        yield Static("", id="queues-status")

    def on_mount(self) -> None:
        table = self.query_one("#queues-table", DataTable)
        table.add_columns("Queue", "Available", "In Flight", "Delayed", "Rate", "ETA", "Type")
        table.cursor_type = "row"

        if self.app.aws_available:  # type: ignore[attr-defined]
            self.refresh_data()
            self.set_interval(10, self.refresh_data)
        else:
            table.add_row("[dim]Connect with --env for AWS ops[/dim]", "", "", "")

    def refresh_data(self) -> None:
        if self.app.aws_available:  # type: ignore[attr-defined]
            self.run_worker(self._load_queues)

    def action_refresh(self) -> None:
        self.refresh_data()

    def action_close_inspector(self) -> None:
        self.query_one("#dlq-inspector").remove_class("visible")

    def action_inspect_dlq(self) -> None:
        table = self.query_one("#queues-table", DataTable)
        row_idx = table.cursor_row
        if row_idx < 0 or row_idx >= len(self._queue_names):
            return

        name = self._queue_names[row_idx]
        if "dlq" not in name:
            self.app.notify("Select a DLQ to inspect", severity="warning")
            return

        self._selected_dlq = name
        self.run_worker(self._peek_dlq(name), exclusive=True)

    def action_refresh(self) -> None:
        self._do_refresh()

    @staticmethod
    def _format_rate(rate: float) -> str:
        """Format processing rate as msg/s or msg/m."""
        if rate <= 0:
            return ""
        if rate >= 1:
            return f"{rate:.1f}/s"
        return f"{rate * 60:.0f}/m"

    @staticmethod
    def _format_eta(available: int, rate: float) -> str:
        """Format estimated time to drain."""
        if rate <= 0 or available <= 0:
            return ""
        secs = available / rate
        if secs < 60:
            return f"{secs:.0f}s"
        if secs < 3600:
            return f"{secs / 60:.0f}m"
        return f"{secs / 3600:.1f}h"

    async def _load_queues(self) -> None:
        try:
            import time

            now = time.monotonic()
            depths = await asyncio.to_thread(
                self.app.aws.get_all_queue_depths  # type: ignore[attr-defined]
            )

            # Compute processing rates from delta with previous reading
            elapsed = now - self._prev_time if self._prev_time > 0 else 0
            if elapsed > 0 and self._prev_depths:
                for name, info in depths.items():
                    if "dlq" in name:
                        continue
                    prev = self._prev_depths.get(name, 0)
                    curr = info["available"] + info["in_flight"]
                    delta = prev - curr  # positive = draining
                    new_rate = max(0, delta / elapsed)
                    if new_rate > 0:
                        # New measurement — use it
                        self._last_rates[name] = new_rate
                    elif curr == 0:
                        # Queue is empty — clear the rate
                        self._last_rates.pop(name, None)
                    # else: queue has items but no change this cycle — keep last rate

            # Store current reading for next cycle
            self._prev_depths = {
                k: v["available"] + v["in_flight"]
                for k, v in depths.items()
                if "dlq" not in k
            }
            self._prev_time = now
            rates = self._last_rates

            # Build reverse map: source queue name → DLQ name
            source_to_dlq = {v: k for k, v in DLQ_TO_SOURCE.items()}

            # Separate queues from DLQs
            queues = {k: v for k, v in depths.items() if "dlq" not in k}
            dlqs = {k: v for k, v in depths.items() if "dlq" in k}

            # Build rows first, then swap into table in one batch
            new_names: list[str] = []
            new_rows: list[tuple[str, ...]] = []

            for name, info in queues.items():
                new_names.append(name)
                avail = str(info["available"]) if info["available"] >= 0 else "?"
                inflight = str(info["in_flight"]) if info["in_flight"] >= 0 else "?"
                delayed = str(info["delayed"]) if info["delayed"] >= 0 else "?"
                rate = rates.get(name, 0)
                rate_str = self._format_rate(rate)
                eta_str = self._format_eta(info["available"], rate)
                new_rows.append((name, avail, inflight, delayed, rate_str, eta_str, ""))

                # Show DLQ underneath if it has messages
                dlq_name = source_to_dlq.get(name)
                if dlq_name and dlq_name in dlqs:
                    dlq_info = dlqs[dlq_name]
                    if dlq_info["available"] > 0:
                        new_names.append(dlq_name)
                        new_rows.append((
                            f"  [red]\u2514 {dlq_name} \u26a0[/red]",
                            f"[red]{dlq_info['available']}[/red]",
                            str(dlq_info["in_flight"]),
                            str(dlq_info["delayed"]),
                            "",
                            "",
                            "[red]DLQ[/red]",
                        ))

            # Swap into table — clear + add back-to-back to minimize flicker
            self._queue_names = new_names
            table = self.query_one("#queues-table", DataTable)
            table.clear()
            for row in new_rows:
                table.add_row(*row)

            total_dlq = sum(
                v["available"]
                for v in dlqs.values()
                if v["available"] > 0
            )
            queue_count = len(queues)
            status = f"  {queue_count} queues"
            if total_dlq > 0:
                status += f"  \u2502  [red]{total_dlq} DLQ messages[/red]"
            else:
                status += f"  \u2502  [green]DLQs clean[/green]"
            self.query_one("#queues-status", Static).update(status)

        except AwsUnavailableError:
            self.app.notify("AWS not available", severity="warning")
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"AWS error: {exc}", severity="error")

    async def _peek_dlq(self, name: str) -> None:
        """Peek at messages in a DLQ without consuming them."""
        try:
            aws = self.app.aws  # type: ignore[attr-defined]
            url = aws.get_queue_url(name)
            if not url:
                self.app.notify(f"Could not resolve URL for {name}", severity="error")
                return

            result = await asyncio.to_thread(
                aws.sqs.receive_message,
                QueueUrl=url,
                MaxNumberOfMessages=10,
                VisibilityTimeout=30,
                AttributeNames=["All"],
            )

            messages = result.get("Messages", [])
            self._dlq_messages = messages

            if not messages:
                self.app.notify(f"No messages in {name}")
                return

            lines = [f"[bold]{name}[/bold] — {len(messages)} message(s)\n"]
            for i, msg in enumerate(messages):
                body = msg.get("Body", "")
                try:
                    parsed = json.loads(body)
                    body_display = json.dumps(parsed, indent=2, default=str)[:300]
                except (json.JSONDecodeError, TypeError):
                    body_display = body[:300]

                receive_count = msg.get("Attributes", {}).get("ApproximateReceiveCount", "?")
                sent_ts = msg.get("Attributes", {}).get("SentTimestamp", "?")
                lines.append(
                    f"[bold]Message {i + 1}[/bold]  "
                    f"Receives: {receive_count}  Sent: {sent_ts}\n"
                    f"{body_display}\n"
                )

            inspector = self.query_one("#dlq-inspector", DlqInspector)
            inspector.query_one("#dlq-content", Static).update("\n".join(lines))
            inspector.add_class("visible")

        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Error peeking DLQ: {exc}", severity="error")

    def action_retry_dlq_message(self) -> None:
        """Retry the first DLQ message by moving it to the source queue."""
        if not self._dlq_messages or not self._selected_dlq:
            self.app.notify("No DLQ messages to retry", severity="warning")
            return

        source_name = DLQ_TO_SOURCE.get(self._selected_dlq)
        if not source_name:
            self.app.notify(f"No source queue mapped for {self._selected_dlq}", severity="error")
            return

        msg = self._dlq_messages[0]

        async def _do_retry(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                aws = self.app.aws  # type: ignore[attr-defined]
                source_url = aws.get_queue_url(source_name)
                dlq_url = aws.get_queue_url(self._selected_dlq)
                if not source_url or not dlq_url:
                    self.app.notify("Could not resolve queue URLs", severity="error")
                    return

                # Send to source queue
                await asyncio.to_thread(
                    aws.sqs.send_message,
                    QueueUrl=source_url,
                    MessageBody=msg["Body"],
                )
                # Delete from DLQ
                await asyncio.to_thread(
                    aws.sqs.delete_message,
                    QueueUrl=dlq_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
                self._dlq_messages.pop(0)
                self.app.notify(f"Message retried to {source_name}")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Retry failed: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Retry first message from {self._selected_dlq} to {source_name}?"),
            _do_retry,
        )

    def action_delete_dlq_message(self) -> None:
        """Delete the first DLQ message."""
        if not self._dlq_messages or not self._selected_dlq:
            self.app.notify("No DLQ messages to delete", severity="warning")
            return

        msg = self._dlq_messages[0]

        async def _do_delete(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                aws = self.app.aws  # type: ignore[attr-defined]
                dlq_url = aws.get_queue_url(self._selected_dlq)
                if not dlq_url:
                    self.app.notify("Could not resolve DLQ URL", severity="error")
                    return

                await asyncio.to_thread(
                    aws.sqs.delete_message,
                    QueueUrl=dlq_url,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
                self._dlq_messages.pop(0)
                self.app.notify("Message deleted")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Delete failed: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Permanently delete first message from {self._selected_dlq}?"),
            _do_delete,
        )
