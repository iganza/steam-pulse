"""Tests for steam_source.py — metrics callback + endpoint name mapping."""

import asyncio
import re

import httpx
import pytest
from library_layer.steam_source import (
    APP_DETAILS_URL,
    APP_LIST_URL,
    DECK_COMPAT_URL,
    REVIEWS_URL,
    DirectSteamSource,
    SteamAPIError,
    _endpoint_name,
)
from pytest_httpx import HTTPXMock

_APP_DETAILS_RE = re.compile(re.escape(APP_DETAILS_URL))


# ── _endpoint_name mapping ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (REVIEWS_URL.format(appid=440), "reviews"),
        (APP_DETAILS_URL, "app_details"),
        (DECK_COMPAT_URL, "deck_compat"),
        (APP_LIST_URL, "app_list"),
        ("https://example.com/unknown", "unknown"),
    ],
)
def test_endpoint_name_mapping(url: str, expected: str) -> None:
    assert _endpoint_name(url) == expected


# ── on_request callback ─────────────────────────────────────────────────────


@pytest.fixture()
def metrics_log() -> list[tuple[str, str, int, float]]:
    return []


@pytest.fixture()
def steam(metrics_log: list, monkeypatch: pytest.MonkeyPatch) -> DirectSteamSource:
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    client = httpx.AsyncClient()

    def callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
        metrics_log.append((endpoint, region, status_code, latency_ms))

    return DirectSteamSource(client, on_request=callback)


def test_on_request_called_on_success(
    steam: DirectSteamSource,
    metrics_log: list,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {}}})

    asyncio.run(steam.get_app_details(440))

    assert len(metrics_log) == 1
    endpoint, region, status, latency = metrics_log[0]
    assert endpoint == "app_details"
    assert region == "us-west-2"
    assert status == 200
    assert latency > 0


def test_on_request_called_on_429_retry(
    steam: DirectSteamSource,
    metrics_log: list,
    httpx_mock: HTTPXMock,
) -> None:
    """Callback fires on EVERY attempt including retries."""
    httpx_mock.add_response(url=_APP_DETAILS_RE, status_code=429)
    httpx_mock.add_response(url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {}}})

    asyncio.run(steam.get_app_details(440))

    assert len(metrics_log) == 2
    assert metrics_log[0][2] == 429
    assert metrics_log[1][2] == 200


def test_on_request_called_on_error(
    steam: DirectSteamSource,
    metrics_log: list,
    httpx_mock: HTTPXMock,
) -> None:
    """Callback fires even when the request ultimately raises."""
    httpx_mock.add_response(url=_APP_DETAILS_RE, status_code=403)

    with pytest.raises(SteamAPIError):
        asyncio.run(steam.get_app_details(440))

    assert len(metrics_log) == 1
    assert metrics_log[0][2] == 403


def test_on_request_none_default(httpx_mock: HTTPXMock) -> None:
    """No callback (default) doesn't crash."""
    httpx_mock.add_response(url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {}}})

    source = DirectSteamSource(httpx.AsyncClient())
    result = asyncio.run(source.get_app_details(440))
    assert result == {}


def test_callback_exception_does_not_break_request(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken callback must not prevent the API call from succeeding."""
    httpx_mock.add_response(
        url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {"name": "TF2"}}}
    )

    def bad_callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
        raise RuntimeError("metrics exploded")

    source = DirectSteamSource(httpx.AsyncClient(), on_request=bad_callback)
    result = asyncio.run(source.get_app_details(440))
    assert result["name"] == "TF2"
