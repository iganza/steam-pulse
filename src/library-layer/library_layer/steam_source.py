"""SteamDataSource abstraction — all Steam data access goes through here."""

import os
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

import httpx
from aws_lambda_powertools import Logger

logger = Logger()

APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
DECK_COMPAT_URL = "https://store.steampowered.com/saleaction/ajaxgetdeckappcompatibilityreport"
STEAMSPY_API_URL = "https://steamspy.com/api.php"

_RETRY_STATUSES = frozenset({429, 503})
_EMPTY_BATCH_RETRIES = 3
_EMPTY_BATCH_BACKOFF = (2.0, 5.0, 10.0)

MetricsCallback = Callable[[str, str, int, float], None]
"""(endpoint, region, status_code, latency_ms) -> None"""


def _endpoint_name(url: str) -> str:
    """Map a Steam API URL to a low-cardinality endpoint name."""
    if "appreviews" in url:
        return "reviews"
    if "appdetails" in url:
        return "app_details"
    if "deckappcompatibility" in url:
        return "deck_compat"
    if "GetAppList" in url:
        return "app_list"
    if "steamspy.com" in url:
        return "steamspy"
    return "unknown"


class SteamAPIError(RuntimeError):
    pass


class SteamDataSource(ABC):
    """All Steam data access goes through this interface.

    Every method raises SteamAPIError on HTTP failure from Steam.
    Callers are responsible for catching and handling errors.
    """

    @abstractmethod
    def get_app_list(self, limit: int | None = None) -> list[dict]:
        """Returns [{appid, name}] for all Steam apps. Optional limit truncates result."""

    @abstractmethod
    def get_app_details(self, appid: int) -> dict:
        """Returns game metadata from Steam Store API, or {} if not found."""

    @abstractmethod
    def get_reviews(
        self,
        appid: int,
        max_reviews: int | None = None,
        start_cursor: str = "*",
    ) -> tuple[list[dict], str | None]:
        """Returns (reviews, next_cursor).

        reviews: list of dicts with voted_up, review_text, playtime_at_review.
        next_cursor: opaque Steam cursor for the next page, or None if exhausted.
        max_reviews caps this single call (not total across batches).
        start_cursor resumes from a previously saved position.
        """

    @abstractmethod
    def get_review_summary(self, appid: int) -> dict:
        """Returns query_summary: total_positive, total_negative, total_reviews, review_score_desc."""

    @abstractmethod
    def get_deck_compatibility(self, appid: int) -> dict:
        """Returns {resolved_category, resolved_items} or {} if unavailable."""

    @abstractmethod
    def get_steamspy_data(self, appid: int) -> dict:
        """Returns full SteamSpy response dict, or {} on error."""


