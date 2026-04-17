"""GenreSynthesisRepository — pure SQL I/O for mv_genre_synthesis.

Sole writer is upsert(). Phase-4 Lambda is the only caller; the API and
any downstream consumer read via get_by_slug().
"""

from __future__ import annotations

import json

from library_layer.models.genre_synthesis import GenreSynthesis, GenreSynthesisRow
from library_layer.repositories.base import BaseRepository


class GenreSynthesisRepository(BaseRepository):
    """CRUD operations for mv_genre_synthesis."""

    def get_by_slug(self, slug: str) -> GenreSynthesisRow | None:
        row = self._fetchone(
            """
            SELECT slug, display_name, input_appids, input_count,
                   prompt_version, input_hash, synthesis, narrative_summary,
                   avg_positive_pct, median_review_count, computed_at
            FROM mv_genre_synthesis
            WHERE slug = %s
            """,
            (slug,),
        )
        if row is None:
            return None
        d = dict(row)
        # psycopg2 decodes JSONB to dict by default, but some call sites
        # wrap the cursor with a plain str-returning JSON type — handle
        # both so a future driver swap doesn't break reads silently.
        synthesis = d["synthesis"]
        if isinstance(synthesis, str):
            synthesis = json.loads(synthesis)
        d["synthesis"] = GenreSynthesis.model_validate(synthesis)
        d["avg_positive_pct"] = float(d["avg_positive_pct"])
        return GenreSynthesisRow.model_validate(d)

    def upsert(self, row: GenreSynthesisRow) -> None:
        """Insert or update by slug. Always full replace — no merge.

        Persists `row.computed_at` verbatim. The service sets this to the
        time the LLM synthesis ran, and the caller expects the row it
        receives back to carry that same timestamp — using NOW() on the
        DB side would desync the in-memory model from the persisted row.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mv_genre_synthesis (
                    slug, display_name, input_appids, input_count,
                    prompt_version, input_hash, synthesis, narrative_summary,
                    avg_positive_pct, median_review_count, computed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    display_name        = EXCLUDED.display_name,
                    input_appids        = EXCLUDED.input_appids,
                    input_count         = EXCLUDED.input_count,
                    prompt_version      = EXCLUDED.prompt_version,
                    input_hash          = EXCLUDED.input_hash,
                    synthesis           = EXCLUDED.synthesis,
                    narrative_summary   = EXCLUDED.narrative_summary,
                    avg_positive_pct    = EXCLUDED.avg_positive_pct,
                    median_review_count = EXCLUDED.median_review_count,
                    computed_at         = EXCLUDED.computed_at
                """,
                (
                    row.slug,
                    row.display_name,
                    row.input_appids,
                    row.input_count,
                    row.prompt_version,
                    row.input_hash,
                    json.dumps(row.synthesis.model_dump(mode="json")),
                    row.narrative_summary,
                    row.avg_positive_pct,
                    row.median_review_count,
                    row.computed_at,
                ),
            )
        self.conn.commit()

    def find_stale(self, max_age_days: int) -> list[str]:
        """Return slugs whose synthesis is older than max_age_days.

        Used by the EventBridge weekly scan to enqueue refresh jobs.
        """
        rows = self._fetchall(
            """
            SELECT slug FROM mv_genre_synthesis
            WHERE computed_at < NOW() - (%s * INTERVAL '1 day')
            ORDER BY computed_at
            """,
            (max_age_days,),
        )
        return [r["slug"] for r in rows]
