"""Shared fixtures for smoke tests against live SteamPulse environments."""

import os

import httpx
import pytest

PROD_PATTERNS = ("d1mamturmn55fm.cloudfront.net", "steampulse.io")

DEFAULT_BASE_URL = "https://d1mamturmn55fm.cloudfront.net"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--prod",
        action="store_true",
        default=False,
        help="Allow running smoke tests against production",
    )


def _is_prod(url: str) -> bool:
    return any(p in url for p in PROD_PATTERNS)


@pytest.fixture(scope="session")
def base_url(request: pytest.FixtureRequest) -> str:
    url = os.environ.get("SMOKETEST_BASE_URL", DEFAULT_BASE_URL)
    if url == "":
        pytest.skip("SMOKETEST_BASE_URL is empty — smoke tests opted out")
    if _is_prod(url) and not request.config.getoption("--prod"):
        pytest.skip(
            "Target is production — pass --prod to confirm: "
            "poetry run pytest tests/smoke/ --prod -v"
        )
    return url.rstrip("/")


@pytest.fixture(scope="session")
def api(base_url: str) -> httpx.Client:
    with httpx.Client(base_url=base_url, timeout=30, follow_redirects=False) as client:
        yield client


@pytest.fixture(scope="session")
def well_known_appid() -> int:
    return 1091500  # Cyberpunk 2077
