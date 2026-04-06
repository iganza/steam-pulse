"""KPI card widget — large count with label."""

from textual.reactive import reactive
from textual.widgets import Static


class KpiCard(Static):
    """Displays a large numeric value with a label underneath."""

    DEFAULT_CSS = """
    KpiCard {
        height: 5;
        min-width: 20;
        border: round $primary;
        content-align: center middle;
        padding: 0 2;
    }
    """

    value: reactive[str] = reactive("--")
    label_text: reactive[str] = reactive("")

    def __init__(self, label: str, value: str = "--", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.label_text = label
        self.value = value

    def render(self) -> str:
        return f"[bold]{self.value}[/bold]\n{self.label_text}"

    def watch_value(self) -> None:
        self.refresh()
