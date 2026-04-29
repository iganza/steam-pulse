"""CatalogReportService — business logic for the /reports page.

Handles pagination, sort validation, and the request-analysis flow.
All data access goes through CatalogReportRepository and AnalysisRequestRepository.
"""

from __future__ import annotations

from typing import cast, get_args

from aws_lambda_powertools import Logger
from library_layer.repositories.analysis_request_repo import AnalysisRequestRepository
from library_layer.repositories.catalog_report_repo import (
    CandidateSort,
    CatalogReportRepository,
    ReportSort,
)

logger = Logger()

_PAGE_SIZE_MAX = 100
_VALID_REPORT_SORTS: set[str] = set(get_args(ReportSort))
_VALID_CANDIDATE_SORTS: set[str] = set(get_args(CandidateSort))


def _clamp_page(page: int, page_size: int) -> tuple[int, int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, _PAGE_SIZE_MAX))
    offset = (page - 1) * page_size
    return page, page_size, offset


class CatalogReportService:
    """Reports page: available reports + coming soon + request analysis."""

    def __init__(
        self,
        catalog_report_repo: CatalogReportRepository,
        analysis_request_repo: AnalysisRequestRepository,
    ) -> None:
        self._catalog_repo = catalog_report_repo
        self._request_repo = analysis_request_repo

    def get_available_reports(
        self,
        *,
        genre: str | None,
        tag: str | None,
        sort: str,
        page: int,
        page_size: int,
    ) -> dict:
        sort_key = cast(ReportSort, sort) if sort in _VALID_REPORT_SORTS else cast(ReportSort, "last_analyzed")
        page, page_size, offset = _clamp_page(page, page_size)

        items = self._catalog_repo.find_reports(
            genre=genre, tag=tag, sort=sort_key, limit=page_size, offset=offset,
        )
        total = self._catalog_repo.count_reports(genre=genre, tag=tag, sort=sort_key)

        return {
            "items": [it.model_dump(mode="json") for it in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
            "sort": sort_key,
            "filters": {"genre": genre, "tag": tag},
        }

    def get_coming_soon(
        self,
        *,
        sort: str,
        page: int,
        page_size: int,
    ) -> dict:
        sort_key = cast(CandidateSort, sort) if sort in _VALID_CANDIDATE_SORTS else cast(CandidateSort, "request_count")
        page, page_size, offset = _clamp_page(page, page_size)

        items = self._catalog_repo.find_candidates(
            sort=sort_key, limit=page_size, offset=offset,
        )
        total = self._catalog_repo.count_candidates()

        return {
            "items": [it.model_dump(mode="json") for it in items],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
            "sort": sort_key,
        }

    def request_analysis(self, *, appid: int, email: str) -> dict:
        """Record an analysis request for a game. Returns status and request count."""
        inserted = self._request_repo.add(appid=appid, email=email)
        count = self._request_repo.count_for_appid(appid=appid)
        status = "requested" if inserted else "already_requested"
        logger.info(
            "Analysis request recorded",
            extra={"appid": appid, "status": status, "request_count": count},
        )
        return {"status": status, "request_count": count}

    def get_request_count(self, *, appid: int) -> int:
        """Get the number of analysis requests for a game."""
        return self._request_repo.count_for_appid(appid=appid)
