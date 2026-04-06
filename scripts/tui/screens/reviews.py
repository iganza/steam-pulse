"""Reviews browser screen — browse reviews per game."""

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static

from tui.queries import REVIEWS_LIST, REVIEW_STATS

PAGE_SIZE = 50


class ReviewDetailPanel(VerticalScroll):
    """Panel showing full review body text."""

    DEFAULT_CSS = """
    ReviewDetailPanel {
        height: 15;
        border: round $accent;
        padding: 1 2;
        margin: 0 1;
        display: none;
    }

    ReviewDetailPanel.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="review-body-content")


class ReviewsBrowserScreen(Widget):
    """Browse reviews for a specific game with stats."""

    DEFAULT_CSS = """
    ReviewsBrowserScreen {
        height: 100%;
        layout: vertical;
    }

    #reviews-appid-bar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
    }

    #reviews-appid {
        width: 20;
    }

    #reviews-stats {
        width: 1fr;
        content-align: left middle;
        padding-left: 2;
    }

    #reviews-table-area {
        height: 1fr;
        margin: 0 1;
    }

    #reviews-status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("pageup", "prev_page", "Prev Page", show=False),
        Binding("pagedown", "next_page", "Next Page", show=False),
        Binding("escape", "close_detail", "Close", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._appid: int | None = None
        self._offset = 0
        self._total = 0
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal

        with Horizontal(id="reviews-appid-bar"):
            yield Input(placeholder="Enter appid...", id="reviews-appid", type="integer")
            yield Static("[dim]Enter an appid to browse reviews[/dim]", id="reviews-stats")

        with Vertical(id="reviews-table-area"):
            yield DataTable(id="reviews-table")

        yield ReviewDetailPanel(id="review-detail")
        yield Static("", id="reviews-status")

    def on_mount(self) -> None:
        table = self.query_one("#reviews-table", DataTable)
        table.add_columns(
            "Steam ID", "Vote", "Playtime", "Posted", "Lang",
            "Helpful", "Funny", "EA", "Body",
        )
        table.cursor_type = "row"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "reviews-appid":
            try:
                self._appid = int(event.value.strip())
            except ValueError:
                self.app.notify("Invalid appid", severity="warning")
                return
            self._offset = 0
            self.run_worker(self._load_reviews, exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._rows):
            body = self._rows[row_idx].get("body_preview", "")
            # For full body, we'd query REVIEW_FULL_BODY — using preview for now
            panel = self.query_one("#review-detail", ReviewDetailPanel)
            panel.query_one("#review-body-content", Static).update(body)
            panel.add_class("visible")

    def action_close_detail(self) -> None:
        self.query_one("#review-detail").remove_class("visible")

    def action_prev_page(self) -> None:
        if self._offset >= PAGE_SIZE:
            self._offset -= PAGE_SIZE
            self.run_worker(self._load_reviews, exclusive=True)

    def action_next_page(self) -> None:
        if self._offset + PAGE_SIZE < self._total:
            self._offset += PAGE_SIZE
            self.run_worker(self._load_reviews, exclusive=True)

    async def _load_reviews(self) -> None:
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn or not self._appid:
            return

        try:
            stats, rows = await asyncio.gather(
                asyncio.to_thread(self._query_one, conn, REVIEW_STATS, (self._appid,)),
                asyncio.to_thread(
                    self._query_all,
                    conn,
                    REVIEWS_LIST.format(sort="votes_helpful DESC", limit=PAGE_SIZE, offset=self._offset),
                    (self._appid,),
                ),
            )

            self._rows = rows or []
            self._total = stats["total"] if stats else 0

            if stats and stats["total"] > 0:
                self.query_one("#reviews-stats", Static).update(
                    f"Total: [bold]{stats['total']:,}[/bold]  \u2502  "
                    f"Positive: {stats.get('positive_pct', 0)}%  \u2502  "
                    f"Avg Playtime: {stats.get('avg_playtime', 0)}h  \u2502  "
                    f"EA: {stats.get('ea_pct', 0)}%  \u2502  "
                    f"Last: {str(stats.get('last_review', '--'))[:10]}"
                )
            else:
                self.query_one("#reviews-stats", Static).update("[dim]No reviews found[/dim]")

            table = self.query_one("#reviews-table", DataTable)
            table.clear()
            for row in self._rows:
                table.add_row(
                    str(row.get("steam_review_id", "")),
                    "\u2713" if row.get("voted_up") else "\u2717",
                    f"{row.get('playtime_hours', 0):.0f}h",
                    str(row.get("posted_at", "--"))[:10],
                    str(row.get("language", ""))[:5],
                    str(row.get("votes_helpful", 0)),
                    str(row.get("votes_funny", 0)),
                    "\u2713" if row.get("written_during_early_access") else "",
                    str(row.get("body_preview", "")),
                )

            page = self._offset // PAGE_SIZE + 1
            total_pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
            self.query_one("#reviews-status", Static).update(
                f"  {self._total:,} reviews  \u2502  Page {page}/{total_pages}"
            )
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Query error: {exc}", severity="error")

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
