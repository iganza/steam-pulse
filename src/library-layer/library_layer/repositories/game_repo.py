"""GameRepository — pure SQL I/O for the games table."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar

import psycopg2
from aws_lambda_powertools import Logger

from library_layer.models.game import Game
from library_layer.repositories.base import BaseRepository
from library_layer.repositories.tag_repo import TAG_CATEGORY_ORDER

logger = Logger()

EARLY_ACCESS_GENRE_ID = 70


class GameNotFound(Exception):
    """Raised when a game cannot be found by appid."""

    def __init__(self, appid: int) -> None:
        self.appid = appid
        super().__init__(f"Game not found: appid={appid}")


class GameRepository(BaseRepository):
    """CRUD operations for the games table."""

    def upsert(self, game_data: dict) -> None:
        """INSERT ... ON CONFLICT (appid) DO UPDATE with all game columns."""
        sql = """
            INSERT INTO games (
                appid, name, slug, type, developer, developer_slug, publisher, publisher_slug,
                developers, publishers,
                website, release_date, release_date_raw, coming_soon, price_usd, is_free,
                short_desc, detailed_description, about_the_game,
                review_count, review_count_english, total_positive, total_negative, positive_pct,
                review_score_desc, header_image, background_image,
                required_age, platforms, supported_languages,
                achievements_total, metacritic_score,
                deck_compatibility, deck_test_results,
                content_descriptor_ids, content_descriptor_notes, controller_support,
                dlc_appids, parent_appid, capsule_image,
                recommendations_total,
                support_url, support_email, legal_notice,
                requirements_windows, requirements_mac, requirements_linux,
                crawled_at, data_source
            ) VALUES (
                %(appid)s, %(name)s, %(slug)s, %(type)s, %(developer)s, %(developer_slug)s,
                %(publisher)s, %(publisher_slug)s,
                %(developers)s, %(publishers)s,
                %(website)s, %(release_date)s, %(release_date_raw)s, %(coming_soon)s, %(price_usd)s, %(is_free)s,
                %(short_desc)s, %(detailed_description)s, %(about_the_game)s,
                %(review_count)s, %(review_count_english)s, %(total_positive)s, %(total_negative)s, %(positive_pct)s,
                %(review_score_desc)s, %(header_image)s,
                %(background_image)s, %(required_age)s, %(platforms)s,
                %(supported_languages)s, %(achievements_total)s, %(metacritic_score)s,
                %(deck_compatibility)s, %(deck_test_results)s,
                %(content_descriptor_ids)s, %(content_descriptor_notes)s, %(controller_support)s,
                %(dlc_appids)s, %(parent_appid)s, %(capsule_image)s,
                %(recommendations_total)s,
                %(support_url)s, %(support_email)s, %(legal_notice)s,
                %(requirements_windows)s, %(requirements_mac)s, %(requirements_linux)s,
                NOW(), %(data_source)s
            )
            ON CONFLICT (appid) DO UPDATE SET
                name                     = EXCLUDED.name,
                slug                     = EXCLUDED.slug,
                type                     = EXCLUDED.type,
                developer                = EXCLUDED.developer,
                developer_slug           = EXCLUDED.developer_slug,
                publisher                = EXCLUDED.publisher,
                publisher_slug           = EXCLUDED.publisher_slug,
                developers               = EXCLUDED.developers,
                publishers               = EXCLUDED.publishers,
                website                  = EXCLUDED.website,
                release_date             = EXCLUDED.release_date,
                release_date_raw         = EXCLUDED.release_date_raw,
                coming_soon              = EXCLUDED.coming_soon,
                price_usd                = EXCLUDED.price_usd,
                is_free                  = EXCLUDED.is_free,
                short_desc               = EXCLUDED.short_desc,
                detailed_description     = EXCLUDED.detailed_description,
                about_the_game           = EXCLUDED.about_the_game,
                review_count             = EXCLUDED.review_count,
                review_count_english     = EXCLUDED.review_count_english,
                total_positive           = EXCLUDED.total_positive,
                total_negative           = EXCLUDED.total_negative,
                positive_pct             = EXCLUDED.positive_pct,
                review_score_desc        = EXCLUDED.review_score_desc,
                header_image             = EXCLUDED.header_image,
                background_image         = EXCLUDED.background_image,
                required_age             = EXCLUDED.required_age,
                platforms                = EXCLUDED.platforms,
                supported_languages      = EXCLUDED.supported_languages,
                achievements_total       = EXCLUDED.achievements_total,
                metacritic_score         = EXCLUDED.metacritic_score,
                deck_compatibility       = EXCLUDED.deck_compatibility,
                deck_test_results        = EXCLUDED.deck_test_results,
                content_descriptor_ids   = EXCLUDED.content_descriptor_ids,
                content_descriptor_notes = EXCLUDED.content_descriptor_notes,
                controller_support       = EXCLUDED.controller_support,
                dlc_appids               = EXCLUDED.dlc_appids,
                parent_appid             = EXCLUDED.parent_appid,
                capsule_image            = EXCLUDED.capsule_image,
                recommendations_total    = EXCLUDED.recommendations_total,
                support_url              = EXCLUDED.support_url,
                support_email            = EXCLUDED.support_email,
                legal_notice             = EXCLUDED.legal_notice,
                requirements_windows     = EXCLUDED.requirements_windows,
                requirements_mac         = EXCLUDED.requirements_mac,
                requirements_linux       = EXCLUDED.requirements_linux,
                crawled_at               = NOW(),
                data_source              = EXCLUDED.data_source
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, game_data)
        self.conn.commit()

    # SELECT shared between find_by_appid and find_by_slug — joins app_catalog so that
    # callers (notably the /api/games/{appid}/report endpoint) can surface per-source
    # freshness timestamps in the UI.
    _GAME_SELECT_WITH_FRESHNESS = """
        SELECT g.*,
               ac.meta_crawled_at,
               ac.review_crawled_at,
               ac.reviews_completed_at,
               ac.tags_crawled_at
        FROM games g
        LEFT JOIN app_catalog ac ON ac.appid = g.appid
    """

    def find_by_appid(self, appid: int) -> Game | None:
        row = self._fetchone(
            f"{self._GAME_SELECT_WITH_FRESHNESS} WHERE g.appid = %s",
            (appid,),
        )
        if row is None:
            return None
        return Game.model_validate(dict(row))

    def find_event_snapshot(self, appid: int) -> dict | None:
        """Minimal pre-upsert snapshot for event detection (coming_soon flip, price change,
        review milestone crossings) plus inline review-crawl dispatch gating. Avoids the
        wide TOAST-heavy row that find_by_appid returns, which is the right read for API
        handlers but wasteful on hot refresh paths.

        Includes app_catalog.review_crawled_at and review_count_at_last_fetch via LEFT
        JOIN so _maybe_dispatch_review_crawl can mirror find_due_reviews()'s WHERE clause
        in Python without a second roundtrip. The LEFT JOIN preserves snapshot semantics
        for games that lack an app_catalog row — both columns simply come back as None.
        """
        row = self._fetchone(
            "SELECT g.coming_soon, g.price_usd, g.review_count, g.review_count_english, "
            "       c.review_crawled_at, c.review_count_at_last_fetch "
            "FROM games g LEFT JOIN app_catalog c USING (appid) "
            "WHERE g.appid = %s",
            (appid,),
        )
        return dict(row) if row else None

    def get_by_appid(self, appid: int) -> Game:
        """Return the game, raising GameNotFound if it does not exist."""
        game = self.find_by_appid(appid)
        if game is None:
            raise GameNotFound(appid)
        return game

    def find_by_slug(self, slug: str) -> Game | None:
        row = self._fetchone(
            f"{self._GAME_SELECT_WITH_FRESHNESS} WHERE g.slug = %s",
            (slug,),
        )
        if row is None:
            return None
        return Game.model_validate(dict(row))

    def find_for_revenue_estimate(self, appid: int) -> Game | None:
        """Lightweight SELECT of only the columns `compute_estimate` needs.

        Avoids the full `g.* + LEFT JOIN app_catalog` cost of `find_by_appid`
        in hot loops like `process_results` where we touch every analyzed game.
        """
        row = self._fetchone(
            """
            SELECT appid, name, slug, type, price_usd, is_free, review_count, release_date
            FROM games
            WHERE appid = %s
            """,
            (appid,),
        )
        if row is None:
            return None
        return Game.model_validate(dict(row))

    def find_eligible_for_reviews(self, min_reviews: int = 500) -> list[Game]:
        rows = self._fetchall(
            "SELECT * FROM games WHERE review_count >= %s ORDER BY review_count DESC",
            (min_reviews,),
        )
        return [Game.model_validate(dict(r)) for r in rows]

    def get_review_count(self, appid: int) -> int:
        """Return the current review_count stored for an appid (0 if missing)."""
        row = self._fetchone("SELECT review_count FROM games WHERE appid = %s", (appid,))
        if row is None or row["review_count"] is None:
            return 0
        return int(row["review_count"])

    def update_review_stats(
        self,
        appid: int,
        total_positive: int,
        total_negative: int,
        review_count: int,
        review_score_desc: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE games
                SET total_positive    = %s,
                    total_negative    = %s,
                    review_count      = %s,
                    positive_pct      = CASE WHEN %s > 0
                                            THEN ROUND(%s::numeric / %s * 100)
                                            ELSE NULL END,
                    review_score_desc = %s
                WHERE appid = %s
                """,
                (
                    total_positive,
                    total_negative,
                    review_count,
                    review_count,
                    total_positive,
                    review_count,
                    review_score_desc,
                    appid,
                ),
            )
        self.conn.commit()

    def ensure_stub(self, appid: int, name: str | None = None) -> None:
        """Insert a minimal stub row if the game does not exist yet (FK safety).

        If *name* is provided the slug is derived from it; otherwise defaults to
        ``App <appid>`` / ``app-<appid>``.
        """
        stub_name = name or f"App {appid}"
        stub_slug = f"app-{appid}"
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO games (appid, name, slug)
                VALUES (%s, %s, %s)
                ON CONFLICT (appid) DO NOTHING
                """,
                (appid, stub_name, stub_slug),
            )
        self.conn.commit()

    # Sort-implied filters: each leaderboard sort needs the column it orders by to
    # be non-null/meaningful, otherwise NULLS-LAST trailing rows inflate `total`
    # past the meaningful population (e.g. "Recently Analyzed" returning 150k
    # rows when only ~200 games have last_analyzed set). Thresholds mirror the
    # mv_discovery_feeds CTEs (top_rated.review_count >= 200 etc).
    @staticmethod
    def _sort_implied_filters(sort: str, prefix: str = "") -> list[str]:
        p = prefix
        if sort == "release_date":
            # Future-dated games slip past coming_soon=FALSE when Steam mislabels
            # them (e.g. appid 4062790 "Precursors: Reach for the Stars",
            # release_date=2028-11-30, coming_soon=false). Cap at CURRENT_DATE so
            # "Recently Released" actually means released-already.
            return [
                f"{p}coming_soon = FALSE",
                f"{p}release_date IS NOT NULL",
                f"{p}release_date <= CURRENT_DATE",
            ]
        if sort == "last_analyzed":
            return [f"{p}last_analyzed IS NOT NULL"]
        if sort in ("sentiment_score", "positive_pct"):
            return [f"{p}positive_pct IS NOT NULL", f"{p}review_count >= 200"]
        if sort == "hidden_gem_score":
            return [f"{p}hidden_gem_score IS NOT NULL", f"{p}hidden_gem_score > 0"]
        return []

    SORTS_WITH_IMPLIED_FILTERS: ClassVar[frozenset[str]] = frozenset(
        {"release_date", "last_analyzed", "sentiment_score", "positive_pct", "hidden_gem_score"}
    )

    @staticmethod
    def _build_game_filters(
        prefix: str = "",
        *,
        min_reviews: int | None = None,
        has_analysis: bool | None = None,
        sentiment: str | None = None,
        price_tier: str | None = None,
        deck_status: str | None = None,
    ) -> tuple[list[str], list[object]]:
        """Build shared SQL filter fragments for game listing (fast + slow path)."""
        conditions: list[str] = []
        params: list[object] = []
        p = prefix

        if min_reviews is not None:
            conditions.append(f"{p}review_count >= %s")
            params.append(min_reviews)
        if has_analysis:
            conditions.append(f"{p}last_analyzed IS NOT NULL")
        if sentiment:
            # Sentiment buckets are derived from Steam's positive_pct (0-100), not from any AI score
            if sentiment == "positive":
                conditions.append(f"{p}positive_pct >= 65")
            elif sentiment == "mixed":
                conditions.append(f"{p}positive_pct >= 45 AND {p}positive_pct < 65")
            elif sentiment == "negative":
                conditions.append(f"{p}positive_pct < 45")
        if price_tier:
            if price_tier == "free":
                conditions.append(f"{p}is_free = TRUE")
            elif price_tier == "under_10":
                conditions.append(
                    f"{p}price_usd < 10 AND ({p}is_free IS NULL OR {p}is_free = FALSE)"
                )
            elif price_tier == "10_to_20":
                conditions.append(f"{p}price_usd >= 10 AND {p}price_usd <= 20")
            elif price_tier == "over_20":
                conditions.append(f"{p}price_usd > 20")
        if deck_status:
            deck_map = {"verified": 3, "playable": 2, "unsupported": 1, "unknown": 0}
            deck_val = deck_map.get(deck_status)
            if deck_val is not None:
                conditions.append(f"{p}deck_compatibility = %s")
                params.append(deck_val)

        return conditions, params

    # Note: legacy `sentiment_score` wire value is mapped to `positive_pct DESC` so that
    # any in-the-wild bookmarks/links continue to sort sensibly without a coordinated
    # frontend rename. Steam's positive_pct is the only sentiment number we sort on.
    _MV_SORT_COLS: ClassVar[dict[str, str]] = {
        "review_count": "review_count DESC NULLS LAST",
        "hidden_gem_score": "hidden_gem_score DESC NULLS LAST",
        "sentiment_score": "positive_pct DESC NULLS LAST",
        "positive_pct": "positive_pct DESC NULLS LAST",
        "release_date": "release_date DESC NULLS LAST",
        "last_analyzed": "last_analyzed DESC NULLS LAST",
        "revenue_desc": "estimated_revenue_usd DESC NULLS LAST",
        "name": "name ASC",
    }

    def _list_from_matview(
        self,
        view: str,
        slug_col: str,
        slug_val: str,
        sort: str,
        limit: int,
        offset: int,
        *,
        min_reviews: int | None = None,
        has_analysis: bool | None = None,
        sentiment: str | None = None,
        price_tier: str | None = None,
        deck_status: str | None = None,
    ) -> dict:
        """Fast path: read from a pre-joined genre/tag materialized view."""
        order = self._MV_SORT_COLS.get(sort, self._MV_SORT_COLS["review_count"])
        conditions = [f"{slug_col} = %s"]
        params: list[object] = [slug_val]

        extra_conds, extra_params = self._build_game_filters(
            min_reviews=min_reviews,
            has_analysis=has_analysis,
            sentiment=sentiment,
            price_tier=price_tier,
            deck_status=deck_status,
        )
        conditions.extend(extra_conds)
        params.extend(extra_params)

        conditions.extend(self._sort_implied_filters(sort))

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        rows = self._fetchall(
            f"""
            SELECT appid, name, slug, developer, header_image,
                   review_count, review_count_english, positive_pct, review_score_desc,
                   price_usd, is_free,
                   release_date, deck_compatibility,
                   hidden_gem_score, last_analyzed, is_early_access,
                   estimated_owners, estimated_revenue_usd, revenue_estimate_method
            FROM {view}
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        result = []
        for row in rows:
            d = dict(row)
            if d.get("release_date"):
                d["release_date"] = str(d["release_date"])
            if d.get("estimated_revenue_usd") is not None:
                d["estimated_revenue_usd"] = float(d["estimated_revenue_usd"])
            result.append(d)
        return {"total": None, "games": result}

    def list_games(
        self,
        q: str | None = None,
        genre: str | None = None,
        tag: str | None = None,
        developer: str | None = None,
        publisher: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        min_reviews: int | None = None,
        has_analysis: bool | None = None,
        sentiment: str | None = None,
        price_tier: str | None = None,
        deck_status: str | None = None,
        sort: str = "review_count",
        limit: int = 24,
        offset: int = 0,
        # Legacy compat
        search: str | None = None,
    ) -> dict:
        """Parameterised query with optional WHERE clauses.

        Returns dict with 'total' (always None — callers provide the count
        from matviews or estimates) and 'games' list.

        For simple genre-only or tag-only browsing, queries pre-joined
        materialized views (mv_genre_games / mv_tag_games) to avoid
        expensive nested-loop joins on cold cache.
        """
        # Fast path: genre or tag filter with matview-compatible extra filters.
        # Only q, search, developer, publisher, year range, and genre+tag combined
        # force the slow path; matviews can't satisfy publisher filtering.
        needs_slow = (
            q or search or developer or publisher or year_from is not None or year_to is not None
        )
        if genre and not tag and not needs_slow:
            return self._list_from_matview(
                "mv_genre_games",
                "genre_slug",
                genre,
                sort,
                limit,
                offset,
                min_reviews=min_reviews,
                has_analysis=has_analysis,
                sentiment=sentiment,
                price_tier=price_tier,
                deck_status=deck_status,
            )
        if tag and not genre and not needs_slow:
            return self._list_from_matview(
                "mv_tag_games",
                "tag_slug",
                tag,
                sort,
                limit,
                offset,
                min_reviews=min_reviews,
                has_analysis=has_analysis,
                sentiment=sentiment,
                price_tier=price_tier,
                deck_status=deck_status,
            )

        # See _MV_SORT_COLS — `sentiment_score` is a legacy alias mapped to positive_pct
        _sort_cols = {
            "review_count": "g.review_count DESC NULLS LAST",
            "hidden_gem_score": "g.hidden_gem_score DESC NULLS LAST",
            "sentiment_score": "g.positive_pct DESC NULLS LAST",
            "positive_pct": "g.positive_pct DESC NULLS LAST",
            "release_date": "g.release_date DESC NULLS LAST",
            "last_analyzed": "g.last_analyzed DESC NULLS LAST",
            "revenue_desc": "g.estimated_revenue_usd DESC NULLS LAST",
            "name": "g.name ASC",
        }
        order = _sort_cols.get(sort, _sort_cols["review_count"])
        conditions: list[str] = ["1=1"]
        params: list = []

        # Text search — ILIKE with exact/prefix boost in ORDER BY
        search_term = q or search
        if search_term:
            conditions.append("g.name ILIKE %s")
            params.append(f"%{search_term}%")
            # Boost exact and prefix matches so "Minato" ranks above "Terminator"
            order = f"(LOWER(g.name) = LOWER(%s))::int DESC, (g.name ILIKE %s)::int DESC, {order}"
            params.append(search_term)
            params.append(f"{search_term}%")

        if genre:
            conditions.append(
                "EXISTS (SELECT 1 FROM game_genres gg JOIN genres gn ON gg.genre_id=gn.id "
                "WHERE gg.appid=g.appid AND gn.slug=%s)"
            )
            params.append(genre)
        if tag:
            conditions.append(
                "EXISTS (SELECT 1 FROM game_tags gt JOIN tags t ON gt.tag_id=t.id "
                "WHERE gt.appid=g.appid AND t.slug=%s)"
            )
            params.append(tag)
        if developer:
            conditions.append("g.developer_slug = %s")
            params.append(developer)
        if publisher:
            conditions.append("g.publisher_slug = %s")
            params.append(publisher)
        if year_from is not None:
            conditions.append("EXTRACT(YEAR FROM g.release_date) >= %s")
            params.append(year_from)
        if year_to is not None:
            conditions.append("EXTRACT(YEAR FROM g.release_date) <= %s")
            params.append(year_to)
        extra_conds, extra_params = self._build_game_filters(
            "g.",
            min_reviews=min_reviews,
            has_analysis=has_analysis,
            sentiment=sentiment,
            price_tier=price_tier,
            deck_status=deck_status,
        )
        conditions.extend(extra_conds)
        params.extend(extra_params)

        conditions.extend(self._sort_implied_filters(sort, "g."))

        where = " AND ".join(conditions)

        # Data-only query — no JOIN to reports. Scores are denormalized on games.
        sql = f"""
            SELECT g.appid, g.name, g.slug, g.developer, g.developer_slug, g.publisher_slug, g.header_image,
                   g.review_count, g.review_count_english, g.positive_pct, g.review_score_desc,
                   g.price_usd, g.is_free,
                   g.release_date, g.deck_compatibility,
                   g.hidden_gem_score, g.last_analyzed, g.crawled_at,
                   g.estimated_owners, g.estimated_revenue_usd, g.revenue_estimate_method,
                   EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = {EARLY_ACCESS_GENRE_ID}) AS is_early_access
            FROM games g
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """
        data_params = list(params) + [limit, offset]
        rows = self._fetchall(sql, tuple(data_params))

        result = []
        for row in rows:
            d = dict(row)
            if d.get("release_date"):
                d["release_date"] = str(d["release_date"])
            if d.get("estimated_revenue_usd") is not None:
                d["estimated_revenue_usd"] = float(d["estimated_revenue_usd"])
            result.append(d)
        return {"total": None, "games": result}

    def find_basics_by_appids(self, appids: list[int]) -> list[dict[str, object]]:
        """Return [{appid, name, slug, header_image, positive_pct, review_count}, ...]
        for the given appids.

        Backs GET /api/games/basics — the lightweight crosslink lookup used
        by the genre synthesis page (benchmark cards, friction/wishlist
        quote source-game links) and the homepage hero strip (sentiment
        chips for the SEO-anchor games), without pulling the full report
        JSON for each appid.

        `review_count` prefers `review_count_english` and falls back to the
        all-language `review_count` — same English-first signal used by
        Phase-4 eligibility / synthesis aggregates.

        Preserves caller order in the result; unknown appids are omitted.
        """
        if not appids:
            return []
        rows = self._fetchall(
            """
            SELECT appid, name, slug, header_image,
                   positive_pct,
                   COALESCE(review_count_english, review_count) AS review_count
            FROM games WHERE appid = ANY(%s)
            """,
            (appids,),
        )
        by_appid = {int(r["appid"]): dict(r) for r in rows}
        return [by_appid[a] for a in appids if a in by_appid]

    def find_review_stats_for_appids(self, appids: list[int]) -> list[dict[str, object]]:
        """Return [{appid, positive_pct, review_count}, ...] for the given appids.

        Used by the Phase-4 synthesizer to compute aggregate descriptors
        (avg_positive_pct, median_review_count) for the input set.

        `review_count` here prefers `review_count_english` and falls back
        to the all-language `review_count` — matching the English-first
        eligibility/ordering logic in
        TagRepository.find_eligible_for_synthesis so the aggregates are
        computed over the same signal Phase-4 selected on.

        Rows with NULL positive_pct / review_count are still returned so
        callers can filter them explicitly.
        """
        if not appids:
            return []
        rows = self._fetchall(
            """
            SELECT appid, positive_pct,
                   COALESCE(review_count_english, review_count) AS review_count
            FROM games WHERE appid = ANY(%s)
            """,
            (appids,),
        )
        return [dict(r) for r in rows]

    def find_benchmarks(
        self, appid: int, genre: str, year: int, price: float | None, is_free: bool
    ) -> dict:
        """Percentile rankings vs. genre + release-year + price cohort."""
        rows = self._fetchall(
            """
            WITH cohort AS (
                SELECT g.appid, g.positive_pct, g.review_count
                FROM games g
                JOIN game_genres gg ON gg.appid = g.appid
                JOIN genres gn ON gg.genre_id = gn.id
                WHERE gn.name = %s
                  AND EXTRACT(YEAR FROM g.release_date) = %s
                  AND (
                      (g.is_free = TRUE AND %s = TRUE)
                      OR (g.price_usd BETWEEN %s * 0.5 AND %s * 2.0)
                  )
                  AND g.review_count > 50
            ),
            ranked AS (
                SELECT appid,
                       PERCENT_RANK() OVER (ORDER BY positive_pct) AS sentiment_rank,
                       PERCENT_RANK() OVER (ORDER BY review_count)  AS popularity_rank
                FROM cohort
            )
            SELECT r.sentiment_rank, r.popularity_rank,
                   (SELECT COUNT(*) FROM cohort) AS cohort_size
            FROM ranked r WHERE r.appid = %s
            """,
            (genre, year, is_free, price or 0.0, price or 0.0, appid),
        )
        if not rows:
            return {"sentiment_rank": None, "popularity_rank": None, "cohort_size": 0}
        r = rows[0]
        return {
            "sentiment_rank": float(r["sentiment_rank"])
            if r["sentiment_rank"] is not None
            else None,
            "popularity_rank": float(r["popularity_rank"])
            if r["popularity_rank"] is not None
            else None,
            "cohort_size": int(r["cohort_size"]),
        }

    def list_genres(self) -> list[dict]:
        """Return genres with game counts, ordered by game_count DESC."""
        rows = self._fetchall("""
            SELECT gn.id, gn.name, gn.slug, COUNT(gg.appid) AS game_count
            FROM genres gn
            LEFT JOIN game_genres gg ON gg.genre_id = gn.id
            GROUP BY gn.id, gn.name, gn.slug
            ORDER BY game_count DESC, gn.name
        """)
        return [dict(r) for r in rows]

    def list_tags(self, limit: int = 100) -> list[dict]:
        """Return tags with game counts, ordered by game_count DESC."""
        rows = self._fetchall(
            """
            SELECT t.id, t.name, t.slug, t.category, COUNT(gt.appid) AS game_count
            FROM tags t
            LEFT JOIN game_tags gt ON gt.tag_id = t.id
            GROUP BY t.id, t.name, t.slug, t.category
            ORDER BY game_count DESC, t.name
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    def list_tags_grouped(self, limit_per_category: int = 20) -> list[dict]:
        """Return tags grouped by category, ordered by game_count within each group."""
        rows = self._fetchall(
            """
            SELECT ranked.category, ranked.id, ranked.name, ranked.slug,
                   ranked.game_count, ranked.total_count
            FROM (
                SELECT
                    agg.category, agg.id, agg.name, agg.slug, agg.game_count,
                    COUNT(*) OVER (PARTITION BY agg.category) AS total_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY agg.category
                        ORDER BY agg.game_count DESC, agg.name
                    ) AS rn
                FROM (
                    SELECT t.category, t.id, t.name, t.slug,
                           COUNT(gt.appid) AS game_count
                    FROM tags t
                    LEFT JOIN game_tags gt ON gt.tag_id = t.id
                    GROUP BY t.category, t.id, t.name, t.slug
                    HAVING COUNT(gt.appid) > 0
                ) AS agg
            ) AS ranked
            WHERE ranked.rn <= %s
            ORDER BY ranked.category, ranked.game_count DESC, ranked.name
            """,
            (limit_per_category,),
        )
        grouped_by_category: dict[str, dict] = {}
        for row in rows:
            category = row["category"]
            if category not in grouped_by_category:
                grouped_by_category[category] = {
                    "category": category,
                    "tags": [],
                    "total_count": row["total_count"],
                }
            grouped_by_category[category]["tags"].append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "category": row["category"],
                    "game_count": row["game_count"],
                }
            )
        grouped = list(grouped_by_category.values())
        grouped.sort(
            key=lambda g: (
                TAG_CATEGORY_ORDER.index(g["category"])
                if g["category"] in TAG_CATEGORY_ORDER
                else 99
            ),
        )
        return grouped

    def update_revenue_estimate(
        self,
        appid: int,
        owners: int | None,
        revenue_usd: Decimal | None,
        method: str | None,
        reason: str | None = None,
    ) -> None:
        """Store the latest Boxleiter revenue estimate for a game.

        When both `owners` and `revenue_usd` are None (e.g. free-to-play,
        excluded type, insufficient reviews), `method` is coerced to NULL so
        clients can reliably treat a NULL method as "no estimate available".
        Symmetrically, `reason` is coerced to NULL whenever a numeric
        estimate IS present — the reason code is only meaningful when the
        numeric fields are NULL, and enforcing that at the repo layer
        prevents stale reason codes from leaking onto rows that later
        acquire a real estimate.
        `revenue_estimate_computed_at` is always stamped — it tracks that we
        attempted a computation, regardless of outcome.
        """
        has_estimate = owners is not None or revenue_usd is not None
        persisted_method = method if has_estimate else None
        persisted_reason = None if has_estimate else reason
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE games
                SET estimated_owners             = %s,
                    estimated_revenue_usd        = %s,
                    revenue_estimate_method      = %s,
                    revenue_estimate_reason      = %s,
                    revenue_estimate_computed_at = NOW()
                WHERE appid = %s
                """,
                (owners, revenue_usd, persisted_method, persisted_reason, appid),
            )
        self.conn.commit()

    def bulk_update_revenue_estimates(
        self,
        rows: list[tuple[int, int | None, Decimal | None, str | None, str | None]],
    ) -> None:
        """Apply many revenue estimate updates in one transaction.

        Each row is `(appid, owners, revenue_usd, method, reason)`. The repo
        enforces two symmetric contracts:
          - `method` is coerced to NULL when neither numeric field is set,
            so clients can treat a NULL method as "no estimate available".
          - `reason` is coerced to NULL when a numeric estimate IS present,
            so stale reason codes cannot leak onto rows that subsequently
            acquire a real estimate.
        One commit per call keeps Lambda hot-loop / backfill runtime
        predictable (no per-row transaction overhead).
        """
        if not rows:
            return
        from psycopg2.extras import execute_values

        payload = []
        for appid, owners, revenue_usd, method, reason in rows:
            has_estimate = owners is not None or revenue_usd is not None
            payload.append(
                (
                    owners,
                    revenue_usd,
                    method if has_estimate else None,
                    None if has_estimate else reason,
                    appid,
                )
            )
        with self.conn.cursor() as cur:
            execute_values(
                cur,
                """
                UPDATE games AS g SET
                    estimated_owners             = data.owners,
                    estimated_revenue_usd        = data.revenue_usd,
                    revenue_estimate_method      = data.method,
                    revenue_estimate_reason      = data.reason,
                    revenue_estimate_computed_at = NOW()
                FROM (VALUES %s) AS data(owners, revenue_usd, method, reason, appid)
                WHERE g.appid = data.appid
                """,
                payload,
                template="(%s::bigint, %s::numeric, %s::text, %s::text, %s::int)",
            )
        self.conn.commit()

    def set_has_early_access_reviews(self, appid: int) -> None:
        """One-way latch: mark that this game has EA reviews. No-op if already TRUE.

        Best-effort: gracefully handles missing column during the
        post-deploy/pre-migration window before migration 0046 is applied.
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE games SET has_early_access_reviews = TRUE "
                    "WHERE appid = %s AND has_early_access_reviews = FALSE",
                    (appid,),
                )
            self.conn.commit()
        except psycopg2.errors.UndefinedColumn:
            self.conn.rollback()
            logger.warning(
                "has_early_access_reviews column not yet available",
                extra={"appid": appid},
            )

    def update_velocity_cache(self, appid: int, velocity_lifetime: float) -> None:
        """Cache lifetime review velocity for list-page sort/filter."""
        with self.conn.cursor() as cur:
            cur.execute(
                """UPDATE games
                   SET review_velocity_lifetime = %s,
                       last_velocity_computed_at = NOW()
                   WHERE appid = %s""",
                (velocity_lifetime, appid),
            )
        self.conn.commit()
