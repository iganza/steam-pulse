"""Tests for steam_source.py — metrics callback + endpoint name mapping."""

import asyncio
import re
from collections.abc import AsyncIterator

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
async def steam(
    metrics_log: list, monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[DirectSteamSource]:
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    async def _instant_sleep(_: float) -> None:
        pass

    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    client = httpx.AsyncClient()

    def callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
        metrics_log.append((endpoint, region, status_code, latency_ms))

    yield DirectSteamSource(client, on_request=callback)
    await client.aclose()


async def test_on_request_called_on_success(
    steam: DirectSteamSource,
    metrics_log: list,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {}}})

    await steam.get_app_details(440)

    assert len(metrics_log) == 1
    endpoint, region, status, latency = metrics_log[0]
    assert endpoint == "app_details"
    assert region == "us-west-2"
    assert status == 200
    assert latency >= 0


async def test_on_request_called_on_429_retry(
    steam: DirectSteamSource,
    metrics_log: list,
    httpx_mock: HTTPXMock,
) -> None:
    """Callback fires on EVERY attempt including retries."""
    httpx_mock.add_response(url=_APP_DETAILS_RE, status_code=429)
    httpx_mock.add_response(url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {}}})

    await steam.get_app_details(440)

    assert len(metrics_log) == 2
    assert metrics_log[0][2] == 429
    assert metrics_log[1][2] == 200


async def test_on_request_called_on_error(
    steam: DirectSteamSource,
    metrics_log: list,
    httpx_mock: HTTPXMock,
) -> None:
    """Callback fires even when the request ultimately raises."""
    httpx_mock.add_response(url=_APP_DETAILS_RE, status_code=403)

    with pytest.raises(SteamAPIError):
        await steam.get_app_details(440)

    assert len(metrics_log) == 1
    assert metrics_log[0][2] == 403


async def test_on_request_none_default(httpx_mock: HTTPXMock) -> None:
    """No callback (default) doesn't crash."""
    httpx_mock.add_response(url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {}}})

    async with httpx.AsyncClient() as client:
        source = DirectSteamSource(client)
        result = await source.get_app_details(440)
    assert result == {}


async def test_callback_exception_does_not_break_request(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken callback must not prevent the API call from succeeding."""
    httpx_mock.add_response(
        url=_APP_DETAILS_RE, json={"440": {"success": True, "data": {"name": "TF2"}}}
    )

    def bad_callback(endpoint: str, region: str, status_code: int, latency_ms: float) -> None:
        raise RuntimeError("metrics exploded")

    async with httpx.AsyncClient() as client:
        source = DirectSteamSource(client, on_request=bad_callback)
        result = await source.get_app_details(440)
    assert result["name"] == "TF2"
