"""Tests for the FastAPI application in lambda_functions/api/handler.py."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_api_state() -> None:
    """Reset module-level singletons between tests."""
    from lambda_functions.api import handler as api_module

    # Reset storage to a fresh InMemoryStorage
    from library_layer.storage import InMemoryStorage
    api_module._storage = InMemoryStorage()


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

    # Pre-populate storage with a full report
    asyncio.run(api_module._storage.upsert_report(440, {
        "game_name": "Team Fortress 2",
        "overall_sentiment": "Very Positive",
        "sentiment_score": 0.93,
        "one_liner": "A timeless class-based shooter with wild humor.",
        "audience_profile": {"ideal_player": "FPS fans who enjoy team play"},
        "appid": 440,
        "dev_priorities": [{"action": "Fix bots", "why_it_matters": "Ruins casual play"}],
        "design_strengths": ["Class variety", "Map design"],
        "churn_triggers": ["Bot problem in casual mode"],
    }))

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

    asyncio.run(api_module._storage.upsert_report(440, {
        "game_name": "Team Fortress 2",
        "overall_sentiment": "Very Positive",
        "sentiment_score": 0.93,
        "one_liner": "Great game.",
        "audience_profile": {},
        "appid": 440,
    }))

    # Multiple requests from same client — all should succeed (no 402)
    for _ in range(3):
        resp = client.post("/api/preview", json={"appid": 440})
        assert resp.status_code == 200


def test_validate_key_rejects_invalid_key(client: TestClient) -> None:
    """POST /api/validate-key with invalid key returns 403."""
    from lambda_functions.api import handler as api_module

    # Mock the LS API to return an invalid response
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"valid": False}

    with patch.object(
        api_module._http_client, "post", new=AsyncMock(return_value=mock_resp)
    ):
        resp = client.post(
            "/api/validate-key",
            json={"key": "fake-key-does-not-exist", "appid": 440},
        )

    assert resp.status_code == 403
    assert resp.json()["error"] == "invalid_key"
