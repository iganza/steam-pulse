"""Smoke tests for /api/new-releases/* endpoints."""

import httpx
import pytest

pytestmark = pytest.mark.smoke


def test_released(api: httpx.Client) -> None:
    r = api.get("/api/new-releases/released")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert len(data["items"]) > 0


def test_upcoming(api: httpx.Client) -> None:
    r = api.get("/api/new-releases/upcoming")
    assert r.status_code == 200


def test_added(api: httpx.Client) -> None:
    r = api.get("/api/new-releases/added")
    assert r.status_code == 200
