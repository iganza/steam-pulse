"""SteamDataSource abstraction — all Steam data access goes through here."""

import asyncio
import logging
import random
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)

APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"

_RETRY_STATUSES = frozenset({429, 503})


class SteamAPIError(RuntimeError):
    pass


class SteamDataSource(ABC):
    @abstractmethod
    async def get_app_list(self, limit: int | None = None) -> list[dict]:
        """Returns [{appid, name}] for all Steam apps. Optional limit truncates result."""

    @abstractmethod
    async def get_app_details(self, appid: int) -> dict:
        """Returns game metadata from Steam Store API."""

    @abstractmethod
    async def get_reviews(self, appid: int, max_reviews: int | None = None) -> list[dict]:
        """Returns reviews with voted_up, review_text, playtime_at_review."""

    @abstractmethod
    async def get_review_summary(self, appid: int) -> dict:
        """Returns query_summary from Steam reviews API: total_positive, total_negative, total_reviews, review_score_desc."""


class DirectSteamSource(SteamDataSource):
    """Calls Steam Store API directly using httpx.

    URLs:
    - App list:    GET https://api.steampowered.com/ISteamApps/GetAppList/v2/
    - App details: GET https://store.steampowered.com/api/appdetails?appids={appid}
    - Reviews:     GET https://store.steampowered.com/appreviews/{appid}?json=1&filter=recent&num_per_page=100
                   Paginate using cursor param until max_reviews reached
    - Summary:     GET https://store.steampowered.com/appreviews/{appid}?json=1&num_per_page=1
                   Returns query_summary with total review counts

    Add jitter (random 0.5-2s sleep) between requests.
    Retry up to 3 times with exponential backoff on 429/503.
    """

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key

    async def _jitter(self) -> None:
        await asyncio.sleep(random.uniform(1.5, 3.5))

    async def _get_with_retry(self, url: str, **params: object) -> httpx.Response:
        for attempt in range(6):
            try:
                resp = await self._client.get(url, params=params or None)  # type: ignore[arg-type]
                if resp.status_code in _RETRY_STATUSES:
                    wait = min(2**attempt + random.uniform(1, 5), 120)
                    logger.warning(
                        "HTTP %s from %s — retrying in %.0fs (attempt %s/6)",
                        resp.status_code, url, wait, attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in _RETRY_STATUSES or attempt == 5:
                    raise SteamAPIError(
                        f"HTTP {exc.response.status_code} from {url}"
                    ) from exc
                wait = min(2**attempt + random.uniform(1, 5), 120)
                await asyncio.sleep(wait)
        raise SteamAPIError(f"Max retries exceeded for {url}")

    async def get_app_list(self, limit: int | None = None) -> list[dict]:
        """Fetch full Steam app catalog via IStoreService (cursor-paginated, requires API key)."""
        if not self._api_key:
            raise SteamAPIError("STEAM_API_KEY is required for IStoreService/GetAppList/v1/")

        apps: list[dict] = []
        last_appid: int | None = None

        while True:
            params: dict = {"key": self._api_key, "max_results": 50000, "include_games": 1}
            if last_appid is not None:
                params["last_appid"] = last_appid

            await self._jitter()
            resp = await self._get_with_retry(APP_LIST_URL, **params)
            data = resp.json().get("response", {})

            batch = data.get("apps", [])
            apps.extend({"appid": a["appid"], "name": a.get("name", "")} for a in batch)

            if not data.get("have_more_results"):
                break
            last_appid = data.get("last_appid")

            if limit and len(apps) >= limit:
                break

        if limit:
            apps = apps[:limit]
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

    async def get_reviews(self, appid: int, max_reviews: int | None = None) -> list[dict]:
        reviews: list[dict] = []
        cursor = "*"
        url = REVIEWS_URL.format(appid=appid)

        while True:
            if max_reviews is not None and len(reviews) >= max_reviews:
                break
            if cursor != "*":
                await self._jitter()

            resp = await self._get_with_retry(
                url,
                json="1",
                filter="all",
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
                    "language": r.get("language", ""),
                    "author_steamid": r.get("author", {}).get("steamid", ""),
                    "votes_helpful": r.get("votes_up", 0),
                    "votes_funny": r.get("votes_funny", 0),
                    "written_during_early_access": r.get("written_during_early_access", False),
                    "received_for_free": r.get("received_for_free", False),
                })

            next_cursor = data.get("cursor", "")
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        return reviews if max_reviews is None else reviews[:max_reviews]

    async def get_review_summary(self, appid: int) -> dict:
        """Fetch review counts from Steam reviews API query_summary (num_per_page=1).

        Makes two calls: one with language="english" (for eligibility counts) and
        one with language="all" (for display total). Returns the English summary
        dict with an additional ``total_reviews_all`` key.
        """
        url = REVIEWS_URL.format(appid=appid)
        try:
            # English counts — matches what get_reviews actually fetches
            await self._jitter()
            eng_resp = await self._get_with_retry(
                url, json="1", num_per_page="1", language="english", purchase_type="all"
            )
            eng_data = eng_resp.json()
            if not eng_data.get("success"):
                return {}
            eng_summary: dict = eng_data.get("query_summary", {})

            # All-language count — for display ("X total reviews on Steam")
            await self._jitter()
            all_resp = await self._get_with_retry(
                url, json="1", num_per_page="1", language="all", purchase_type="all"
            )
            all_data = all_resp.json()
            all_summary = all_data.get("query_summary", {}) if all_data.get("success") else {}

            total_positive_all = int(all_summary.get("total_positive") or 0)
            total_negative_all = int(all_summary.get("total_negative") or 0)

            result = dict(eng_summary)
            result["total_reviews_all"] = total_positive_all + total_negative_all
            return result
        except SteamAPIError:
            logger.warning("Review summary unavailable for appid=%s", appid)
            return {}
