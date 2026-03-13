"""SteamDataSource abstraction — all Steam data access goes through here."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)

APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
STEAMSPY_URL = "https://steamspy.com/api.php"

_RETRY_STATUSES = frozenset({429, 503})


class SteamAPIError(RuntimeError):
    pass


class SteamDataSource(ABC):
    @abstractmethod
    async def get_app_list(self, limit: int | None = None) -> list[dict]:
        """Returns [{appid, name}] for all Steam apps. Optional limit stops pagination early."""

    @abstractmethod
    async def get_app_details(self, appid: int) -> dict:
        """Returns game metadata from Steam Store API."""

    @abstractmethod
    async def get_reviews(self, appid: int, max_reviews: int = 500) -> list[dict]:
        """Returns reviews with voted_up, review_text, playtime_at_review."""

    @abstractmethod
    async def get_steamspy_data(self, appid: int) -> dict:
        """Returns SteamSpy data: tags, owner estimates."""


class DirectSteamSource(SteamDataSource):
    """Calls Steam Store API and SteamSpy directly using httpx.

    URLs:
    - App list:    GET https://steamspy.com/api.php?request=all&page=N (paginated, 1000/page)
    - App details: GET https://store.steampowered.com/api/appdetails?appids={appid}
    - Reviews:     GET https://store.steampowered.com/appreviews/{appid}?json=1&filter=recent&num_per_page=100
                   Paginate using cursor param until max_reviews reached
    - SteamSpy:    GET https://steamspy.com/api.php?request=appdetails&appid={appid}

    Add jitter (random 0.5-2s sleep) between requests.
    Retry up to 3 times with exponential backoff on 429/503.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def _jitter(self) -> None:
        await asyncio.sleep(random.uniform(0.5, 2.0))

    async def _get_with_retry(self, url: str, **params: object) -> httpx.Response:
        for attempt in range(3):
            try:
                resp = await self._client.get(url, params=params or None)  # type: ignore[arg-type]
                if resp.status_code in _RETRY_STATUSES:
                    wait = 2**attempt
                    logger.warning(
                        "HTTP %s from %s — retrying in %ss (attempt %s/3)",
                        resp.status_code, url, wait, attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in _RETRY_STATUSES or attempt == 2:
                    raise SteamAPIError(
                        f"HTTP {exc.response.status_code} from {url}"
                    ) from exc
                await asyncio.sleep(2**attempt)
        raise SteamAPIError(f"Max retries exceeded for {url}")

    async def get_app_list(self, limit: int | None = None) -> list[dict]:
        """Paginate SteamSpy request=all (1000 apps/page) until empty response.

        SteamSpy returns an empty body (not {}) on the last page, so we guard
        against JSONDecodeError and break on empty content.
        """
        apps: list[dict] = []
        page = 0
        while True:
            await self._jitter()
            resp = await self._get_with_retry(STEAMSPY_URL, request="all", page=str(page))
            if not resp.content.strip():
                break
            try:
                data: dict = resp.json()
            except ValueError:
                break
            if not data:
                break
            for appid_str, info in data.items():
                apps.append({"appid": int(appid_str), "name": info.get("name", "")})
            if limit and len(apps) >= limit:
                break
            page += 1
        return apps

    async def get_app_details(self, appid: int) -> dict:
        await self._jitter()
        resp = await self._get_with_retry(
            APP_DETAILS_URL, appids=str(appid), l="english"
        )
        data = resp.json()
        key = str(appid)
        if key not in data or not data[key].get("success"):
            return {}
        return data[key]["data"]  # type: ignore[no-any-return]

    async def get_reviews(self, appid: int, max_reviews: int = 500) -> list[dict]:
        reviews: list[dict] = []
        cursor = "*"
        url = REVIEWS_URL.format(appid=appid)

        while len(reviews) < max_reviews:
            if cursor != "*":
                await self._jitter()

            resp = await self._get_with_retry(
                url,
                json="1",
                filter="recent",
                language="english",
                num_per_page="100",
                cursor=cursor,
                purchase_type="all",
            )
            data = resp.json()

            if not data.get("success"):
                break

            batch = data.get("reviews", [])
            if not batch:
                break

            for r in batch:
                reviews.append({
                    "review_text": r.get("review", ""),
                    "voted_up": r.get("voted_up", False),
                    "playtime_at_review": r.get("author", {}).get("playtime_at_review", 0),
                    "timestamp_created": r.get("timestamp_created", 0),
                })

            next_cursor = data.get("cursor", "")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        return reviews[:max_reviews]

    async def get_steamspy_data(self, appid: int) -> dict:
        await self._jitter()
        try:
            resp = await self._get_with_retry(
                STEAMSPY_URL, request="appdetails", appid=str(appid)
            )
            return resp.json()  # type: ignore[no-any-return]
        except SteamAPIError:
            logger.warning("SteamSpy data unavailable for appid=%s", appid)
            return {}
