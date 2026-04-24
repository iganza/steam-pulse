"""Tests for the FastAPI application in lambda_functions/api/handler.py."""

import os

import pytest
from fastapi.testclient import TestClient
from library_layer.services.catalog_report_service import CatalogReportService

# ---------------------------------------------------------------------------
# Lightweight in-memory repo mocks — injected at module level before each test
# ---------------------------------------------------------------------------


class _MemReportRepo:
    def __init__(self) -> None:
        self._store: dict[int, dict] = {}

    def find_by_appid(self, appid: int) -> object | None:
        from library_layer.models.report import Report

        data = self._store.get(appid)
        return Report(appid=appid, report_json=data) if data else None

    def upsert(self, data: dict) -> None:
        self._store[data.get("appid")] = data  # type: ignore[index]

    def count_all(self) -> int:
        return len(self._store)


class _MemGameRepo:
    def ensure_stub(self, appid: int, name: str | None = None) -> None:
        pass

    def find_by_appid(self, appid: int) -> None:
        return None

    def list_games(self, **kwargs: object) -> dict:
        return {"total": None, "games": []}

    def list_genres(self) -> list[dict]:
        return []

    def list_tags(self, limit: int = 100) -> list[dict]:
        return []

    def list_tags_grouped(self, limit_per_category: int = 20) -> list[dict]:
        return []


class _MemMatviewRepo:
    def get_total_games_count(self) -> int:
        return 100

    def get_genre_count(self, genre_slug: str) -> int | None:
        return {"indie": 5000, "action": 3000}.get(genre_slug)

    def get_tag_count(self, tag_slug: str) -> int | None:
        return {"roguelike": 800}.get(tag_slug)

    def list_genre_counts(self) -> list[dict]:
        return []

    def list_tag_counts(self, limit: int = 100) -> list[dict]:
        return []

    def list_tags_grouped(self, limit_per_category: int = 20) -> list[dict]:
        return []


class _MemJobRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def find(self, job_id: str) -> dict | None:
        return self._store.get(job_id)

    def upsert(self, job_id: str, status: str, appid: int) -> None:
        self._store[job_id] = {"job_id": job_id, "status": status, "appid": appid}


class _MemWaitlistRepo:
    def __init__(self) -> None:
        self._store: set[str] = set()

    def add(self, email: str) -> bool:
        if email in self._store:
            return False
        self._store.add(email)
        return True


class _MemCatalogReportRepo:
    """Stub for CatalogReportRepository — returns empty results by default."""

    def find_reports(self, **kwargs: object) -> list:
        return []

    def count_reports(self, **kwargs: object) -> int:
        return 0

    def find_candidates(self, **kwargs: object) -> list:
        return []

    def count_candidates(self) -> int:
        return 0


class _MemAnalysisRequestRepo:
    """Stub for AnalysisRequestRepository."""

    def __init__(self) -> None:
        self._store: set[tuple[int, str]] = set()

    def add(self, *, appid: int, email: str) -> bool:
        key = (appid, email)
        if key in self._store:
            return False
        self._store.add(key)
        return True

    def count_for_appid(self, *, appid: int) -> int:
        return sum(1 for a, _ in self._store if a == appid)


class _StubSqsClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_message(self, **kwargs: object) -> None:
        self.sent.append(kwargs)


@pytest.fixture(autouse=True)
def reset_api_state() -> None:
    """Inject fresh in-memory mock repos before each test."""
    import lambda_functions.api.handler as api_module

    api_module._report_repo = _MemReportRepo()  # type: ignore[assignment]
    api_module._game_repo = _MemGameRepo()  # type: ignore[assignment]
    api_module._matview_repo = _MemMatviewRepo()  # type: ignore[assignment]
    api_module._job_repo = _MemJobRepo()  # type: ignore[assignment]
    api_module._waitlist_repo = _MemWaitlistRepo()  # type: ignore[assignment]
    api_module._catalog_report_repo = _MemCatalogReportRepo()  # type: ignore[assignment]
    api_module._analysis_request_repo = _MemAnalysisRequestRepo()  # type: ignore[assignment]
    api_module._catalog_report_service = CatalogReportService(  # type: ignore[assignment]
        api_module._catalog_report_repo,  # type: ignore[arg-type]
        api_module._analysis_request_repo,  # type: ignore[arg-type]
    )
    api_module._sqs_client = _StubSqsClient()  # type: ignore[assignment]
    api_module._email_queue_url = None  # type: ignore[assignment]
    os.environ.pop("DATABASE_URL", None)


