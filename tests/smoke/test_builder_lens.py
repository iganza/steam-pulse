"""Smoke tests for the Builder lens: /api/analytics/trend-query and /api/analytics/metrics."""

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_single_metric(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trend-query",
        params={"metrics": "releases", "granularity": "year", "limit": 3},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["periods"]) > 0
    assert "releases" in data["periods"][0]


def test_multi_metric(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trend-query",
        params={"metrics": "releases,avg_steam_pct", "limit": 3},
    )
    assert r.status_code == 200
    assert len(r.json()["metrics"]) == 2


def test_type_param(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trend-query",
        params={"metrics": "releases", "type": "all", "limit": 3},
    )
    assert r.status_code == 200


def test_genre_param(api: httpx.Client) -> None:
    r = api.get(
        "/api/analytics/trend-query",
        params={"metrics": "releases", "genre": "action", "limit": 3},
    )
    assert r.status_code == 200


def test_unknown_metric_returns_400(api: httpx.Client) -> None:
    r = api.get("/api/analytics/trend-query", params={"metrics": "not_a_metric"})
    assert r.status_code == 400


def test_empty_metrics_returns_400(api: httpx.Client) -> None:
    r = api.get("/api/analytics/trend-query", params={"metrics": ""})
    assert r.status_code == 400


def test_metrics_catalog(api: httpx.Client) -> None:
    r = api.get("/api/analytics/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "metrics" in data
    assert len(data["metrics"]) > 0
