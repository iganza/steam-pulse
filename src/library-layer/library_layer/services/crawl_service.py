"""CrawlService — orchestrates Steam API, repositories, and AWS clients."""

from __future__ import annotations

import gzip
import json
import logging
import uuid
from datetime import date, datetime
from typing import Any

from library_layer.config import SteamPulseConfig
from library_layer.events import (
    GameMetadataReadyEvent,
    GamePriceChangedEvent,
    GameReleasedEvent,
    ReviewMilestoneEvent,
    ReviewsReadyEvent,
)
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.steam_source import DirectSteamSource, SteamAPIError
from library_layer.utils.events import EventPublishError, publish_event
from library_layer.utils.slugify import slugify
from library_layer.utils.time import unix_to_datetime

logger = logging.getLogger(__name__)

MAX_REVIEWS_DEFAULT = None  # fetch all reviews
REVIEW_MILESTONES = [500, 1000, 5000, 10000]


def _reanalysis_threshold(total_reviews: int) -> int:
    """New reviews needed since last analysis to trigger re-analysis."""
    if total_reviews < 200:
        return 25
    elif total_reviews < 2_000:
        return 150
    elif total_reviews < 20_000:
        return 500
    elif total_reviews < 200_000:
        return 2_000
    else:
        return 10_000