@pytest.fixture
def client() -> TestClient:
    from lambda_functions.api.handler import app

    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """GET /health returns 200 with storage key."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "storage" in data


def test_tags_grouped_endpoint(client: TestClient) -> None:
    """GET /api/tags/grouped returns 200 with list of category groups."""
    resp = client.get("/api/tags/grouped")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_tags_grouped_rejects_invalid_limit(client: TestClient) -> None:
    """GET /api/tags/grouped with limit_per_category=0 returns 422."""
    resp = client.get("/api/tags/grouped?limit_per_category=0")
    assert resp.status_code == 422


# /api/preview removed — analysis is now driven by AnalysisRequest messages,
# not an HTTP endpoint. See three-phase-analysis.md.


# ---------------------------------------------------------------------------
# In-memory mocks for the data-driven insight endpoints
# ---------------------------------------------------------------------------


class _MemReviewRepo:
    """Minimal mock for ReviewRepository — returns canned review stats."""

    def find_review_stats(self, appid: int) -> dict:
        return {
            "timeline": [{"week": "2023-10-02", "total": 10, "positive": 8, "pct_positive": 80}],
            "playtime_buckets": [{"bucket": "<2h", "reviews": 5, "pct_positive": 80}],
            "review_velocity": {"reviews_per_day": 1.5, "reviews_last_30_days": 30},
        }


class _FakeGame:
    """Minimal stand-in for a Game model used by the benchmarks endpoint."""

    appid = 440
    name = "TF2"
    release_date = "2007-10-10"
    is_free = True
    price_usd = None


class _MemGameRepoWithBenchmarks(_MemGameRepo):
    """Game repo mock that also supports find_by_appid and find_benchmarks."""

    def find_by_appid(self, appid: int) -> object | None:
        return _FakeGame() if appid == 440 else None

    def find_benchmarks(
        self, appid: int, genre: str, year: int, price: float | None, is_free: bool
    ) -> dict:
        return {"sentiment_rank": 0.75, "popularity_rank": 0.45, "cohort_size": 50}


class _MemTagRepo:
    """Minimal mock for TagRepository."""

    def __init__(
        self,
        genres: list[dict] | None = None,
        tags: list[dict] | None = None,
    ) -> None:
        self._genres = genres or []
        self._tags = tags or []

    def find_genres_for_game(self, appid: int) -> list[dict]:
        return self._genres

    def find_tags_for_game(self, appid: int) -> list[dict]:
        return self._tags


# ---------------------------------------------------------------------------
# review-stats endpoint tests
# ---------------------------------------------------------------------------


def test_review_stats_endpoint_returns_200(client: TestClient) -> None:
    """GET /api/games/{appid}/review-stats returns 200 with the expected top-level keys."""
    import lambda_functions.api.handler as api_module

    api_module._review_repo = _MemReviewRepo()  # type: ignore[assignment]
    resp = client.get("/api/games/440/review-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "timeline" in data
    assert "playtime_buckets" in data
    assert "review_velocity" in data


def test_review_stats_endpoint_forwards_repo_data(client: TestClient) -> None:
    """GET /api/games/{appid}/review-stats passes repo data through unchanged."""
    import lambda_functions.api.handler as api_module

    api_module._review_repo = _MemReviewRepo()  # type: ignore[assignment]
    resp = client.get("/api/games/440/review-stats")
    data = resp.json()
    assert data["review_velocity"]["reviews_per_day"] == 1.5
    assert len(data["timeline"]) == 1


# ---------------------------------------------------------------------------
# benchmarks endpoint tests
# ---------------------------------------------------------------------------


def test_benchmarks_endpoint_returns_404_for_unknown_game(client: TestClient) -> None:
    """GET /api/games/{appid}/benchmarks returns 404 when the game is not in the DB."""
    import lambda_functions.api.handler as api_module

    api_module._game_repo = _MemGameRepoWithBenchmarks()  # type: ignore[assignment]
    api_module._tag_repo = _MemTagRepo()  # type: ignore[assignment]
    resp = client.get("/api/games/9999/benchmarks")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# /api/games/{appid}/report revenue-estimate shaping
# ---------------------------------------------------------------------------


def _build_game_with_revenue(**overrides: object) -> object:
    """Construct a real Game pydantic model with sensible defaults so the
    report endpoint can serialize it."""
    from decimal import Decimal

    from library_layer.models.game import Game

    base: dict = {
        "appid": 440,
        "name": "Team Fortress 2",
        "slug": "team-fortress-2",
        "type": "game",
        "developer": "Valve",
        "price_usd": Decimal("10.00"),
        "is_free": False,
        "review_count": 1000,
        "positive_pct": Decimal("90"),
        "release_date": "2024-01-01",
    }
    base.update(overrides)
    return Game.model_validate(base)


class _MemGameRepoWithGame(_MemGameRepo):
    def __init__(self, game: object | None) -> None:
        self._game = game

    def find_by_appid(self, appid: int) -> object | None:
        return self._game if appid == 440 else None


def test_report_endpoint_includes_revenue_estimate_when_present(client: TestClient) -> None:
    """GET /api/games/{appid}/report surfaces owners/revenue/method when all non-null."""
    from decimal import Decimal

    import lambda_functions.api.handler as api_module

    game = _build_game_with_revenue(
        estimated_owners=30_000,
        estimated_revenue_usd=Decimal("300000.00"),
        revenue_estimate_method="boxleiter_v1",
        revenue_estimate_reason=None,
    )
    api_module._game_repo = _MemGameRepoWithGame(game)  # type: ignore[assignment]
    api_module._tag_repo = _MemTagRepo()  # type: ignore[assignment]

    resp = client.get("/api/games/440/report")
    assert resp.status_code == 200
    game_meta = resp.json()["game"]
    assert game_meta["estimated_owners"] == 30_000
    assert game_meta["estimated_revenue_usd"] == 300000.0
    assert game_meta["revenue_estimate_method"] == "boxleiter_v1"
    # Reason is absent when the estimate succeeded.
    assert "revenue_estimate_reason" not in game_meta


def test_report_endpoint_omits_revenue_estimate_when_null(client: TestClient) -> None:
    """When owners/revenue are both NULL (e.g. free-to-play), the numeric
    keys are omitted but the reason code is surfaced so the UI can render
    precise empty-state copy."""
    import lambda_functions.api.handler as api_module

    game = _build_game_with_revenue(
        is_free=True,
        price_usd=None,
        estimated_owners=None,
        estimated_revenue_usd=None,
        revenue_estimate_method=None,
        revenue_estimate_reason="free_to_play",
    )
    api_module._game_repo = _MemGameRepoWithGame(game)  # type: ignore[assignment]
    api_module._tag_repo = _MemTagRepo()  # type: ignore[assignment]

    resp = client.get("/api/games/440/report")
    assert resp.status_code == 200
    game_meta = resp.json()["game"]
    assert "estimated_owners" not in game_meta
    assert "estimated_revenue_usd" not in game_meta
    assert "revenue_estimate_method" not in game_meta
    assert game_meta["revenue_estimate_reason"] == "free_to_play"


def test_report_endpoint_omits_method_when_only_method_present(client: TestClient) -> None:
    """Defense-in-depth: if only method is set (shouldn't happen post-repo fix) we must
    still omit the method to match the 'method present == estimate available' contract."""
    import lambda_functions.api.handler as api_module

    game = _build_game_with_revenue(
        estimated_owners=None,
        estimated_revenue_usd=None,
        revenue_estimate_method="boxleiter_v1",
    )
    api_module._game_repo = _MemGameRepoWithGame(game)  # type: ignore[assignment]
    api_module._tag_repo = _MemTagRepo()  # type: ignore[assignment]

    resp = client.get("/api/games/440/report")
    assert resp.status_code == 200
    game_meta = resp.json()["game"]
    assert "estimated_owners" not in game_meta
    assert "estimated_revenue_usd" not in game_meta
    assert "revenue_estimate_method" not in game_meta


def test_benchmarks_endpoint_returns_cohort_data(client: TestClient) -> None:
    """GET /api/games/{appid}/benchmarks returns ranking data when game and genre exist."""
    import lambda_functions.api.handler as api_module

    api_module._game_repo = _MemGameRepoWithBenchmarks()  # type: ignore[assignment]
    api_module._tag_repo = _MemTagRepo(genres=[{"name": "Action", "id": 1}])  # type: ignore[assignment]
    resp = client.get("/api/games/440/benchmarks")
    assert resp.status_code == 200
    data = resp.json()
    assert "sentiment_rank" in data
    assert "cohort_size" in data
    assert data["cohort_size"] == 50


# ---------------------------------------------------------------------------
# /api/publishers/{slug}/analytics
# ---------------------------------------------------------------------------


class _StubAnalyticsRepo:
    """Minimal stub that records the entity slug passed to the portfolio methods."""

    def __init__(self) -> None:
        self.developer_calls: list[str] = []
        self.publisher_calls: list[str] = []

    def find_developer_portfolio(self, slug: str) -> dict:
        self.developer_calls.append(slug)
        return {"developer": "Stub Dev", "developer_slug": slug, "summary": {}, "games": []}

    def find_publisher_portfolio(self, slug: str) -> dict:
        self.publisher_calls.append(slug)
        return {
            "publisher": "Stub Pub",
            "publisher_slug": slug,
            "summary": {"total_games": 2, "total_reviews": 300},
            "games": [{"appid": 1}, {"appid": 2}],
        }


def test_publisher_analytics_endpoint_returns_portfolio(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/publishers/{slug}/analytics shapes the repo response through unchanged."""
    import lambda_functions.api.handler as api_module

    stub = _StubAnalyticsRepo()
    monkeypatch.setattr(api_module, "_analytics_repo", stub)
    resp = client.get("/api/publishers/big-pub/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["publisher"] == "Stub Pub"
    assert data["publisher_slug"] == "big-pub"
    assert data["summary"]["total_games"] == 2
    assert len(data["games"]) == 2
    assert stub.publisher_calls == ["big-pub"]


# ---------------------------------------------------------------------------
# waitlist endpoint tests
# ---------------------------------------------------------------------------


def test_waitlist_registers_new_email(client: TestClient) -> None:
    """POST /api/waitlist with a new email returns status=registered."""
    resp = client.post("/api/waitlist", json={"email": "dev@example.com"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "registered"


def test_waitlist_duplicate_email_returns_already_registered(client: TestClient) -> None:
    """POST /api/waitlist with an already-registered email returns status=already_registered."""
    client.post("/api/waitlist", json={"email": "dev@example.com"})
    resp = client.post("/api/waitlist", json={"email": "dev@example.com"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_registered"


def test_waitlist_enqueues_sqs_message_for_new_email(client: TestClient) -> None:
    """POST /api/waitlist enqueues a WaitlistConfirmationMessage for a new email."""
    import json as _json
    import lambda_functions.api.handler as api_module

    api_module._email_queue_url = "https://sqs.us-west-2.amazonaws.com/123456789/email-queue"  # type: ignore[assignment]
    client.post("/api/waitlist", json={"email": "dev@example.com"})

    sqs_stub: _StubSqsClient = api_module._sqs_client  # type: ignore[assignment]
    assert len(sqs_stub.sent) == 1
    body = _json.loads(sqs_stub.sent[0]["MessageBody"])
    assert body["message_type"] == "waitlist_confirmation"
    assert body["email"] == "dev@example.com"


def test_waitlist_normalizes_email(client: TestClient) -> None:
    """POST /api/waitlist strips and lowercases the email before storing."""
    resp = client.post("/api/waitlist", json={"email": "  Dev@Example.com  "})
    assert resp.status_code == 200
    # A second request with the normalized form should deduplicate
    resp2 = client.post("/api/waitlist", json={"email": "dev@example.com"})
    assert resp2.json()["status"] == "already_registered"


# ---------------------------------------------------------------------------
# /api/games total count logic
# ---------------------------------------------------------------------------


def test_games_genre_only_returns_matview_total(client: TestClient) -> None:
    """Genre-only filter uses pre-computed count from mv_genre_counts."""
    resp = client.get("/api/games?genre=indie")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5000
    assert data["has_more"] is True


def test_games_tag_only_returns_matview_total(client: TestClient) -> None:
    """Tag-only filter uses pre-computed count from mv_tag_counts."""
    resp = client.get("/api/games?tag=roguelike")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 800
    assert data["has_more"] is True


def test_games_unfiltered_returns_estimated_total(client: TestClient) -> None:
    """Unfiltered browse uses pg_class estimate."""
    resp = client.get("/api/games")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 100
    assert data["has_more"] is True


def test_games_complex_filter_empty_result(client: TestClient) -> None:
    """Complex filters with empty result return total=null, has_more=false."""
    resp = client.get("/api/games?genre=indie&sentiment=positive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] is None
    assert data["has_more"] is False


def test_games_complex_filter_full_page(client: TestClient) -> None:
    """Complex filters with a full page of results set has_more=true."""
    import lambda_functions.api.handler as api_module

    # Mock list_games to return exactly `limit` (24) games
    class _FullPageGameRepo:
        def ensure_stub(self, appid: int, name: str | None = None) -> None:
            pass

        def list_games(self, **kwargs: object) -> dict:
            return {"total": None, "games": [{"appid": i} for i in range(24)]}

    api_module._game_repo = _FullPageGameRepo()  # type: ignore[assignment]
    resp = client.get("/api/games?genre=indie&sentiment=positive")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] is None
    assert data["has_more"] is True
    assert len(data["games"]) == 24


def test_games_serializes_datetime_fields(client: TestClient) -> None:
    """/api/games must serialize datetime columns (last_analyzed, crawled_at) without crashing."""
    import datetime as dt

    import lambda_functions.api.handler as api_module

    class _DatetimeGameRepo:
        def ensure_stub(self, appid: int, name: str | None = None) -> None:
            pass

        def list_games(self, **kwargs: object) -> dict:
            return {
                "total": None,
                "games": [
                    {
                        "appid": 1,
                        "name": "Test",
                        "last_analyzed": dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc),
                        "crawled_at": dt.datetime(2026, 1, 2, 12, 0, tzinfo=dt.timezone.utc),
                    }
                ],
            }

    api_module._game_repo = _DatetimeGameRepo()  # type: ignore[assignment]
    resp = client.get("/api/games")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "private, max-age=300"
    assert resp.json()["games"][0]["last_analyzed"].startswith("2026-01-01")


def test_waitlist_rejects_invalid_email(client: TestClient) -> None:
    """POST /api/waitlist with a non-email string returns 422."""
    resp = client.post("/api/waitlist", json={"email": "not-an-email"})
    assert resp.status_code == 422


def test_waitlist_rejects_empty_email(client: TestClient) -> None:
    """POST /api/waitlist with an empty string returns 422."""
    resp = client.post("/api/waitlist", json={"email": ""})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Builder lens — /api/analytics/metrics + /api/analytics/trend-query
# ---------------------------------------------------------------------------


def test_analytics_metrics_endpoint(client: TestClient) -> None:
    """GET /api/analytics/metrics returns the registry catalog."""
    resp = client.get("/api/analytics/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert "metrics" in body
    ids = {m["id"] for m in body["metrics"]}
    assert "releases" in ids
    assert "avg_steam_pct" in ids
    # Every entry has the shape the frontend expects.
    for m in body["metrics"]:
        assert {
            "id",
            "label",
            "unit",
            "category",
            "source",
            "column",
            "default_chart_hint",
        } <= m.keys()


def test_analytics_trend_query_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /api/analytics/trend-query returns shaped periods for valid metrics."""
    from datetime import datetime
    from unittest.mock import MagicMock

    import lambda_functions.api.handler as api_module
    from library_layer.services.analytics_service import AnalyticsService

    mock_repo = MagicMock()
    mock_repo.query_metrics.return_value = [
        {"period": datetime(2024, 10, 1), "releases": 120},
        {"period": datetime(2024, 11, 1), "releases": 135},
    ]
    # monkeypatch restores the original service after the test — avoids
    # bleeding the mock into subsequent API tests that share the module.
    monkeypatch.setattr(api_module, "_analytics_service", AnalyticsService(mock_repo))

    resp = client.get("/api/analytics/trend-query?metrics=releases&granularity=month&limit=12")
    assert resp.status_code == 200
    body = resp.json()
    assert body["granularity"] == "month"
    assert len(body["periods"]) == 2
    assert body["periods"][0]["releases"] == 120
    assert [m["id"] for m in body["metrics"]] == ["releases"]


def test_analytics_trend_query_unknown_metric_returns_400(client: TestClient) -> None:
    resp = client.get("/api/analytics/trend-query?metrics=not_a_metric&granularity=month")
    assert resp.status_code == 400
    assert "unknown metric" in resp.json()["detail"]


def test_analytics_trend_query_invalid_granularity_returns_400(client: TestClient) -> None:
    resp = client.get("/api/analytics/trend-query?metrics=releases&granularity=daily")
    assert resp.status_code == 400
    assert "Invalid granularity" in resp.json()["detail"]


def test_analytics_trend_query_empty_metrics_returns_400(client: TestClient) -> None:
    resp = client.get("/api/analytics/trend-query?metrics=&granularity=month")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/reports — Reports / Catalog page
# ---------------------------------------------------------------------------


def test_reports_returns_200_with_shape(client: TestClient) -> None:
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_more" in data
    assert "sort" in data
    assert data["sort"] == "last_analyzed"


def test_reports_invalid_sort_falls_back(client: TestClient) -> None:
    resp = client.get("/api/reports?sort=bogus")
    assert resp.status_code == 200
    assert resp.json()["sort"] == "last_analyzed"


def test_reports_has_cache_header(client: TestClient) -> None:
    resp = client.get("/api/reports")
    assert "s-maxage" in resp.headers.get("cache-control", "")


def test_coming_soon_returns_200_with_shape(client: TestClient) -> None:
    resp = client.get("/api/reports/coming-soon")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["sort"] == "request_count"


def test_coming_soon_invalid_sort_falls_back(client: TestClient) -> None:
    resp = client.get("/api/reports/coming-soon?sort=nope")
    assert resp.status_code == 200
    assert resp.json()["sort"] == "request_count"


def test_request_analysis_new_request(client: TestClient) -> None:
    resp = client.post(
        "/api/reports/request-analysis",
        json={"appid": 440, "email": "test@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "requested"
    assert data["request_count"] == 1


def test_request_analysis_duplicate(client: TestClient) -> None:
    client.post("/api/reports/request-analysis", json={"appid": 440, "email": "test@example.com"})
    resp = client.post(
        "/api/reports/request-analysis",
        json={"appid": 440, "email": "test@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_requested"
    assert resp.json()["request_count"] == 1


def test_request_analysis_email_normalized(client: TestClient) -> None:
    resp = client.post(
        "/api/reports/request-analysis",
        json={"appid": 440, "email": "  TEST@Example.COM  "},
    )
    assert resp.status_code == 200
    # Second request with the normalized form should be duplicate
    resp2 = client.post(
        "/api/reports/request-analysis",
        json={"appid": 440, "email": "test@example.com"},
    )
    assert resp2.json()["status"] == "already_requested"


def test_request_analysis_invalid_email_returns_422(client: TestClient) -> None:
    resp = client.post(
        "/api/reports/request-analysis",
        json={"appid": 440, "email": "not-an-email"},
    )
    assert resp.status_code == 422


def test_report_request_count(client: TestClient) -> None:
    # No requests yet
    resp = client.get("/api/reports/request-count/440")
    assert resp.status_code == 200
    assert resp.json()["request_count"] == 0

    # Add a request, then check count
    client.post("/api/reports/request-analysis", json={"appid": 440, "email": "a@b.com"})
    resp = client.get("/api/reports/request-count/440")
    assert resp.json()["request_count"] == 1
