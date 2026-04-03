"""TagRepository — pure SQL I/O for tags, genres, and categories."""

from __future__ import annotations

from library_layer.repositories.base import BaseRepository
from library_layer.utils.slugify import slugify


class TagRepository(BaseRepository):
    """CRUD operations for tags, game_tags, genres, game_genres, game_categories."""

    def upsert_tags(self, items: list[dict]) -> None:
        """Upsert tags and game_tag associations in bulk.

        Args:
            items: List of dicts with keys: appid, name (tag name), votes.
                   Optional key: tagid (Steam's stable tag ID).
        """
        # Build deduplicated tag list and prepare data
        tag_rows: list[tuple[str, str, int | None]] = []
        seen_names: set[str] = set()
        valid_items: list[tuple[int, str, int]] = []

        for item in items:
            tag_name: str = item.get("name") or ""
            if not tag_name:
                continue
            appid: int = item["appid"]
            votes: int = item.get("votes", 0)
            steam_tag_id: int | None = item.get("tagid")
            tag_slug = slugify(tag_name) or tag_name.lower()[:50]
            valid_items.append((appid, tag_name, votes))
            if tag_name not in seen_names:
                seen_names.add(tag_name)
                tag_rows.append((tag_name, tag_slug, steam_tag_id))

        if not valid_items:
            return

        with self.conn.cursor() as cur:
            from psycopg2.extras import execute_values

            # Prefetch existing slugs to avoid unique violations on slug column
            candidate_slugs = [slug for _, slug, _ in tag_rows]
            cur.execute("SELECT slug FROM tags WHERE slug = ANY(%s)", (candidate_slugs,))
            existing_slugs: set[str] = {
                row["slug"] if isinstance(row, dict) else row[0] for row in cur.fetchall()
            }

            # Deduplicate slugs against both existing DB rows and within the batch
            used_slugs: set[str] = set(existing_slugs)
            deduped_rows: list[tuple[str, str, int | None]] = []
            for name, slug, steam_tag_id in tag_rows:
                final_slug = slug
                counter = 1
                while final_slug in used_slugs:
                    final_slug = f"{slug}-{counter}"
                    counter += 1
                used_slugs.add(final_slug)
                deduped_rows.append((name, final_slug, steam_tag_id))

            execute_values(
                cur,
                """INSERT INTO tags (name, slug, steam_tag_id) VALUES %s
                   ON CONFLICT (name) DO UPDATE
                   SET steam_tag_id = COALESCE(EXCLUDED.steam_tag_id, tags.steam_tag_id)""",
                deduped_rows,
            )

            # Fetch all tag IDs in one query
            names = [name for name, _, _ in tag_rows]
            cur.execute("SELECT id, name FROM tags WHERE name = ANY(%s)", (names,))
            name_to_id: dict[str, int] = {}
            for row in cur.fetchall():
                tag_id = row["id"] if isinstance(row, dict) else row[0]
                tag_name = row["name"] if isinstance(row, dict) else row[1]
                name_to_id[tag_name] = tag_id

            # Bulk upsert game_tags
            game_tag_rows = [
                (appid, name_to_id[name], votes)
                for appid, name, votes in valid_items
                if name in name_to_id
            ]
            if game_tag_rows:
                execute_values(
                    cur,
                    """INSERT INTO game_tags (appid, tag_id, votes) VALUES %s
                       ON CONFLICT (appid, tag_id) DO UPDATE SET votes = EXCLUDED.votes""",
                    game_tag_rows,
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
