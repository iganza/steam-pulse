"""Games browser screen — searchable, filterable game table with detail panel."""

import asyncio
import json
import webbrowser

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Input, Static

from tui.queries import GAME_DETAIL, GAME_REPORT_SUMMARY, GAME_REVIEW_COUNT, GAMES_COUNT, GAMES_LIST
from tui.widgets.confirm_dialog import ConfirmDialog

# ── Filter definitions ─────────────────────────────────────────────────────────

FILTERS: dict[str, tuple[str, str]] = {
    "f1": ("No report", "r.appid IS NULL"),
    "f2": ("Stale report", "r.last_analyzed < NOW() - INTERVAL '30 days'"),
    "f3": ("Never crawled", "g.crawled_at IS NULL"),
    "f4": ("Has reviews", "g.review_count > 0"),
    "f5": ("Failed meta", "EXISTS (SELECT 1 FROM app_catalog ac WHERE ac.appid = g.appid AND ac.meta_status = 'failed')"),
}

SORT_COLUMNS: dict[str, str] = {
    "review_count": "g.review_count DESC",
    "name": "g.name ASC",
    "positive_pct": "g.positive_pct DESC",
    "sentiment_score": "g.sentiment_score DESC NULLS LAST",
    "price_usd": "g.price_usd DESC NULLS LAST",
    "release_date": "g.release_date DESC NULLS LAST",
    "crawled_at": "g.crawled_at DESC NULLS LAST",
    "last_analyzed": "g.last_analyzed DESC NULLS LAST",
}

PAGE_SIZE = 50


