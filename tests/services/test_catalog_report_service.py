"""Unit tests for CatalogReportService — sort validation, pagination, request flow."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from library_layer.models.catalog import AnalysisCandidateEntry, CatalogReportEntry
from library_layer.services.catalog_report_service import CatalogReportService


def _report_entry(appid: int) -> CatalogReportEntry:
    return CatalogReportEntry(
        appid=appid,
        name=f"Game {appid}",
        slug=f"game-{appid}",
        last_analyzed=datetime(2026, 4, 1, tzinfo=UTC),
    )


def _candidate_entry(appid: int, request_count: int = 0) -> AnalysisCandidateEntry:
    return AnalysisCandidateEntry(
        appid=appid,
        game_name=f"Game {appid}",
        slug=f"game-{appid}",
        request_count=request_count,
    )


def _make_service() -> tuple[CatalogReportService, MagicMock, MagicMock]:
    catalog_repo = MagicMock()
    request_repo = MagicMock()
    svc = CatalogReportService(catalog_repo, request_repo)
    return svc, catalog_repo, request_repo


# ── get_available_reports ──────────────────────────────────────────────


def test_get_available_reports_returns_items() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_reports.return_value = [_report_entry(440)]
    catalog_repo.count_reports.return_value = 1

    result = svc.get_available_reports(
        genre=None, tag=None, sort="last_analyzed", page=1, page_size=24,
    )

    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["appid"] == 440
    assert result["page"] == 1
    assert result["sort"] == "last_analyzed"


def test_get_available_reports_invalid_sort_falls_back() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_reports.return_value = []
    catalog_repo.count_reports.return_value = 0

    result = svc.get_available_reports(
        genre=None, tag=None, sort="invalid_sort", page=1, page_size=24,
    )

    assert result["sort"] == "last_analyzed"
    _, kwargs = catalog_repo.find_reports.call_args
    assert kwargs["sort"] == "last_analyzed"


def test_get_available_reports_passes_filters() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_reports.return_value = []
    catalog_repo.count_reports.return_value = 0

    svc.get_available_reports(
        genre="action", tag="fps", sort="review_count", page=2, page_size=10,
    )

    _, kwargs = catalog_repo.find_reports.call_args
    assert kwargs["genre"] == "action"
    assert kwargs["tag"] == "fps"
    assert kwargs["sort"] == "review_count"
    assert kwargs["limit"] == 10
    assert kwargs["offset"] == 10


def test_get_available_reports_has_more() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_reports.return_value = [_report_entry(i) for i in range(24)]
    catalog_repo.count_reports.return_value = 50

    result = svc.get_available_reports(
        genre=None, tag=None, sort="last_analyzed", page=1, page_size=24,
    )

    assert result["has_more"] is True


def test_get_available_reports_page_clamping() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_reports.return_value = []
    catalog_repo.count_reports.return_value = 0

    result = svc.get_available_reports(
        genre=None, tag=None, sort="last_analyzed", page=-5, page_size=200,
    )

    assert result["page"] == 1
    assert result["page_size"] == 100  # clamped to max


# ── get_coming_soon ────────────────────────────────────────────────────


def test_get_coming_soon_returns_items() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_candidates.return_value = [_candidate_entry(730, request_count=5)]
    catalog_repo.count_candidates.return_value = 1

    result = svc.get_coming_soon(sort="request_count", page=1, page_size=24)

    assert result["total"] == 1
    assert result["items"][0]["request_count"] == 5
    assert result["sort"] == "request_count"


def test_get_coming_soon_invalid_sort_falls_back() -> None:
    svc, catalog_repo, _ = _make_service()
    catalog_repo.find_candidates.return_value = []
    catalog_repo.count_candidates.return_value = 0

    result = svc.get_coming_soon(sort="bogus", page=1, page_size=24)

    assert result["sort"] == "request_count"


# ── request_analysis ───────────────────────────────────────────────────


def test_request_analysis_new_request() -> None:
    svc, _, request_repo = _make_service()
    request_repo.add.return_value = True
    request_repo.count_for_appid.return_value = 3

    result = svc.request_analysis(appid=440, email="test@example.com")

    assert result["status"] == "requested"
    assert result["request_count"] == 3
    request_repo.add.assert_called_once_with(appid=440, email="test@example.com")


def test_request_analysis_duplicate() -> None:
    svc, _, request_repo = _make_service()
    request_repo.add.return_value = False
    request_repo.count_for_appid.return_value = 5

    result = svc.request_analysis(appid=440, email="test@example.com")

    assert result["status"] == "already_requested"
    assert result["request_count"] == 5


# ── get_request_count ──────────────────────────────────────────────────


def test_get_request_count() -> None:
    svc, _, request_repo = _make_service()
    request_repo.count_for_appid.return_value = 7

    assert svc.get_request_count(appid=440) == 7
