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
    "metadata-dlq": "app-crawl-queue",
    "review-dlq": "review-crawl-queue",
    "spoke-results-dlq": "spoke-results-queue",
    "cache-dlq": "cache-invalidation-queue",
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
        Binding("escape", "close_inspector", "Close", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._queue_names: list[str] = []
        self._dlq_messages: list[dict] = []
        self._selected_dlq: str | None = None

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
        table.add_columns("Queue", "Messages", "In Flight", "Type")
        table.cursor_type = "row"

        if self.app.aws_available:  # type: ignore[attr-defined]
            self.set_interval(10, self._auto_refresh)
            self.run_worker(self._load_queues, exclusive=True)
        else:
            table.add_row("[dim]Connect with --env for AWS ops[/dim]", "", "", "")

    def action_refresh(self) -> None:
        if self.app.aws_available:  # type: ignore[attr-defined]
            self.run_worker(self._load_queues, exclusive=True)

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

    async def _auto_refresh(self) -> None:
        if self.app.aws_available:  # type: ignore[attr-defined]
            self.run_worker(self._load_queues, exclusive=True)

    async def _load_queues(self) -> None:
        try:
            depths = await asyncio.to_thread(
                self.app.aws.get_all_queue_depths  # type: ignore[attr-defined]
            )

            self._queue_names = list(depths.keys())
            table = self.query_one("#queues-table", DataTable)
            table.clear()

            for name, info in depths.items():
                msgs = str(info["messages"]) if info["messages"] >= 0 else "?"
                inflight = str(info["in_flight"]) if info["in_flight"] >= 0 else "?"
                qtype = "[red]DLQ[/red]" if "dlq" in name else "Queue"
                warning = ""
                if "dlq" in name and info["messages"] > 0:
                    warning = " \u26a0"
                table.add_row(f"{name}{warning}", msgs, inflight, qtype)

            total_dlq = sum(
                v["messages"]
                for k, v in depths.items()
                if "dlq" in k and v["messages"] > 0
            )
            status = f"  {len(depths)} queues"
            if total_dlq > 0:
                status += f"  \u2502  [red]{total_dlq} DLQ messages[/red]"
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
                VisibilityTimeout=0,
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
