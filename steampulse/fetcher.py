"""Async fetchers for Steam review and app metadata APIs."""

import asyncio
from typing import Optional

import httpx

REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAMSPY_URL = "https://steamspy.com/api.php"

MAX_PAGES = 5
REVIEWS_PER_PAGE = 100
PAGE_DELAY = 1.0  # seconds between pages


async def fetch_reviews(appid: int, max_reviews: Optional[int] = 500) -> list[dict]:
    """
    Fetch reviews from the Steam review API.
    Pass max_reviews=None to fetch all available reviews.
    Paginates using cursor, with 1s delay between pages.
    Returns list of review dicts with: review_text, voted_up, playtime_at_review, timestamp_created.
    """
    reviews: list[dict] = []
    cursor = "*"
    pages_fetched = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
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
                resp = await client.get(
                    REVIEWS_URL.format(appid=appid), params=params
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Steam reviews API returned {e.response.status_code}") from e
            except httpx.RequestError as e:
                raise RuntimeError(f"Steam reviews API unreachable: {e}") from e

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
                        "playtime_at_review": r.get("author", {}).get(
                            "playtime_at_review", 0
                        ),
                        "timestamp_created": r.get("timestamp_created", 0),
                    }
                )

            cursor = data.get("cursor", "")
            pages_fetched += 1

            if max_reviews is not None and len(reviews) >= max_reviews:
                break

            if batch:
                await asyncio.sleep(PAGE_DELAY)

    return reviews if max_reviews is None else reviews[:max_reviews]


async def fetch_app_metadata(appid: int) -> Optional[dict]:
    """
    Fetch Steam app details for a given appid.
    Returns normalized metadata dict or None if not found.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                APPDETAILS_URL,
                params={"appids": str(appid), "l": "english"},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Steam appdetails API returned {e.response.status_code}") from e
        except httpx.RequestError as e:
            raise RuntimeError(f"Steam appdetails API unreachable: {e}") from e

    key = str(appid)
    if key not in data or not data[key].get("success"):
        return None

    d = data[key]["data"]

    price_usd: Optional[float] = None
    if not d.get("is_free") and d.get("price_overview"):
        price_usd = d["price_overview"].get("final", 0) / 100.0

    metacritic_score: Optional[int] = None
    if d.get("metacritic"):
        metacritic_score = d["metacritic"].get("score")

    return {
        "appid": appid,
        "name": d.get("name", ""),
        "type": d.get("type", ""),
        "short_description": d.get("short_description", ""),
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


async def fetch_steamspy(appid: int) -> Optional[dict]:
    """Fetch SteamSpy data for a given appid (V2 crawler use)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                STEAMSPY_URL,
                params={"request": "appdetails", "appid": str(appid)},
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError):
            return None

        
