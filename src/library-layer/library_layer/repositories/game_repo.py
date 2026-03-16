"""GameRepository — pure SQL I/O for the games table."""

from __future__ import annotations

from library_layer.models.game import Game
from library_layer.repositories.base import BaseRepository


class GameRepository(BaseRepository):
    """CRUD operations for the games table."""

    def upsert(self, game_data: dict) -> None:
        """INSERT ... ON CONFLICT (appid) DO UPDATE with all game columns."""
        sql = """
            INSERT INTO games (
                appid, name, slug, type, developer, publisher, developers, publishers,
                website, release_date, coming_soon, price_usd, is_free,
                short_desc, detailed_description, about_the_game,
                review_count, total_positive, total_negative, positive_pct,
                review_score_desc, header_image, background_image,
                required_age, platforms, supported_languages,
                achievements_total, metacritic_score, crawled_at, data_source
            ) VALUES (
                %(appid)s, %(name)s, %(slug)s, %(type)s, %(developer)s, %(publisher)s,
                %(developers)s, %(publishers)s,
                %(website)s, %(release_date)s, %(coming_soon)s, %(price_usd)s, %(is_free)s,
                %(short_desc)s, %(detailed_description)s, %(about_the_game)s,
                %(review_count)s, %(total_positive)s, %(total_negative)s, %(positive_pct)s,
                %(review_score_desc)s, %(header_image)s,
                %(background_image)s, %(required_age)s, %(platforms)s,
                %(supported_languages)s, %(achievements_total)s, %(metacritic_score)s,
                NOW(), %(data_source)s
            )
            ON CONFLICT (appid) DO UPDATE SET
                name                 = EXCLUDED.name,
                slug                 = EXCLUDED.slug,
                type                 = EXCLUDED.type,
                developer            = EXCLUDED.developer,
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
        row = self._fetchone(
            "SELECT review_count FROM games WHERE appid = %s", (appid,)
        )
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
                ON CONFLICT (appid) DO UPDATE SET name = EXCLUDED.name
                """,
                (appid, stub_name, stub_slug),
            )
        self.conn.commit()

    def list_games(
        self,
        genre: str | None = None,
        tag: str | None = None,
        developer: str | None = None,
        min_reviews: int | None = None,
        search: str | None = None,
        sort: str = "review_count",
        limit: int = 48,
        offset: int = 0,
    ) -> list[dict]:
        """Parameterised query with optional WHERE clauses.

        Returns rows with: appid, name, slug, developer, header_image,
        review_count, positive_pct, price_usd, is_free, release_date,
        hidden_gem_score, sentiment_score.
        ORDER BY is controlled by *sort* (``review_count`` | ``hidden_gem_score``
        | ``positive_pct``).
        """
        _sort_cols = {
            "review_count":    "g.review_count DESC NULLS LAST",
            "hidden_gem_score": "r.report_json->>'hidden_gem_score' DESC NULLS LAST",
            "positive_pct":    "g.positive_pct DESC NULLS LAST",
        }
        order = _sort_cols.get(sort, _sort_cols["review_count"])
        conditions: list[str] = ["1=1"]
        params: list = []
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
            conditions.append("g.developer ILIKE %s")
            params.append(f"%{developer}%")
        if min_reviews is not None:
            conditions.append("g.review_count >= %s")
            params.append(min_reviews)
        if search:
            conditions.append("g.name ILIKE %s")
            params.append(f"%{search}%")
        where = " AND ".join(conditions)
        sql = f"""
            SELECT g.appid, g.name, g.slug, g.developer, g.header_image,
                   g.review_count, g.positive_pct, g.price_usd, g.is_free,
                   g.release_date,
                   r.report_json->>'hidden_gem_score' AS hidden_gem_score,
                   r.report_json->>'sentiment_score'  AS sentiment_score
            FROM games g
            LEFT JOIN reports r ON r.appid = g.appid
            WHERE {where}
            ORDER BY {order}
            LIMIT %s OFFSET %s
        """
        params += [limit, offset]
        rows = self._fetchall(sql, tuple(params))
        result = []
        for row in rows:
            d = dict(row)
            if d.get("release_date"):
                d["release_date"] = str(d["release_date"])
            result.append(d)
        return result

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
            SELECT t.id, t.name, t.slug, COUNT(gt.appid) AS game_count
            FROM tags t
            LEFT JOIN game_tags gt ON gt.tag_id = t.id
            GROUP BY t.id, t.name, t.slug
            ORDER BY game_count DESC, t.name
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in rows]
