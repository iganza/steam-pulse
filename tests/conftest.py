"""Shared pytest fixtures and path setup."""

import json
import os
import sys
from pathlib import Path

import pytest

# Expose library_layer and lambda_functions packages to tests
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "library-layer"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "lambda-functions"))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def steam_appdetails_440() -> dict:
    return json.loads((FIXTURES_DIR / "steam_appdetails_440.json").read_text())


@pytest.fixture
def steam_reviews_440() -> dict:
    return json.loads((FIXTURES_DIR / "steam_reviews_440.json").read_text())


@pytest.fixture(autouse=True)
def aws_credentials() -> None:
    """Prevent any real AWS calls during tests."""
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")


@pytest.fixture(autouse=True)
def fast_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch random.uniform to 0 so asyncio.sleep jitter is instant in tests."""
    monkeypatch.setattr("random.uniform", lambda a, b: 0)
