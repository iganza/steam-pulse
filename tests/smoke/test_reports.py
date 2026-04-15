"""Smoke tests for /api/reports/* endpoints."""

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_reports_list(api: httpx.Client) -> None:
    r = api.get("/api/reports", params={"limit": 5})
    assert r.status_code == 200
    data = r.json()
    assert "items" in data


def test_reports_coming_soon(api: httpx.Client) -> None:
    r = api.get("/api/reports/coming-soon")
    assert r.status_code == 200