class GameDetailPanel(VerticalScroll):
    """Right-side panel showing game detail info."""

    DEFAULT_CSS = """
    GameDetailPanel {
        width: 50;
        border-left: solid $primary;
        padding: 1 2;
        display: none;
    }

    GameDetailPanel.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="detail-content")
        yield Static(
            "\n[dim]1[/dim] crawl meta  [dim]2[/dim] crawl reviews  "
            "[dim]3[/dim] crawl tags  [dim]4[/dim] analyze  [dim]o[/dim] open Steam  "
            "[dim]Esc[/dim] close",
            id="detail-actions",
        )


class GamesBrowserScreen(Widget):
    """Searchable/sortable/filterable game data table."""

    DEFAULT_CSS = """
    GamesBrowserScreen {
        height: 100%;
    }

    #games-toolbar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
    }

    #games-search {
        width: 40;
    }

    #games-filters {
        width: 1fr;
        height: 3;
        content-align: left middle;
        padding-left: 2;
    }

    #games-status {
        dock: bottom;
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }

    #games-main {
        layout: horizontal;
        height: 1fr;
    }

    #games-table-area {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("slash", "focus_search", "Search", show=False),
        Binding("pageup", "prev_page", "Prev Page", show=False),
        Binding("pagedown", "next_page", "Next Page", show=False),
        Binding("escape", "close_detail", "Close Detail", show=False),
        Binding("1", "crawl_meta", "Crawl Meta", show=False),
        Binding("2", "crawl_reviews", "Crawl Reviews", show=False),
        Binding("3", "crawl_tags", "Crawl Tags", show=False),
        Binding("4", "analyze_game", "Analyze", show=False),
        Binding("o", "open_steam", "Open Steam", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._search_text = ""
        self._active_filters: set[str] = set()
        self._sort = "review_count"
        self._offset = 0
        self._total = 0
        self._selected_appid: int | None = None
        self._rows: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="games-toolbar"):
            yield Input(placeholder="/ to search...", id="games-search")
            yield Static(
                "[dim]/[/dim] search  [dim]F1[/dim] No report  [dim]F2[/dim] Stale  "
                "[dim]F3[/dim] Not crawled  [dim]F4[/dim] Has reviews  "
                "[dim]F5[/dim] Failed",
                id="games-filters",
            )

        with Horizontal(id="games-main"):
            with Vertical(id="games-table-area"):
                yield DataTable(id="games-table")
            yield GameDetailPanel(id="game-detail")

        yield Static("", id="games-status")

    def on_mount(self) -> None:
        table = self.query_one("#games-table", DataTable)
        table.add_columns(
            "AppID", "Name", "Reviews", "Pos%", "Sentiment",
            "Price", "Released", "Crawled", "Analyzed", "Report",
        )
        table.cursor_type = "row"
        self.run_worker(self._load_games, exclusive=True)

    def action_focus_search(self) -> None:
        self.query_one("#games-search", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "games-search":
            self._search_text = event.value.strip()
            self._offset = 0
            self.run_worker(self._load_games, exclusive=True)

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        if key in ("f1", "f2", "f3", "f4", "f5"):
            if key in self._active_filters:
                self._active_filters.discard(key)
            else:
                self._active_filters.add(key)
            self._offset = 0
            self._update_filter_display()
            self.run_worker(self._load_games, exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._rows):
            appid = self._rows[row_idx]["appid"]
            self._selected_appid = appid
            self.run_worker(self._load_detail, exclusive=True)

    def action_prev_page(self) -> None:
        if self._offset >= PAGE_SIZE:
            self._offset -= PAGE_SIZE
            self.run_worker(self._load_games, exclusive=True)

    def action_next_page(self) -> None:
        if self._offset + PAGE_SIZE < self._total:
            self._offset += PAGE_SIZE
            self.run_worker(self._load_games, exclusive=True)

    def action_close_detail(self) -> None:
        panel = self.query_one("#game-detail", GameDetailPanel)
        panel.remove_class("visible")
        self._selected_appid = None

    def action_open_steam(self) -> None:
        if self._selected_appid:
            webbrowser.open(f"https://store.steampowered.com/app/{self._selected_appid}")

    def action_crawl_meta(self) -> None:
        if not self._selected_appid or not self.app.aws_available:  # type: ignore[attr-defined]
            return

        async def _do_crawl(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                from library_layer.events import GameDiscoveredEvent

                event = GameDiscoveredEvent(appid=self._selected_appid)
                await asyncio.to_thread(
                    self.app.aws.publish_event, "game-events", event  # type: ignore[attr-defined]
                )
                self.app.notify(f"Queued metadata crawl for {self._selected_appid}")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Crawl metadata for appid {self._selected_appid}?"),
            _do_crawl,
        )

    def action_crawl_reviews(self) -> None:
        if not self._selected_appid or not self.app.aws_available:  # type: ignore[attr-defined]
            return

        appid = self._selected_appid

        async def _do_crawl(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                import json

                msg = json.dumps({"appid": appid, "target": 5000})
                await asyncio.to_thread(
                    self.app.aws.send_sqs_message, "review-crawl-queue", msg  # type: ignore[attr-defined]
                )
                self.app.notify(f"Queued review crawl for {appid}")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Crawl reviews for appid {appid}?"),
            _do_crawl,
        )

    def action_crawl_tags(self) -> None:
        if not self._selected_appid or not self.app.aws_available:  # type: ignore[attr-defined]
            return

        appid = self._selected_appid

        async def _do_crawl(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                import json

                msg = json.dumps({"appid": appid, "task": "tags"})
                await asyncio.to_thread(
                    self.app.aws.send_sqs_message, "app-crawl-queue", msg  # type: ignore[attr-defined]
                )
                self.app.notify(f"Queued tag crawl for {appid}")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Crawl tags for appid {appid}?"),
            _do_crawl,
        )

    def action_analyze_game(self) -> None:
        if not self._selected_appid or not self.app.aws_available:  # type: ignore[attr-defined]
            return

        appid = self._selected_appid

        async def _do_analyze(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                import json

                input_json = json.dumps({"appid": appid})
                await asyncio.to_thread(
                    self.app.aws.start_sfn_execution, input_json  # type: ignore[attr-defined]
                )
                self.app.notify(f"Started analysis for {appid}")
            except Exception as exc:  # noqa: BLE001
                self.app.notify(f"Error: {exc}", severity="error")

        self.app.push_screen(
            ConfirmDialog(f"Start analysis for appid {appid}?"),
            _do_analyze,
        )

    def _update_filter_display(self) -> None:
        parts = []
        for key, (label, _) in FILTERS.items():
            if key in self._active_filters:
                parts.append(f"[bold green]{key.upper()}[/bold green] {label}")
            else:
                parts.append(f"[dim]{key.upper()}[/dim] {label}")
        self.query_one("#games-filters", Static).update("  ".join(parts))

    def _build_where(self) -> str:
        """Build WHERE clause from search text and active filters."""
        conditions: list[str] = []
        if self._search_text:
            conditions.append("g.name ILIKE %(search)s")
        for key in self._active_filters:
            if key in FILTERS:
                conditions.append(FILTERS[key][1])
        if not conditions:
            return ""
        return "WHERE " + " AND ".join(conditions)

    async def _load_games(self) -> None:
        """Load games list from DB."""
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn:
            return

        where = self._build_where()
        sort_sql = SORT_COLUMNS.get(self._sort, "g.review_count DESC")

        try:
            count_sql = GAMES_COUNT.format(where=where)
            list_sql = GAMES_LIST.format(
                where=where, sort=sort_sql, limit=PAGE_SIZE, offset=self._offset
            )
            params = {"search": f"%{self._search_text}%"} if self._search_text else None

            total_row, rows = await asyncio.gather(
                asyncio.to_thread(self._query_one, conn, count_sql, params),
                asyncio.to_thread(self._query_all, conn, list_sql, params),
            )

            self._total = total_row["total"] if total_row else 0
            self._rows = rows or []

            table = self.query_one("#games-table", DataTable)
            table.clear()
            for row in self._rows:
                table.add_row(
                    str(row["appid"]),
                    (row["name"] or "")[:40],
                    f"{row['review_count'] or 0:,}",
                    f"{row['positive_pct'] or 0:.0f}%",
                    f"{row['sentiment_score']:.2f}" if row.get("sentiment_score") else "--",
                    "Free"
                    if row.get("price_usd") == 0
                    else "--"
                    if row.get("price_usd") is None
                    else f"${row['price_usd']:.2f}",
                    str(row["release_date"] or "--")[:10],
                    str(row["crawled_at"] or "--")[:10],
                    str(row["last_analyzed"] or "--")[:10],
                    "\u2713" if row.get("has_report") else "",
                )

            page = self._offset // PAGE_SIZE + 1
            total_pages = max(1, (self._total + PAGE_SIZE - 1) // PAGE_SIZE)
            self.query_one("#games-status", Static).update(
                f"  {self._total:,} games  \u2502  Page {page}/{total_pages}  "
                f"\u2502  PgUp/PgDn to navigate  \u2502  Enter for detail"
            )
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Query error: {exc}", severity="error")

    async def _load_detail(self) -> None:
        """Load detail for the selected game."""
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn or not self._selected_appid:
            return

        try:
            game, report, review_count = await asyncio.gather(
                asyncio.to_thread(self._query_one, conn, GAME_DETAIL, (self._selected_appid,)),
                asyncio.to_thread(
                    self._query_one, conn, GAME_REPORT_SUMMARY, (self._selected_appid,)
                ),
                asyncio.to_thread(
                    self._query_one, conn, GAME_REVIEW_COUNT, (self._selected_appid,)
                ),
            )

            if not game:
                return

            platforms = ""
            if game.get("platforms"):
                p = game["platforms"]
                if isinstance(p, str):
                    p = json.loads(p)
                parts = []
                if p.get("windows"):
                    parts.append("Win \u2713")
                if p.get("mac"):
                    parts.append("Mac \u2713")
                if p.get("linux"):
                    parts.append("Linux \u2713")
                platforms = "  ".join(parts)

            if game.get("is_free"):
                price_display = "Free"
            else:
                price_usd = game.get("price_usd")
                price_display = "--" if price_usd is None else f"${price_usd:.2f}"

            lines = [
                f"[bold]\u2550\u2550\u2550 {game['name']} ({game['appid']}) \u2550\u2550\u2550[/bold]",
                "",
                f"Developer:    {game.get('developer', '--')}",
                f"Publisher:    {game.get('publisher', '--')}",
                f"Released:     {str(game.get('release_date', '--'))[:10]}",
                f"Price:        {price_display}",
                f"Platforms:    {platforms or '--'}",
                "",
                "[bold]\u2500\u2500 Crawl Status \u2500\u2500[/bold]",
                f"Metadata:     {game.get('meta_status', '--')} ({str(game.get('meta_crawled_at', '--'))[:19]})",
                f"Reviews:      {review_count['count'] if review_count else 0:,} in DB / {game.get('review_count', 0):,} on Steam",
                f"Tags:         {str(game.get('tags_crawled_at', 'never'))[:19]}",
                f"Analysis:     {str(game.get('last_analyzed', 'never'))[:19]}",
            ]

            if game.get("sentiment_score") is not None:
                lines.extend([
                    "",
                    "[bold]\u2500\u2500 Scores \u2500\u2500[/bold]",
                    f"Sentiment:    {game['sentiment_score']:.2f}",
                    f"Hidden Gem:   {game.get('hidden_gem_score', '--')}",
                ])

            if report:
                lines.extend([
                    "",
                    "[bold]\u2500\u2500 Report \u2500\u2500[/bold]",
                    f"One-liner:    {report.get('one_liner', '--')}",
                    f"Sentiment:    {report.get('overall_sentiment', '--')}",
                    f"Strengths:    {report.get('strengths_count', 0)} items",
                    f"Friction:     {report.get('friction_count', 0)} items",
                    f"Tech Issues:  {report.get('tech_issues_count', 0)} items",
                ])

            panel = self.query_one("#game-detail", GameDetailPanel)
            panel.query_one("#detail-content", Static).update("\n".join(lines))
            panel.add_class("visible")

        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Detail error: {exc}", severity="error")

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
