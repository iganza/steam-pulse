"""TagRepository — pure SQL I/O for tags, genres, and categories."""

from __future__ import annotations

from library_layer.repositories.base import BaseRepository
from library_layer.utils.slugify import slugify

# Canonical display order for tag categories. Used by any code that groups
# tags by category (GameRepository, MatviewRepository, etc.).
TAG_CATEGORY_ORDER: tuple[str, ...] = (
    "Genre",
    "Sub-Genre",
    "Theme & Setting",
    "Gameplay",
    "Player Mode",
    "Visuals & Viewpoint",
    "Mood & Tone",
    "Other",
)


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

                # Delete stale tag associations for every appid in this batch
                # in a single DELETE. UNNEST of parallel arrays builds the
                # keep-set inline, reducing statement count, round-trips, and
                # per-statement overhead versus N small DELETEs (one per touched appid).
                batch_appids = list({aid for aid, _, _ in game_tag_rows})
                kept_appids = [aid for aid, _, _ in game_tag_rows]
                kept_tag_ids = [tid for _, tid, _ in game_tag_rows]
                cur.execute(
                    """
                    DELETE FROM game_tags gt
                    WHERE gt.appid = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM UNNEST(%s::int[], %s::int[]) AS kept(appid, tag_id)
                          WHERE kept.appid = gt.appid AND kept.tag_id = gt.tag_id
                      )
                    """,
                    (batch_appids, kept_appids, kept_tag_ids),
                )
        self.conn.commit()

    def upsert_genres(self, appid: int, genres: list[dict]) -> None:
        """Upsert genres and game_genre associations (delete-and-replace).

        Removes any existing game_genre associations for this appid that are NOT in the
        incoming set, so genres dropped by Steam (e.g. leaving Early Access) disappear.

        Args:
            appid: The game's appid.
            genres: List of Steam genre dicts: [{"id": "1", "description": "Action"}, ...]
        """
        valid_genre_ids = [int(g.get("id") or 0) for g in genres if int(g.get("id") or 0)]
        # Dedupe by genre_id — execute_values + ON CONFLICT DO UPDATE raises on
        # duplicate conflict targets within a single statement. Steam occasionally
        # returns the same genre twice (unlike per-row INSERTs, which absorbed it).
        genre_by_id: dict[int, tuple[int, str, str]] = {}
        for genre in genres:
            genre_id = int(genre.get("id") or 0)
            genre_name: str = genre.get("description") or ""
            if not (genre_id and genre_name):
                continue
            genre_slug = slugify(genre_name) or f"genre-{genre_id}"
            genre_by_id[genre_id] = (genre_id, genre_name, genre_slug)
        genre_rows = list(genre_by_id.values())
        game_genre_rows: list[tuple[int, int]] = [(appid, gid) for gid in genre_by_id]

        with self.conn.cursor() as cur:
            from psycopg2.extras import execute_values

            if valid_genre_ids:
                cur.execute(
                    "DELETE FROM game_genres WHERE appid = %s AND genre_id != ALL(%s)",
                    (appid, valid_genre_ids),
                )
            else:
                cur.execute("DELETE FROM game_genres WHERE appid = %s", (appid,))

            if genre_rows:
                execute_values(
                    cur,
                    """INSERT INTO genres (id, name, slug) VALUES %s
                       ON CONFLICT (id) DO UPDATE
                         SET name = EXCLUDED.name, slug = EXCLUDED.slug""",
                    genre_rows,
                )
                execute_values(
                    cur,
                    """INSERT INTO game_genres (appid, genre_id) VALUES %s
                       ON CONFLICT (appid, genre_id) DO NOTHING""",
                    game_genre_rows,
                )
        self.conn.commit()

    def upsert_categories(self, appid: int, categories: list[dict]) -> None:
        """Upsert category associations for a game (delete-and-replace).

        Removes any existing game_category associations for this appid that are NOT in
        the incoming set, so categories dropped by Steam disappear.

        Args:
            appid: The game's appid.
            categories: List of Steam category dicts: [{"id": 1, "description": "Multi-player"}, ...]
        """
        valid_cat_ids = [int(c.get("id") or 0) for c in categories if int(c.get("id") or 0)]
        # Dedupe by cat_id — execute_values + ON CONFLICT DO UPDATE raises on
        # duplicate conflict targets within a single statement.
        category_by_id: dict[int, tuple[int, int, str]] = {}
        for cat in categories:
            cat_id = int(cat.get("id") or 0)
            cat_name: str = cat.get("description") or ""
            if not (cat_id and cat_name):
                continue
            category_by_id[cat_id] = (appid, cat_id, cat_name)
        category_rows = list(category_by_id.values())

        with self.conn.cursor() as cur:
            from psycopg2.extras import execute_values

            if valid_cat_ids:
                cur.execute(
                    "DELETE FROM game_categories WHERE appid = %s AND category_id != ALL(%s)",
                    (appid, valid_cat_ids),
                )
            else:
                cur.execute("DELETE FROM game_categories WHERE appid = %s", (appid,))

            if category_rows:
                execute_values(
                    cur,
                    """INSERT INTO game_categories (appid, category_id, category_name)
                       VALUES %s
                       ON CONFLICT (appid, category_id) DO UPDATE
                         SET category_name = EXCLUDED.category_name""",
                    category_rows,
                )
        self.conn.commit()

    def find_tags_for_game(self, appid: int) -> list[dict]:
        rows = self._fetchall(
            """
            SELECT t.id, t.name, t.slug, t.category, gt.votes
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
            SELECT gt.appid, t.id, t.name, t.slug, t.category, gt.votes
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

    def find_eligible_for_synthesis(
        self, slug: str, *, min_reviews: int, limit: int, pipeline_version: str
    ) -> list[int]:
        """Return appids eligible to feed the Phase-4 genre synthesizer.

        Filters:
          - game has the given tag slug
          - game has a report at reports.pipeline_version = %s
            (stale reports from a prior Phase-3 PIPELINE_VERSION are
            excluded — mixing them in would degrade prompt adherence
            and produce inconsistent cross-genre syntheses)
          - COALESCE(review_count_english, review_count) >= min_reviews
            (English is the eligibility driver per schema docs; fall back
            to total only when English is missing)
          - positive_pct IS NOT NULL (guarantees _compute_aggregates can
            always produce a valid avg without hard-failing at runtime)

        Sorted by English-first review count DESC and capped at `limit`
        so large tags don't stream thousands of rows when the caller only
        ever consumes the top-N (MAX_REPORTS_PER_GENRE).
        """
        rows = self._fetchall(
            """
            SELECT g.appid
            FROM games g
            JOIN game_tags gt ON gt.appid = g.appid
            JOIN tags t ON t.id = gt.tag_id
            JOIN reports r ON r.appid = g.appid
            WHERE t.slug = %s
              AND r.pipeline_version = %s
              AND COALESCE(g.review_count_english, g.review_count, 0) >= %s
              AND g.positive_pct IS NOT NULL
            ORDER BY COALESCE(g.review_count_english, g.review_count) DESC NULLS LAST,
                     g.appid
            LIMIT %s
            """,
            (slug, pipeline_version, min_reviews, limit),
        )
        return [int(r["appid"]) for r in rows]

    def find_display_name_for_slug(self, slug: str) -> str | None:
        """Return the tag's display name for a slug, or None if unknown."""
        row = self._fetchone("SELECT name FROM tags WHERE slug = %s", (slug,))
        if row is None:
            return None
        return str(row["name"])

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
