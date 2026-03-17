"""Tests for the FastAPI application in lambda_functions/api/handler.py."""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


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

    def list_games(self, **kwargs: object) -> list[dict]:
        return []

    def list_genres(self) -> list[dict]:
        return []

    def list_tags(self, limit: int = 100) -> list[dict]:
        return []


class _MemJobRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def find(self, job_id: str) -> dict | None:
        return self._store.get(job_id)

    def upsert(self, job_id: str, status: str, appid: int) -> None:
        self._store[job_id] = {"job_id": job_id, "status": status, "appid": appid}


@pytest.fixture(autouse=True)
def reset_api_state() -> None:
    """Inject fresh in-memory mock repos before each test."""
    import lambda_functions.api.handler as api_module
    api_module._report_repo = _MemReportRepo()  # type: ignore[assignment]
    api_module._game_repo = _MemGameRepo()  # type: ignore[assignment]
    api_module._job_repo = _MemJobRepo()  # type: ignore[assignment]
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


def test_preview_requires_appid(client: TestClient) -> None:
    """POST /api/preview with empty body returns 422 validation error."""
    resp = client.post("/api/preview", json={})
    assert resp.status_code == 422


def test_preview_returns_partial_report(client: TestClient) -> None:
    """POST /api/preview with cached report returns only preview fields, not full report."""
    from lambda_functions.api import handler as api_module

    report = {
        "game_name": "Team Fortress 2",
        "overall_sentiment": "Very Positive",
        "sentiment_score": 0.93,
        "one_liner": "A timeless class-based shooter with wild humor.",
        "audience_profile": {"ideal_player": "FPS fans who enjoy team play"},
        "appid": 440,
        "dev_priorities": [{"action": "Fix bots", "why_it_matters": "Ruins casual play"}],
        "design_strengths": ["Class variety", "Map design"],
        "churn_triggers": ["Bot problem in casual mode"],
    }
    asyncio.run(api_module._upsert_report(440, report))

    resp = client.post("/api/preview", json={"appid": 440})
    assert resp.status_code == 200
    data = resp.json()

    # Preview fields present
    assert data["game_name"] == "Team Fortress 2"
    assert data["overall_sentiment"] == "Very Positive"
    assert "sentiment_score" in data
    assert "one_liner" in data

    # Premium fields NOT in preview response
    assert "dev_priorities" not in data
    assert "design_strengths" not in data
    assert "churn_triggers" not in data


def test_preview_unconditional(client: TestClient) -> None:
    """POST /api/preview returns 200 for every request — no rate limiting."""
    from lambda_functions.api import handler as api_module

    report = {
        "game_name": "Team Fortress 2",
        "overall_sentiment": "Very Positive",
        "sentiment_score": 0.93,
        "one_liner": "Great game.",
        "audience_profile": {},
        "appid": 440,
    }
    asyncio.run(api_module._upsert_report(440, report))

    # Multiple requests from same client — all should succeed (no 402)
    for _ in range(3):
        resp = client.post("/api/preview", json={"appid": 440})
        assert resp.status_code == 200


def test_validate_key_returns_not_found_when_no_report(client: TestClient) -> None:
    """POST /api/validate-key returns 404 when report has not been analyzed yet."""
    resp = client.post(
        "/api/validate-key",
        json={"license_key": "any-key", "appid": 440},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "not_found"
