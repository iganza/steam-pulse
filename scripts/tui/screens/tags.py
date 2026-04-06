"""Tags & Genres screen — matview-backed tag/genre browser."""

import asyncio

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Static, TabbedContent, TabPane

from tui.queries import GENRES_LIST, GENRE_TOP_GAMES, MATVIEW_LAST_REFRESH, TAGS_LIST, TAG_TOP_GAMES
from tui.widgets.freshness import FreshnessLabel


class TagsGenresScreen(Widget):
    """Browse tags and genres with game counts."""

    DEFAULT_CSS = """
    TagsGenresScreen {
        height: 100%;
        layout: vertical;
    }

    #tags-header {
        height: 3;
        layout: horizontal;
        padding: 0 1;
    }

    #tags-tabs {
        height: 1fr;
    }

    #tag-detail-area {
        height: 12;
        border: round $accent;
        margin: 0 1;
        display: none;
    }

    #tag-detail-area.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("escape", "close_detail", "Close", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._tag_rows: list[dict] = []
        self._genre_rows: list[dict] = []

    def compose(self) -> ComposeResult:
        from textual.containers import Horizontal, Vertical

        with Horizontal(id="tags-header"):
            yield FreshnessLabel("Matview refresh", id="tags-freshness")
            yield Static(
                "  [dim]F5[/dim] Refresh matviews  [dim]Enter[/dim] Top games",
            )

        with TabbedContent(id="tags-tabs"):
            with TabPane("Tags", id="tags-tab"):
                yield DataTable(id="tags-table")
            with TabPane("Genres", id="genres-tab"):
                yield DataTable(id="genres-table")

        with Vertical(id="tag-detail-area"):
            yield Static("[bold]Top Games[/bold]", id="tag-detail-title")
            yield DataTable(id="tag-detail-table")

    def on_mount(self) -> None:
        tags_table = self.query_one("#tags-table", DataTable)
        tags_table.add_columns("Tag", "Category", "Games")
        tags_table.cursor_type = "row"

        genres_table = self.query_one("#genres-table", DataTable)
        genres_table.add_columns("Genre", "Games")
        genres_table.cursor_type = "row"

        detail_table = self.query_one("#tag-detail-table", DataTable)
        detail_table.add_columns("AppID", "Name", "Developer", "Reviews", "Pos%", "Sentiment")
        detail_table.show_cursor = False

        self.run_worker(self._load_data, exclusive=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        row_idx = event.cursor_row

        if table_id == "tags-table" and 0 <= row_idx < len(self._tag_rows):
            slug = self._tag_rows[row_idx].get("slug", "")
            name = self._tag_rows[row_idx].get("name", "")
            self.run_worker(self._load_tag_games(slug, name), exclusive=True)
        elif table_id == "genres-table" and 0 <= row_idx < len(self._genre_rows):
            slug = self._genre_rows[row_idx].get("slug", "")
            name = self._genre_rows[row_idx].get("name", "")
            self.run_worker(self._load_genre_games(slug, name), exclusive=True)

    def action_close_detail(self) -> None:
        self.query_one("#tag-detail-area").remove_class("visible")

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        if key == "f5":
            self._trigger_matview_refresh()

    def _trigger_matview_refresh(self) -> None:
        self.run_worker(self._do_matview_refresh, exclusive=True)

    async def _do_matview_refresh(self) -> None:
        """Refresh materialized views directly via DB connection."""
        try:
            import asyncio

            conn = self.app.db_conn  # type: ignore[attr-defined]
            if not conn:
                self.app.notify("No DB connection", severity="error")
                return

            self.app.notify("Refreshing materialized views...")
            await asyncio.to_thread(self._refresh_views, conn)
            self.app.notify("Matview refresh complete")
            await self._load_data()
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Matview refresh failed: {exc}", severity="error")

    @staticmethod
    def _refresh_views(conn: object) -> None:
        """Refresh all materialized views (sync, runs in thread)."""
        views = [
            "mv_genre_counts", "mv_tag_counts", "mv_genre_games", "mv_tag_games",
            "mv_price_positioning", "mv_release_timing", "mv_platform_distribution",
            "mv_tag_trend", "mv_price_summary",
        ]
        previous_autocommit = conn.autocommit  # type: ignore[union-attr]
        cur = None
        try:
            conn.autocommit = True  # type: ignore[union-attr]
            cur = conn.cursor()  # type: ignore[union-attr]
            start = __import__("time").monotonic()
            for view in views:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}")  # noqa: S608
            duration_ms = int((__import__("time").monotonic() - start) * 1000)
            # Log refresh to matview_refresh_log
            conn.autocommit = False  # type: ignore[union-attr]
            cur.execute(
                "INSERT INTO matview_refresh_log (refreshed_at, duration_ms, views_refreshed) "
                "VALUES (NOW(), %s, %s)",
                (duration_ms, views),
            )
            conn.commit()  # type: ignore[union-attr]
        finally:
            if cur is not None:
                cur.close()
            conn.autocommit = previous_autocommit  # type: ignore[union-attr]

    async def _load_data(self) -> None:
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn:
            return

        try:
            tags, genres, refresh = await asyncio.gather(
                asyncio.to_thread(self._query_all, conn, TAGS_LIST),
                asyncio.to_thread(self._query_all, conn, GENRES_LIST),
                asyncio.to_thread(self._query_one, conn, MATVIEW_LAST_REFRESH),
            )

            self._tag_rows = tags or []
            self._genre_rows = genres or []

            tags_table = self.query_one("#tags-table", DataTable)
            tags_table.clear()
            for row in self._tag_rows:
                tags_table.add_row(
                    row.get("name", ""),
                    row.get("category", ""),
                    f"{row.get('game_count', 0):,}",
                )

            genres_table = self.query_one("#genres-table", DataTable)
            genres_table.clear()
            for row in self._genre_rows:
                genres_table.add_row(
                    row.get("name", ""),
                    f"{row.get('game_count', 0):,}",
                )

            if refresh:
                self.query_one("#tags-freshness", FreshnessLabel).timestamp = refresh.get(
                    "last_refresh"
                )
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Query error: {exc}", severity="error")

    async def _load_tag_games(self, slug: str, name: str) -> None:
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn:
            return

        try:
            rows = await asyncio.to_thread(self._query_all, conn, TAG_TOP_GAMES, (slug,))
            self._show_top_games(rows or [], f"Top Games — Tag: {name}")
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Query error: {exc}", severity="error")

    async def _load_genre_games(self, slug: str, name: str) -> None:
        conn = self.app.db_conn  # type: ignore[attr-defined]
        if not conn:
            return

        try:
            rows = await asyncio.to_thread(self._query_all, conn, GENRE_TOP_GAMES, (slug,))
            self._show_top_games(rows or [], f"Top Games — Genre: {name}")
        except Exception as exc:  # noqa: BLE001
            self.app.notify(f"Query error: {exc}", severity="error")

    def _show_top_games(self, rows: list[dict], title: str) -> None:
        self.query_one("#tag-detail-title", Static).update(f"[bold]{title}[/bold]")
        table = self.query_one("#tag-detail-table", DataTable)
        table.clear()
        for row in rows:
            table.add_row(
                str(row.get("appid", "")),
                (row.get("name", "") or "")[:35],
                (row.get("developer", "") or "")[:20],
                f"{row.get('review_count', 0):,}",
                f"{row.get('positive_pct', 0):.0f}%",
                f"{row.get('sentiment_score', 0):.2f}" if row.get("sentiment_score") else "--",
            )
        self.query_one("#tag-detail-area").add_class("visible")

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
