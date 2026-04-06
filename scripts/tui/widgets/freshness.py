"""Freshness label widget — shows relative time with color coding."""

from datetime import datetime, timezone

from textual.reactive import reactive
from textual.widgets import Static


def _format_age(dt: datetime | None) -> tuple[str, str]:
    """Format a datetime as relative time and return (text, color)."""
    if dt is None:
        return "never", "dim"
    now = datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now", "green"
    if seconds < 60:
        text = f"{seconds}s ago"
    elif seconds < 3600:
        text = f"{seconds // 60}m ago"
    elif seconds < 86400:
        text = f"{seconds // 3600}h ago"
    else:
        text = f"{seconds // 86400}d ago"

    if seconds < 3600:
        color = "green"
    elif seconds < 86400:
        color = "yellow"
    else:
        color = "red"
    return text, color


class FreshnessLabel(Static):
    """Displays a label with a relative timestamp, color-coded by freshness."""

    timestamp: reactive[datetime | None] = reactive(None)

    def __init__(
        self, label: str, timestamp: datetime | None = None, **kwargs: object
    ) -> None:
        super().__init__(**kwargs)
        self.label_text = label
        self.timestamp = timestamp

    def render(self) -> str:
        text, color = _format_age(self.timestamp)
        return f"{self.label_text}: [{color}]{text}[/{color}]"

    def watch_timestamp(self) -> None:
        self.refresh()
