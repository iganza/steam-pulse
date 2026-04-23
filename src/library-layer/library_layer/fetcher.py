"""Fetchers for Steam review and app metadata APIs."""

import random
import time

import httpx
from aws_lambda_powertools import Logger

logger = Logger()

REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"

REVIEWS_PER_PAGE = 100
PAGE_DELAY_MIN = 0.5  # seconds — randomised between min/max to avoid detection
PAGE_DELAY_MAX = 2.0
METADATA_DELAY_MIN = 0.3
METADATA_DELAY_MAX = 1.2
MAX_RETRIES = 5
BACKOFF_BASE = 2.0  # exponential: 2, 4, 8, 16, 32 seconds


def _jitter(min_s: float, max_s: float) -> float:
    return random.uniform(min_s, max_s)


def _get_with_retry(client: httpx.Client, url: str, params: dict) -> httpx.Response:
    """GET with exponential backoff on 429/503. Raises on permanent failure."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(url, params=params)
        except httpx.RequestError as e:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Steam API unreachable after {MAX_RETRIES} attempts: {e}"
                ) from e
            time.sleep(BACKOFF_BASE**attempt + _jitter(0, 1))
            continue

        if resp.status_code in (429, 503):
            wait = BACKOFF_BASE**attempt + _jitter(1, 3)
            time.sleep(wait)
            continue

        resp.raise_for_status()
        return resp

    raise RuntimeError(f"Steam API rate-limited after {MAX_RETRIES} retries: {url}")


def fetch_reviews(appid: int, max_reviews: int | None = 500) -> list[dict]:
    """
    Fetch reviews from the Steam review API.
    Pass max_reviews=None to fetch all available reviews.
    Paginates using cursor with randomised delay + exponential backoff on 429/503.
    Returns list of review dicts with: review_text, voted_up, playtime_at_review, timestamp_created.
    """
    reviews: list[dict] = []
    cursor = "*"

    with httpx.Client(timeout=30.0) as client:
        while True:
            params = {
                "json": "1",
                "filter": "recent",
                "language": "english",
                "num_per_page": str(REVIEWS_PER_PAGE),
                "cursor": cursor,
                "purchase_type": "all",
            }

            try:
                resp = _get_with_retry(client, REVIEWS_URL.format(appid=appid), params)
                data = resp.json()
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Steam reviews API returned {e.response.status_code}") from e

            if not data.get("success"):
                break

            batch = data.get("reviews", [])
            if not batch:
                break

            for r in batch:
                reviews.append(
                    {
                        "review_text": r.get("review", ""),
                        "voted_up": r.get("voted_up", False),
                        "playtime_at_review": r.get("author", {}).get("playtime_at_review", 0),
                        "timestamp_created": r.get("timestamp_created", 0),
                    }
                )

            cursor = data.get("cursor", "")

            if max_reviews is not None and len(reviews) >= max_reviews:
                break

            if batch:
                time.sleep(_jitter(PAGE_DELAY_MIN, PAGE_DELAY_MAX))

    return reviews if max_reviews is None else reviews[:max_reviews]


def fetch_app_metadata(appid: int) -> dict | None:
    """
    Fetch Steam app details for a given appid.
    Returns normalized metadata dict or None if not found.
    Includes randomised delay to avoid rate limiting during bulk crawls.
    """
    with httpx.Client(timeout=30.0) as client:
        try:
            resp = _get_with_retry(
                client,
                APPDETAILS_URL,
                {"appids": str(appid), "l": "english", "cc": "us"},
            )
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Steam appdetails API returned {e.response.status_code}") from e

    # Polite delay after every metadata fetch — callers may loop over thousands of appids
    time.sleep(_jitter(METADATA_DELAY_MIN, METADATA_DELAY_MAX))

    key = str(appid)
    if key not in data or not data[key].get("success"):
        return None

    d = data[key]["data"]

    price_usd: float | None = None
    price_overview = d.get("price_overview") or {}
    if price_overview and not d.get("is_free"):
        currency = price_overview.get("currency")
        if currency != "USD":
            logger.warning(
                "appdetails returned non-USD price",
                extra={
                    "appid": appid,
                    "currency": currency,
                    "final": price_overview.get("final"),
                },
            )
        else:
            price_usd = price_overview.get("final", 0) / 100.0

    metacritic_score: int | None = None
    if d.get("metacritic"):
        metacritic_score = d["metacritic"].get("score")

    return {
        "appid": appid,
        "name": d.get("name", ""),
        "type": d.get("type", ""),
        "short_description": d.get("short_description", ""),
        "about_the_game": d.get("about_the_game", ""),
        "is_free": d.get("is_free", False),
        "price_usd": price_usd,
        "developers": d.get("developers", []),
        "publishers": d.get("publishers", []),
        "platforms": d.get("platforms", {}),
        "metacritic_score": metacritic_score,
        "genres": [g["description"] for g in d.get("genres", [])],
        "categories": [c["description"] for c in d.get("categories", [])],
        "release_date": d.get("release_date", {}).get("date", ""),
        "header_image": d.get("header_image", ""),
        "total_positive": d.get("recommendations", {}).get("total", 0),
        "review_score_desc": d.get("review_score_desc", ""),
    }
