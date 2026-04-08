"""NewReleasesRepository — pure SQL I/O backed by mv_new_releases.

All queries hit the materialized view, never the base tables. The matview is
registered in MatviewRepository.MATVIEW_NAMES and refreshed by the existing
matview_refresh_handler Lambda — no separate refresh wiring.
"""

from __future__ import annotations

from datetime import date, datetime

from library_layer.models.new_release import NewReleaseEntry
from library_layer.repositories.base import BaseRepository


def _filter_clause(genre: str | None, tag: str | None) -> tuple[str, list]:
    """Build the genre/tag filter SQL fragment + params.

    Returns ("" or " AND ...", [params]) — caller appends to an existing WHERE.
    """
    parts: list[str] = []
    params: list = []
    if genre:
        parts.append("%s = ANY(genre_slugs)")
        params.append(genre)
    if tag:
        parts.append("%s = ANY(top_tag_slugs)")
        params.append(tag)
    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


class NewReleasesRepository(BaseRepository):
    """Read-only access to mv_new_releases for the /new-releases feed."""

    # ── Released lens ────────────────────────────────────────────────────────

    def find_recently_released(
        self,
        since: date | None,
        until: date,
        limit: int,
        offset: int,
        genre: str | None = None,
        tag: str | None = None,
    ) -> list[NewReleaseEntry]:
        filt, fparams = _filter_clause(genre, tag)
        if since is not None:
            sql = f"""
                SELECT * FROM mv_new_releases
                WHERE coming_soon = FALSE
                  AND release_date IS NOT NULL
                  AND release_date >= %s AND release_date <= %s
                  {filt}
                ORDER BY release_date DESC, appid DESC
                LIMIT %s OFFSET %s
            """
            params: list = [since, until, *fparams, limit, offset]
        else:
            sql = f"""
                SELECT * FROM mv_new_releases
                WHERE coming_soon = FALSE
                  AND release_date IS NOT NULL
                  AND release_date <= %s
                  {filt}
                ORDER BY release_date DESC, appid DESC
                LIMIT %s OFFSET %s
            """
            params = [until, *fparams, limit, offset]
        rows = self._fetchall(sql, tuple(params))
        return [NewReleaseEntry.model_validate(dict(r)) for r in rows]

    def count_released_between(
        self,
        since: date | None,
        until: date,
        genre: str | None = None,
        tag: str | None = None,
    ) -> int:
        filt, fparams = _filter_clause(genre, tag)
        if since is not None:
            sql = f"""
                SELECT COUNT(*) AS c FROM mv_new_releases
                WHERE coming_soon = FALSE
                  AND release_date IS NOT NULL
                  AND release_date >= %s AND release_date <= %s
                  {filt}
            """
            params: list = [since, until, *fparams]
        else:
            sql = f"""
                SELECT COUNT(*) AS c FROM mv_new_releases
                WHERE coming_soon = FALSE
                  AND release_date IS NOT NULL
                  AND release_date <= %s
                  {filt}
            """
            params = [until, *fparams]
        row = self._fetchone(sql, tuple(params))
        return int(row["c"]) if row else 0

    # ── Coming Soon lens ─────────────────────────────────────────────────────

    def find_upcoming(
        self,
        limit: int,
        offset: int,
        genre: str | None = None,
        tag: str | None = None,
    ) -> list[NewReleaseEntry]:
        filt, fparams = _filter_clause(genre, tag)
        sql = f"""
            SELECT * FROM mv_new_releases
            WHERE coming_soon = TRUE
              {filt}
            ORDER BY release_date ASC NULLS LAST, appid ASC
            LIMIT %s OFFSET %s
        """
        rows = self._fetchall(sql, tuple([*fparams, limit, offset]))
        return [NewReleaseEntry.model_validate(dict(r)) for r in rows]

    def count_upcoming(
        self, genre: str | None = None, tag: str | None = None
    ) -> int:
        filt, fparams = _filter_clause(genre, tag)
        sql = f"SELECT COUNT(*) AS c FROM mv_new_releases WHERE coming_soon = TRUE {filt}"
        row = self._fetchone(sql, tuple(fparams))
        return int(row["c"]) if row else 0

    # ── Just Added lens ──────────────────────────────────────────────────────

    def find_recently_added(
        self,
        since: datetime | None,
        limit: int,
        offset: int,
        genre: str | None = None,
        tag: str | None = None,
    ) -> list[NewReleaseEntry]:
        filt, fparams = _filter_clause(genre, tag)
        if since is not None:
            sql = f"""
                SELECT * FROM mv_new_releases
                WHERE discovered_at >= %s
                  {filt}
                ORDER BY discovered_at DESC, appid DESC
                LIMIT %s OFFSET %s
            """
            params: list = [since, *fparams, limit, offset]
        else:
            sql = f"""
                SELECT * FROM mv_new_releases
                WHERE TRUE
                  {filt}
                ORDER BY discovered_at DESC, appid DESC
                LIMIT %s OFFSET %s
            """
            params = [*fparams, limit, offset]
        rows = self._fetchall(sql, tuple(params))
        return [NewReleaseEntry.model_validate(dict(r)) for r in rows]

    def count_added_since(
        self,
        since: datetime | None,
        genre: str | None = None,
        tag: str | None = None,
    ) -> int:
        filt, fparams = _filter_clause(genre, tag)
        if since is not None:
            sql = f"SELECT COUNT(*) AS c FROM mv_new_releases WHERE discovered_at >= %s {filt}"
            params: list = [since, *fparams]
        else:
            sql = f"SELECT COUNT(*) AS c FROM mv_new_releases WHERE TRUE {filt}"
            params = list(fparams)
        row = self._fetchone(sql, tuple(params))
        return int(row["c"]) if row else 0