class CrawlService:
    """Orchestrates app and review crawling: Steam API + repositories + SQS/SFN."""

    def __init__(
        self,
        game_repo: GameRepository,
        review_repo: ReviewRepository,
        catalog_repo: CatalogRepository,
        tag_repo: TagRepository,
        steam: DirectSteamSource,
        sqs_client: Any,
        review_queue_url: str,
        sns_client: Any,
        config: SteamPulseConfig,
        sfn_arn: str | None = None,
        sfn_client: Any | None = None,
        s3_client: Any | None = None,
        archive_bucket: str | None = None,
    ) -> None:
        self._game_repo = game_repo
        self._review_repo = review_repo
        self._catalog_repo = catalog_repo
        self._tag_repo = tag_repo
        self._steam = steam
        self._sqs = sqs_client
        self._review_queue_url = review_queue_url
        self._sfn_arn = sfn_arn
        self._sfn = sfn_client
        self._sns = sns_client
        self._config = config
        self._s3 = s3_client
        self._archive_bucket = archive_bucket

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def crawl_app(self, appid: int, dry_run: bool = False) -> bool:
        """Fetch app details + review summary from Steam. Upsert to DB. Enqueue review crawl if eligible.

        Returns:
            True on success, False on failure (Steam API error or not found).
        """
        try:
            details = await self._steam.get_app_details(appid)
        except SteamAPIError as exc:
            logger.warning("Steam API error for appid=%s: %s", appid, exc)
            self._catalog_repo.set_meta_status(appid, "failed")
            return False

        if not details:
            logger.info("appid=%s not found on Steam — skipping", appid)
            self._catalog_repo.set_meta_status(appid, "skipped")
            return False

        summary = await self._steam.get_review_summary(appid)
        deck_compat = await self._steam.get_deck_compatibility(appid)
        total_positive = int(summary.get("total_positive") or 0)
        total_negative = int(summary.get("total_negative") or 0)
        total_reviews = total_positive + total_negative  # English
        total_reviews_all = int(summary.get("total_reviews_all") or 0) or total_reviews
        positive_pct: int | None = (
            round(total_positive / total_reviews * 100) if total_reviews > 0 else None
        )
        review_score_desc: str = summary.get("review_score_desc", "") or ""

        devs: list[str] = details.get("developers") or []
        pubs: list[str] = details.get("publishers") or []

        release_info = details.get("release_date") or {}
        coming_soon: bool = (
            bool(release_info.get("coming_soon", False))
            if isinstance(release_info, dict)
            else False
        )
        release_date = _parse_release_date(
            release_info.get("date", "") if isinstance(release_info, dict) else ""
        )

        price_info = details.get("price_overview") or {}
        is_free: bool = bool(details.get("is_free", False))
        price_usd: float | None = (
            price_info.get("final", 0) / 100.0 if price_info and not is_free else None
        )

        achievements = details.get("achievements") or {}
        achievements_total = (
            int(achievements.get("total", 0)) if isinstance(achievements, dict) else 0
        )
        metacritic = details.get("metacritic") or {}
        metacritic_score: int | None = (
            metacritic.get("score") if isinstance(metacritic, dict) else None
        )

        name: str = details.get("name") or f"App {appid}"
        slug = slugify(name, appid)

        genres: list[dict] = details.get("genres") or []
        categories: list[dict] = details.get("categories") or []

        logger.info(
            "appid=%s name=%r — genres=%d categories=%d reviews=%d",
            appid,
            name,
            len(genres),
            len(categories),
            total_reviews,
        )

        if dry_run:
            return True

        # Load existing row BEFORE upsert for state comparison (events)
        existing = self._game_repo.find_by_appid(appid)
        old_review_count = existing.review_count if existing else 0

        game_data: dict = {
            "appid": appid,
            "name": name,
            "slug": slug,
            "type": details.get("type") or "game",
            "developer": devs[0] if devs else None,
            "developer_slug": slugify(devs[0]) if devs else None,
            "publisher": pubs[0] if pubs else None,
            "developers": json.dumps(devs),
            "publishers": json.dumps(pubs),
            "website": details.get("website") or None,
            "release_date": release_date,
            "coming_soon": coming_soon,
            "price_usd": price_usd,
            "is_free": is_free,
            "short_desc": (details.get("short_description") or "")[:2000],
            "detailed_description": details.get("detailed_description") or "",
            "about_the_game": details.get("about_the_game") or "",
            "review_count": total_reviews_all,
            "review_count_english": total_reviews,
            "total_positive": total_positive,
            "total_negative": total_negative,
            "positive_pct": positive_pct,
            "review_score_desc": review_score_desc,
            "header_image": details.get("header_image") or "",
            "background_image": details.get("background") or "",
            "required_age": int(details.get("required_age") or 0),
            "platforms": json.dumps(details.get("platforms") or {}),
            "supported_languages": details.get("supported_languages") or "",
            "achievements_total": achievements_total,
            "metacritic_score": metacritic_score,
            "deck_compatibility": deck_compat.get("resolved_category") if deck_compat else None,
            "deck_test_results": json.dumps(deck_compat.get("resolved_items", [])) if deck_compat else None,
            "data_source": "steam_direct",
        }

        self._game_repo.upsert(game_data)

        # Tags (genres + categories combined)
        tag_items = genres + categories
        self._tag_repo.upsert_tags(
            [
                {"appid": appid, "name": item.get("description") or "", "votes": 0}
                for item in tag_items
                if item.get("description")
            ]
        )
        self._tag_repo.upsert_genres(appid, genres)
        self._tag_repo.upsert_categories(appid, categories)

        review_status = "pending" if total_reviews >= 500 else "ineligible"
        self._catalog_repo.set_meta_status(
            appid,
            "done",
            review_count=total_reviews_all,
            review_status=review_status,
        )

        self._archive_to_s3(f"app-details/{appid}/{date.today().isoformat()}.json.gz", details)

        # ── Publish domain events ──────────────────────────────────────────
        self._publish_crawl_app_events(appid, game_data, existing)

        delta = total_reviews_all - old_review_count
        threshold = _reanalysis_threshold(total_reviews_all)
        if delta >= threshold:
            logger.info(
                "appid=%s delta=%d >= threshold=%d — queuing for review crawl",
                appid,
                delta,
                threshold,
            )
            self._enqueue_review_crawl(appid)
        else:
            logger.info(
                "appid=%s delta=%d < threshold=%d — skipping review crawl",
                appid,
                delta,
                threshold,
            )

        return True

    async def crawl_reviews(
        self,
        appid: int,
        dry_run: bool = False,
        max_reviews: int | None = MAX_REVIEWS_DEFAULT,
    ) -> int:
        """Fetch reviews from Steam. Bulk upsert to DB. Trigger Step Functions.

        Returns:
            Number of reviews upserted.
        """
        try:
            raw_reviews = await self._steam.get_reviews(appid, max_reviews=max_reviews)
        except SteamAPIError as exc:
            logger.warning("Steam reviews API error for appid=%s: %s", appid, exc)
            return 0

        if not raw_reviews:
            logger.info("No reviews found for appid=%s", appid)
            return 0

        logger.info("Fetched %d reviews for appid=%s", len(raw_reviews), appid)

        self._archive_to_s3(f"reviews/{appid}/{date.today().isoformat()}.json.gz", raw_reviews)

        if dry_run:
            return len(raw_reviews)

        self._game_repo.ensure_stub(appid)

        game = self._game_repo.find_by_appid(appid)
        game_name: str = game.name if game else f"App {appid}"

        reviews_to_upsert = []
        for r in raw_reviews:
            ts = r.get("timestamp_created")
            steam_id = f"{ts}_{appid}"
            posted_at: datetime | None = None
            if ts:
                try:
                    posted_at = unix_to_datetime(int(ts))
                except (ValueError, OSError):
                    pass
            playtime_minutes = int(r.get("playtime_at_review") or 0)
            reviews_to_upsert.append(
                {
                    "appid": appid,
                    "steam_review_id": steam_id,
                    "author_steamid": r.get("author_steamid", ""),
                    "voted_up": bool(r.get("voted_up", False)),
                    "playtime_hours": playtime_minutes // 60,
                    "body": r.get("review_text", ""),
                    "posted_at": posted_at,
                    "language": r.get("language", ""),
                    "votes_helpful": int(r.get("votes_helpful") or 0),
                    "votes_funny": int(r.get("votes_funny") or 0),
                    "written_during_early_access": bool(r.get("written_during_early_access", False)),
                    "received_for_free": bool(r.get("received_for_free", False)),
                }
            )

        upserted = self._review_repo.bulk_upsert(reviews_to_upsert)
        logger.info("Upserted %d reviews for appid=%s", upserted, appid)

        self._trigger_analysis(appid, game_name)

        # Publish reviews-ready event
        try:
            publish_event(
                self._sns,
                self._config.CONTENT_EVENTS_TOPIC_ARN,
                ReviewsReadyEvent(
                    appid=appid,
                    game_name=game_name,
                    reviews_crawled=upserted,
                ),
            )
        except EventPublishError:
            logger.warning("Failed to publish reviews-ready for appid=%s", appid)

        return upserted

    def _should_enqueue_reviews(self, review_count: int, stored_count: int) -> bool:
        """Return True if delta exceeds the tiered threshold for re-analysis."""
        delta = review_count - stored_count
        return delta >= _reanalysis_threshold(review_count)

    # ------------------------------------------------------------------
    # S3 archival
    # ------------------------------------------------------------------

    def _archive_to_s3(self, key: str, data: dict | list) -> None:
        """Archive raw API response to S3 as gzip'd JSON. Skips silently if unconfigured."""
        if not self._s3 or not self._archive_bucket:
            return
        try:
            compressed = gzip.compress(json.dumps(data).encode())
            self._s3.put_object(
                Bucket=self._archive_bucket,
                Key=key,
                Body=compressed,
                ContentEncoding="gzip",
                ContentType="application/json",
            )
        except Exception:
            logger.warning("Failed to archive %s to S3", key)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _publish_crawl_app_events(
        self,
        appid: int,
        game_data: dict,
        existing: object | None,
    ) -> None:
        """Publish domain events after app metadata upsert."""
        if not self._sns or not self._config:
            return

        topic_arn = self._config.GAME_EVENTS_TOPIC_ARN
        threshold = self._config.REVIEW_ELIGIBILITY_THRESHOLD
        review_count = game_data["review_count"]
        review_count_english = game_data.get("review_count_english", review_count)
        is_eligible = review_count_english >= threshold

        try:
            # Always: metadata-ready
            publish_event(
                self._sns,
                topic_arn,
                GameMetadataReadyEvent(
                    appid=appid,
                    review_count=review_count,
                    is_eligible=is_eligible,
                ),
                extra_attributes={"is_eligible": str(is_eligible).lower()},
            )

            # Detect game release: coming_soon flipped True → False
            if (
                existing
                and getattr(existing, "coming_soon", False)
                and not game_data.get("coming_soon", True)
            ):
                publish_event(
                    self._sns,
                    topic_arn,
                    GameReleasedEvent(
                        appid=appid,
                        game_name=game_data["name"],
                        release_date=str(game_data.get("release_date", "")),
                    ),
                )

            # Detect price change (compare as floats — existing may be Decimal)
            if existing:
                old_price = float(getattr(existing, "price_usd", None) or 0)
                new_price = float(game_data.get("price_usd") or 0)
                if old_price != new_price:
                    publish_event(
                        self._sns,
                        topic_arn,
                        GamePriceChangedEvent(
                            appid=appid,
                            old_price=old_price,
                            new_price=new_price,
                            is_free=game_data.get("is_free", False),
                        ),
                    )

            # Detect review milestones
            old_count = getattr(existing, "review_count", 0) if existing else 0
            for milestone in REVIEW_MILESTONES:
                if old_count < milestone <= review_count:
                    publish_event(
                        self._sns,
                        topic_arn,
                        ReviewMilestoneEvent(
                            appid=appid,
                            milestone=milestone,
                            review_count=review_count,
                        ),
                    )
        except EventPublishError:
            logger.warning("Failed to publish crawl_app events for appid=%s", appid)

    def _enqueue_review_crawl(self, appid: int) -> None:
        if not self._review_queue_url:
            logger.info("No review_queue_url set — skipping enqueue for appid=%s", appid)
            return
        self._sqs.send_message(
            QueueUrl=self._review_queue_url,
            MessageBody=json.dumps({"appid": appid}),
        )
        logger.info("Queued appid=%s to review-crawl-queue", appid)

    def _trigger_analysis(self, appid: int, game_name: str) -> str | None:
        """Start Step Functions execution. Returns execution ARN or None if SFN not configured."""
        if not self._sfn_arn or not self._sfn:
            logger.info(
                "No SFN_ARN configured — skipping Step Functions trigger for appid=%s",
                appid,
            )
            return None
        resp = self._sfn.start_execution(
            stateMachineArn=self._sfn_arn,
            name=f"analysis-{appid}-{uuid.uuid4().hex[:8]}",
            input=json.dumps({"appid": appid, "game_name": game_name}),
        )
        arn: str = resp["executionArn"]
        logger.info("Started Step Functions execution %s for appid=%s", arn, appid)
        return arn


def _parse_release_date(raw: str) -> object | None:
    """Parse a Steam release date string into a date object."""
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%b %Y"):
        try:
            from datetime import datetime as _dt

            return _dt.strptime(raw.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None
