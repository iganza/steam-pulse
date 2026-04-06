"""Pipeline funnel widget — tree-style pipeline status display."""

from textual.reactive import reactive
from textual.widgets import Static


class PipelineFunnel(Static):
    """Renders the crawl pipeline funnel as a tree."""

    DEFAULT_CSS = """
    PipelineFunnel {
        height: auto;
        padding: 1 2;
        border: round $primary;
    }
    """

    data: reactive[dict] = reactive(dict)

    def __init__(self, data: dict | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        if data:
            self.data = data

    def render(self) -> str:
        d = self.data
        if not d:
            return "[dim]Loading pipeline status...[/dim]"

        total = d.get("total", 0)
        reports = d.get("reports", 0)

        lines = [
            f"[bold]Catalog Entries:[/bold]  {total:,}",
            f"\u251c\u2500 Meta Pending:    {d.get('meta_pending', 0):,}",
            f"\u251c\u2500 Meta Done:       {d.get('meta_done', 0):,}",
            f"\u251c\u2500 Meta Failed:     {d.get('meta_failed', 0):,}",
            f"\u251c\u2500 Meta Skipped:    {d.get('meta_skipped', 0):,}",
            f"\u251c\u2500 Reviews Done:    {d.get('reviews_done', 0):,}",
            f"\u251c\u2500 Tags Crawled:    {d.get('tags_crawled', 0):,}",
            f"\u2514\u2500 Analyzed:        {reports:,}",
        ]
        return "\n".join(lines)

    def watch_data(self) -> None:
        self.refresh()
