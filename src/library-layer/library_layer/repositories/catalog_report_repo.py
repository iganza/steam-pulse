"""CatalogReportRepository — pure SQL I/O backed by mv_catalog_reports and mv_analysis_candidates.

All queries hit materialized views, never the base tables. Both matviews are
registered in MATVIEW_NAMES (matview_repo.py) and refreshed by the existing
matview_refresh_handler Lambda.
"""

from __future__ import annotations

from typing import Literal

from library_layer.models.catalog import AnalysisCandidateEntry, CatalogReportEntry
from library_layer.repositories.base import BaseRepository

ReportSort = Literal["last_analyzed", "review_count", "positive_pct", "hidden_gem_score"]
CandidateSort = Literal["request_count", "review_count"]

# Minimum reviews required to appear on the "Best on Steam" leaderboard so
# tiny-sample 100% games can't outrank well-reviewed titles.
_BEST_ON_STEAM_MIN_REVIEWS = 500


def _filter_clause(
    genre: str | None,
    tag: str | None,
    sort: ReportSort | None = None,
) -> tuple[str, list]:
    """Build genre/tag/sort-implied filter SQL fragment + params.

    Uses the @> array-contains operator so GIN indexes are used.
    """
    parts: list[str] = []
    params: list = []
    if genre:
        parts.append("genre_slugs @> ARRAY[%s]::text[]")
        params.append(genre)
    if tag:
        parts.append("tag_slugs @> ARRAY[%s]::text[]")
        params.append(tag)
    if sort == "positive_pct":
        parts.append("review_count >= %s")
        params.append(_BEST_ON_STEAM_MIN_REVIEWS)
    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


_SORT_MAP: dict[ReportSort, str] = {
    "last_analyzed": "last_analyzed DESC",
    "review_count": "review_count DESC NULLS LAST",
    "positive_pct": "positive_pct DESC NULLS LAST",
    "hidden_gem_score": "hidden_gem_score DESC NULLS LAST",
}

_CANDIDATE_SORT_MAP: dict[CandidateSort, str] = {
    "request_count": "request_count DESC, review_count DESC NULLS LAST",
    "review_count": "review_count DESC NULLS LAST",
}


class CatalogReportRepository(BaseRepository):
    """Read-only access to mv_catalog_reports and mv_analysis_candidates."""

    # ── Available Reports ──────────────────────────────────────────────

    def find_reports(
        self,
        *,
        genre: str | None,
        tag: str | None,
        sort: ReportSort,
        limit: int,
        offset: int,
    ) -> list[CatalogReportEntry]:
        filt, fparams = _filter_clause(genre, tag, sort)
        order = _SORT_MAP.get(sort, "last_analyzed DESC")
        sql = f"""
            SELECT * FROM mv_catalog_reports
            WHERE TRUE {filt}
            ORDER BY {order}, appid DESC
            LIMIT %s OFFSET %s
        """
        rows = self._fetchall(sql, tuple([*fparams, limit, offset]))
        return [CatalogReportEntry.model_validate(dict(r)) for r in rows]

    def count_reports(
        self,
        *,
        genre: str | None,
        tag: str | None,
        sort: ReportSort | None = None,
    ) -> int:
        filt, fparams = _filter_clause(genre, tag, sort)
        sql = f"SELECT COUNT(*) AS c FROM mv_catalog_reports WHERE TRUE {filt}"
        row = self._fetchone(sql, tuple(fparams))
        return int(row["c"]) if row else 0

    # ── Coming Soon (analysis candidates) ──────────────────────────────

    def find_candidates(
        self,
        *,
        sort: CandidateSort,
        limit: int,
        offset: int,
    ) -> list[AnalysisCandidateEntry]:
        order = _CANDIDATE_SORT_MAP.get(sort, "request_count DESC, review_count DESC NULLS LAST")
        sql = f"""
            SELECT * FROM mv_analysis_candidates
            ORDER BY {order}, appid DESC
            LIMIT %s OFFSET %s
        """
        rows = self._fetchall(sql, (limit, offset))
        return [AnalysisCandidateEntry.model_validate(dict(r)) for r in rows]

    def count_candidates(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS c FROM mv_analysis_candidates")
        return int(row["c"]) if row else 0