class DirectSteamSource(SteamDataSource):
    """Calls Steam Store API directly using httpx.

    URLs:
    - App list:    GET https://api.steampowered.com/ISteamApps/GetAppList/v2/
    - App details: GET https://store.steampowered.com/api/appdetails?appids={appid}
    - Reviews:     GET https://store.steampowered.com/appreviews/{appid}?json=1&filter=recent&num_per_page=100
                   Paginate using cursor param until max_reviews reached
    - Summary:     GET https://store.steampowered.com/appreviews/{appid}?json=1&num_per_page=1
                   Returns query_summary with total review counts

    Add jitter (random 0.3-1s sleep) between requests.
    Retry up to 5 times with exponential backoff on 429/503.
    """

    def __init__(
        self,
        client: httpx.Client,
        api_key: str | None = None,
        on_request: MetricsCallback | None = None,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._on_request = on_request
        self._region = os.environ.get("AWS_REGION", "local")
        self._jitter_min = float(os.environ.get("STEAM_JITTER_MIN", "0.3"))
        self._jitter_max = float(os.environ.get("STEAM_JITTER_MAX", "1.0"))

    def _jitter(self) -> None:
        time.sleep(random.uniform(self._jitter_min, self._jitter_max))

    def _emit(self, endpoint: str, status_code: int, latency_ms: float) -> None:
        """Fire metrics callback if set — never raises."""
        if self._on_request:
            try:
                self._on_request(endpoint, self._region, status_code, latency_ms)
            except Exception:
                logger.debug("Metrics callback failed", exc_info=True)

    def _get_with_retry(self, url: str, **params: object) -> httpx.Response:
        endpoint = _endpoint_name(url)
        for attempt in range(6):
            t0 = time.monotonic()
            try:
                resp = self._client.get(url, params=params or None)  # type: ignore[arg-type]
                latency_ms = (time.monotonic() - t0) * 1000
                self._emit(endpoint, resp.status_code, latency_ms)
                if resp.status_code in _RETRY_STATUSES:
                    wait = min(2**attempt + random.uniform(1, 5), 120)
                    logger.warning("HTTP retry", extra={
                        "status": resp.status_code,
                        "url": url,
                        "wait_s": round(wait),
                        "attempt": attempt + 1,
                    })
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as exc:
                # Callback already fired above for the response — no duplicate emit.
                if exc.response.status_code not in _RETRY_STATUSES or attempt == 5:
                    raise SteamAPIError(
                        f"HTTP {exc.response.status_code} from {url}"
                    ) from exc
                wait = min(2**attempt + random.uniform(1, 5), 120)
                time.sleep(wait)
            except httpx.RequestError as exc:
                latency_ms = (time.monotonic() - t0) * 1000
                self._emit(endpoint, 0, latency_ms)
                if attempt == 5:
                    raise SteamAPIError(f"Network error fetching {url}: {exc}") from exc
                wait = min(2**attempt + random.uniform(1, 5), 120)
                logger.warning("Network error retry", extra={
                    "url": url,
                    "wait_s": round(wait),
                    "attempt": attempt + 1,
                    "error": str(exc),
                })
                time.sleep(wait)
        raise SteamAPIError(f"Max retries exceeded for {url}")

    def get_app_list(self, limit: int | None = None) -> list[dict]:
        """Fetch full Steam app catalog via IStoreService (cursor-paginated, requires API key)."""
        if not self._api_key:
            raise SteamAPIError("STEAM_API_KEY is required for IStoreService/GetAppList/v1/")

        apps: list[dict] = []
        last_appid: int | None = None

        while True:
            params: dict = {"key": self._api_key, "max_results": 50000, "include_games": 1}
            if last_appid is not None:
                params["last_appid"] = last_appid

            self._jitter()
            resp = self._get_with_retry(APP_LIST_URL, **params)
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

    def get_app_details(self, appid: int) -> dict:
        self._jitter()
        resp = self._get_with_retry(
            APP_DETAILS_URL, appids=str(appid), l="english"
        )
        data = resp.json()
        key = str(appid)
        if key not in data or not data[key].get("success"):
            return {}
        return data[key]["data"]  # type: ignore[no-any-return]

    def get_reviews(
        self,
        appid: int,
        max_reviews: int | None = None,
        start_cursor: str = "*",
    ) -> tuple[list[dict], str | None]:
        reviews: list[dict] = []
        cursor = start_cursor
        url = REVIEWS_URL.format(appid=appid)

        while True:
            if max_reviews is not None and len(reviews) >= max_reviews:
                break
            if cursor != "*":
                self._jitter()

            resp = self._get_with_retry(
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
                return reviews if max_reviews is None else reviews[:max_reviews], None

            batch = data.get("reviews", [])
            if not batch:
                # Steam occasionally returns an empty page for a valid cursor
                # (transient glitch). Retry before declaring exhaustion.
                # Proven: a cursor that returned empty in production returned
                # 100 valid reviews when retried minutes later.
                for attempt, wait in enumerate(_EMPTY_BATCH_BACKOFF, start=1):
                    logger.warning(
                        "Empty batch from Steam — retrying",
                        extra={"attempt": attempt, "wait": wait, "cursor": cursor},
                    )
                    time.sleep(wait)
                    resp = self._get_with_retry(
                        url,
                        json="1",
                        filter="recent",
                        language="english",
                        num_per_page="100",
                        cursor=cursor,
                        purchase_type="all",
                    )
                    data = resp.json()
                    batch = data.get("reviews", [])
                    if batch:
                        break
                if not batch:
                    return reviews if max_reviews is None else reviews[:max_reviews], None

            for r in batch:
                reviews.append({
                    "recommendationid": r.get("recommendationid", ""),
                    "review_text": r.get("review", ""),
                    "voted_up": r.get("voted_up", False),
                    "playtime_at_review": r.get("author", {}).get("playtime_at_review", 0),
                    "timestamp_created": r.get("timestamp_created", 0),
                    "language": r.get("language") or None,
                    "author_steamid": r.get("author", {}).get("steamid") or None,
                    "votes_helpful": r.get("votes_up", 0),
                    "votes_funny": r.get("votes_funny", 0),
                    "written_during_early_access": r.get("written_during_early_access", False),
                    "received_for_free": r.get("received_for_free", False),
                })

            next_cursor = data.get("cursor", "")
            if not next_cursor or next_cursor == cursor:
                # Steam exhausted
                capped = reviews if max_reviews is None else reviews[:max_reviews]
                return capped, None
            cursor = next_cursor

        # Stopped at max_reviews cap — more pages remain
        return reviews[:max_reviews], cursor  # type: ignore[index]

    def get_review_summary(self, appid: int) -> dict:
        """Fetch review counts from Steam reviews API query_summary (num_per_page=1).

        Makes two calls: one with language="english" (for eligibility counts) and
        one with language="all" (for display total). Returns the English summary
        dict with an additional ``total_reviews_all`` key.

        Raises:
            SteamAPIError: on HTTP failure from Steam.
        """
        url = REVIEWS_URL.format(appid=appid)

        # English counts — matches what get_reviews actually fetches
        self._jitter()
        eng_resp = self._get_with_retry(
            url, json="1", num_per_page="1", language="english", purchase_type="all"
        )
        eng_data = eng_resp.json()
        if not eng_data.get("success"):
            return {}
        eng_summary: dict = eng_data.get("query_summary", {})

        # All-language count — for display ("X total reviews on Steam")
        self._jitter()
        all_resp = self._get_with_retry(
            url, json="1", num_per_page="1", language="all", purchase_type="all"
        )
        all_data = all_resp.json()
        all_summary = all_data.get("query_summary", {}) if all_data.get("success") else {}

        total_positive_all = int(all_summary.get("total_positive") or 0)
        total_negative_all = int(all_summary.get("total_negative") or 0)

        result = dict(eng_summary)
        result["total_reviews_all"] = total_positive_all + total_negative_all
        return result

    def get_deck_compatibility(self, appid: int) -> dict:
        """Fetch Steam Deck compatibility report for an app.

        Returns dict with 'resolved_category' (int) and 'resolved_items' (list),
        or empty dict if unavailable.

        Raises:
            SteamAPIError: on HTTP failure from Steam.
        """
        self._jitter()
        resp = self._get_with_retry(DECK_COMPAT_URL, nAppID=str(appid))
        data = resp.json()
        if not data.get("success"):
            return {}
        results = data.get("results", {})
        return {
            "resolved_category": results.get("resolved_category", 0),
            "resolved_items": results.get("resolved_items", []),
        }

    def get_steamspy_data(self, appid: int) -> dict:
        """Fetch full SteamSpy data for a game.

        Returns the raw SteamSpy response dict, or {} on error.
        SteamSpy rate limit: ~4 req/sec. Caller must handle pacing.
        """
        self._jitter()
        try:
            resp = self._get_with_retry(
                STEAMSPY_API_URL,
                request="appdetails",
                appid=str(appid),
            )
            data = resp.json()
            # SteamSpy returns partial data for invalid appids — valid responses have "tags"
            if "tags" not in data:
                return {}
            return data
        except Exception:
            logger.warning("SteamSpy fetch failed", extra={"appid": appid})
            return {}
