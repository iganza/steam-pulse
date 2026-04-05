"""GameRepository — pure SQL I/O for the games table."""

from __future__ import annotations

from library_layer.models.game import Game
from library_layer.repositories.base import BaseRepository
from library_layer.repositories.tag_repo import TAG_CATEGORY_ORDER

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
                appid, name, slug, type, developer, developer_slug, publisher, developers, publishers,
                website, release_date, coming_soon, price_usd, is_free,
                short_desc, detailed_description, about_the_game,
                review_count, review_count_english, total_positive, total_negative, positive_pct,
                review_score_desc, header_image, background_image,
                required_age, platforms, supported_languages,
                achievements_total, metacritic_score,
                deck_compatibility, deck_test_results,
                crawled_at, data_source
            ) VALUES (
                %(appid)s, %(name)s, %(slug)s, %(type)s, %(developer)s, %(developer_slug)s, %(publisher)s,
                %(developers)s, %(publishers)s,
                %(website)s, %(release_date)s, %(coming_soon)s, %(price_usd)s, %(is_free)s,
                %(short_desc)s, %(detailed_description)s, %(about_the_game)s,
                %(review_count)s, %(review_count_english)s, %(total_positive)s, %(total_negative)s, %(positive_pct)s,
                %(review_score_desc)s, %(header_image)s,
                %(background_image)s, %(required_age)s, %(platforms)s,
                %(supported_languages)s, %(achievements_total)s, %(metacritic_score)s,
                %(deck_compatibility)s, %(deck_test_results)s,
                NOW(), %(data_source)s
            )
            ON CONFLICT (appid) DO UPDATE SET
                name                 = EXCLUDED.name,
                slug                 = EXCLUDED.slug,
                type                 = EXCLUDED.type,
                developer            = EXCLUDED.developer,
                developer_slug       = EXCLUDED.developer_slug,
                publisher            = EXCLUDED.publisher,
                developers           = EXCLUDED.developers,
                publishers           = EXCLUDED.publishers,
                website              = EXCLUDED.website,
                release_date         = EXCLUDED.release_date,
                coming_soon          = EXCLUDED.coming_soon,
                price_usd            = EXCLUDED.price_usd,
                is_free              = EXCLUDED.is_free,
                short_desc           = EXCLUDED.short_desc,
                detailed_description = EXCLUDED.detailed_description,
                about_the_game       = EXCLUDED.about_the_game,
                review_count         = EXCLUDED.review_count,
                review_count_english = EXCLUDED.review_count_english,
                total_positive       = EXCLUDED.total_positive,
                total_negative       = EXCLUDED.total_negative,
                positive_pct         = EXCLUDED.positive_pct,
                review_score_desc    = EXCLUDED.review_score_desc,
                header_image         = EXCLUDED.header_image,
                background_image     = EXCLUDED.background_image,
                required_age         = EXCLUDED.required_age,
                platforms            = EXCLUDED.platforms,
                supported_languages  = EXCLUDED.supported_languages,
                achievements_total   = EXCLUDED.achievements_total,
                metacritic_score     = EXCLUDED.metacritic_score,
                deck_compatibility   = EXCLUDED.deck_compatibility,
                deck_test_results    = EXCLUDED.deck_test_results,
                crawled_at           = NOW(),
                data_source          = EXCLUDED.data_source
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, game_data)
        self.conn.commit()

    def find_by_appid(self, appid: int) -> Game | None:
        row = self._fetchone("SELECT * FROM games WHERE appid = %s", (appid,))
        if row is None:
            return None
        return Game.model_validate(dict(row))

    def get_by_appid(self, appid: int) -> Game:
        """Return the game, raising GameNotFound if it does not exist."""
        game = self.find_by_appid(appid)
        if game is None:
            raise GameNotFound(appid)
        return game

    def find_by_slug(self, slug: str) -> Game | None:
        row = self._fetchone("SELECT * FROM games WHERE slug = %s", (slug,))
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

    def list_games(
        self,
        q: str | None = None,
        genre: str | None = None,
        tag: str | None = None,
        developer: str | None = None,
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

        Returns dict with 'total' count and 'games' list.
        """
        _sort_cols = {
            "review_count": "g.review_count DESC NULLS LAST",
            "hidden_gem_score": "r.report_json->>'hidden_gem_score' DESC NULLS LAST",
            "sentiment_score": "r.report_json->>'sentiment_score' DESC NULLS LAST",
            "positive_pct": "g.positive_pct DESC NULLS LAST",
            "release_date": "g.release_date DESC NULLS LAST",
            "last_analyzed": "r.last_analyzed DESC NULLS LAST",
            "name": "g.name ASC",
        }
        order = _sort_cols.get(sort, _sort_cols["review_count"])
        conditions: list[str] = ["1=1"]
        params: list = []

        # Text search — try pg_trgm, fall back to ILIKE
        search_term = q or search
        if search_term:
            conditions.append("g.name ILIKE %s")
            params.append(f"%{search_term}%")

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
        if year_from is not None:
            conditions.append("EXTRACT(YEAR FROM g.release_date) >= %s")
            params.append(year_from)
        if year_to is not None:
            conditions.append("EXTRACT(YEAR FROM g.release_date) <= %s")
            params.append(year_to)
        if min_reviews is not None:
            conditions.append("g.review_count >= %s")
            params.append(min_reviews)
        if has_analysis:
            conditions.append("r.appid IS NOT NULL")
        if sentiment:
            if sentiment == "positive":
                conditions.append("(r.report_json->>'sentiment_score')::float >= 0.65")
            elif sentiment == "mixed":
                conditions.append(
                    "(r.report_json->>'sentiment_score')::float >= 0.45 "
                    "AND (r.report_json->>'sentiment_score')::float < 0.65"
                )
            elif sentiment == "negative":
                conditions.append("(r.report_json->>'sentiment_score')::float < 0.45")
        if price_tier:
            if price_tier == "free":
                conditions.append("g.is_free = TRUE")
            elif price_tier == "under_10":
                conditions.append("g.price_usd < 10 AND (g.is_free IS NULL OR g.is_free = FALSE)")
            elif price_tier == "10_to_20":
                conditions.append("g.price_usd >= 10 AND g.price_usd <= 20")
            elif price_tier == "over_20":
                conditions.append("g.price_usd > 20")
        if deck_status:
            _deck_map = {"verified": 3, "playable": 2, "unsupported": 1, "unknown": 0}
            deck_val = _deck_map.get(deck_status)
            if deck_val is not None:
                conditions.append("g.deck_compatibility = %s")
                params.append(deck_val)

        where = " AND ".join(conditions)

        # Single query with COUNT(*) OVER() to avoid a separate count round-trip.
        sql = f"""
            SELECT g.appid, g.name, g.slug, g.developer, g.header_image,
                   g.review_count, g.review_count_english, g.positive_pct, g.price_usd, g.is_free,
                   g.release_date, g.deck_compatibility,
                   r.report_json->>'hidden_gem_score' AS hidden_gem_score,
                   r.report_json->>'sentiment_score'  AS sentiment_score,
                   EXISTS (SELECT 1 FROM game_genres gg WHERE gg.appid = g.appid AND gg.genre_id = {EARLY_ACCESS_GENRE_ID}) AS is_early_access,
                   COUNT(*) OVER() AS total_count
            FROM games g
            LEFT JOIN reports r ON r.appid = g.appid
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """
        data_params = list(params) + [limit, offset]
        rows = self._fetchall(sql, tuple(data_params))

        if rows:
            total = int(rows[0]["total_count"])
        elif offset > 0:
            # Paged past results — still need total for the paginator.
            count_sql = f"""
                SELECT COUNT(*) AS cnt
                FROM games g
                LEFT JOIN reports r ON r.appid = g.appid
                WHERE {where}
            """
            count_row = self._fetchone(count_sql, tuple(params))
            total = int(count_row["cnt"]) if count_row else 0
        else:
            total = 0

        result = []
        for row in rows:
            d = dict(row)
            d.pop("total_count", None)
            if d.get("release_date"):
                d["release_date"] = str(d["release_date"])
            result.append(d)
        return {"total": total, "games": result}

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
