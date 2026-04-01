"""TagRepository — pure SQL I/O for tags, genres, and categories."""

from __future__ import annotations

from library_layer.repositories.base import BaseRepository
from library_layer.utils.slugify import slugify


class TagRepository(BaseRepository):
    """CRUD operations for tags, game_tags, genres, game_genres, game_categories."""

    def upsert_tags(self, items: list[dict]) -> None:
        """Upsert tags and game_tag associations.

        Args:
            items: List of dicts with keys: appid, name (tag name), votes.
        """
        with self.conn.cursor() as cur:
            for item in items:
                tag_name: str = item.get("name") or ""
                if not tag_name:
                    continue
                appid: int = item["appid"]
                votes: int = item.get("votes", 0)
                tag_slug = slugify(tag_name) or tag_name.lower()[:50]

                cur.execute(
                    """
                    INSERT INTO tags (name, slug) VALUES (%s, %s)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (tag_name, tag_slug),
                )
                cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
                row = cur.fetchone()
                if row:
                    tag_id: int = row["id"] if isinstance(row, dict) else row[0]
                    cur.execute(
                        """
                        INSERT INTO game_tags (appid, tag_id, votes) VALUES (%s, %s, %s)
                        ON CONFLICT (appid, tag_id) DO UPDATE SET votes = EXCLUDED.votes
                        """,
                        (appid, tag_id, votes),
                    )
        self.conn.commit()

    def upsert_genres(self, appid: int, genres: list[dict]) -> None:
        """Upsert genres and game_genre associations.

        Args:
            appid: The game's appid.
            genres: List of Steam genre dicts: [{"id": "1", "description": "Action"}, ...]
        """
        with self.conn.cursor() as cur:
            for genre in genres:
                genre_id = int(genre.get("id") or 0)
                genre_name: str = genre.get("description") or ""
                genre_slug = slugify(genre_name) or f"genre-{genre_id}"
                if not (genre_id and genre_name):
                    continue
                cur.execute(
                    """
                    INSERT INTO genres (id, name, slug) VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug
                    """,
                    (genre_id, genre_name, genre_slug),
                )
                cur.execute(
                    """
                    INSERT INTO game_genres (appid, genre_id) VALUES (%s, %s)
                    ON CONFLICT (appid, genre_id) DO NOTHING
                    """,
                    (appid, genre_id),
                )
        self.conn.commit()

    def upsert_categories(self, appid: int, categories: list[dict]) -> None:
        """Upsert category associations for a game.

        Args:
            appid: The game's appid.
            categories: List of Steam category dicts: [{"id": 1, "description": "Multi-player"}, ...]
        """
        with self.conn.cursor() as cur:
            for cat in categories:
                cat_id = int(cat.get("id") or 0)
                cat_name: str = cat.get("description") or ""
                if not (cat_id and cat_name):
                    continue
                cur.execute(
                    """
                    INSERT INTO game_categories (appid, category_id, category_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (appid, category_id) DO UPDATE
                        SET category_name = EXCLUDED.category_name
                    """,
                    (appid, cat_id, cat_name),
                )
        self.conn.commit()

    def find_tags_for_game(self, appid: int) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT t.id, t.name, t.slug, gt.votes
            FROM tags t
            JOIN game_tags gt ON gt.tag_id = t.id
            WHERE gt.appid = %s
            ORDER BY gt.votes DESC
            """,
            (appid,),
        )
        return [dict(r) for r in rows]

    def find_genres_for_game(self, appid: int) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT g.id, g.name, g.slug
            FROM genres g
            JOIN game_genres gg ON gg.genre_id = g.id
            WHERE gg.appid = %s
            """,
            (appid,),
        )
        return [dict(r) for r in rows]

    def find_tags_for_appids(self, appids: list[int]) -> dict[int, list[dict]]:
        """Fetch tags for multiple appids in one query. Returns {appid: [tag, ...]}."""
        if not appids:
            return {}
        rows = self._fetchall(
            """
            SELECT gt.appid, t.id, t.name, t.slug, gt.votes
            FROM tags t
            JOIN game_tags gt ON gt.tag_id = t.id
            WHERE gt.appid = ANY(%s)
            ORDER BY gt.appid, gt.votes DESC
            """,
            (appids,),
        )
        result: dict[int, list[dict]] = {appid: [] for appid in appids}
        for r in rows:
            d = dict(r)
            result[d["appid"]].append(d)
        return result

    def find_genres_for_appids(self, appids: list[int]) -> dict[int, list[dict]]:
        """Fetch genres for multiple appids in one query. Returns {appid: [genre, ...]}."""
        if not appids:
            return {}
        rows = self._fetchall(
            """
            SELECT gg.appid, g.id, g.name, g.slug
            FROM genres g
            JOIN game_genres gg ON gg.genre_id = g.id
            WHERE gg.appid = ANY(%s)
            """,
            (appids,),
        )
        result: dict[int, list[dict]] = {appid: [] for appid in appids}
        for r in rows:
            d = dict(r)
            result[d["appid"]].append(d)
        return result
