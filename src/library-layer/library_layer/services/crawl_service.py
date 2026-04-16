"""CrawlService — orchestrates Steam API, repositories, and AWS clients."""

import gzip
import json
import uuid
from datetime import date, datetime
from typing import Any

from aws_lambda_powertools import Logger
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
from library_layer.utils.scores import steam_review_label
from library_layer.utils.slugify import slugify
from library_layer.utils.time import unix_to_datetime

logger = Logger()

MAX_REVIEWS_DEFAULT = None  # fetch all reviews
REVIEW_MILESTONES = [500, 1000, 5000, 10000]


_STEAM_SENTINEL = 4_294_967_295
_INT_MAX = 2_147_483_647


def _safe_votes(val: object) -> int:
    """Map Steam vote counts to safe integers. Sentinel 0xFFFFFFFF and negatives become 0."""
    n = int(val or 0)
    return 0 if n < 0 or n >= _STEAM_SENTINEL else min(n, _INT_MAX)


def _normalize_reviews(appid: int, raw_reviews: list[dict]) -> list[dict]:
    """Transform raw Steam review dicts into the shape expected by ReviewRepository.bulk_upsert()."""
    result = []
    for r in raw_reviews:
        ts = r.get("timestamp_created")
        # Prefer Steam's unique recommendationid; fall back to author+timestamp
        # for legacy data that pre-dates the field being passed through.
        rec_id = r.get("recommendationid")
        if rec_id:
            steam_id = str(rec_id)
        else:
            author = r.get("author_steamid") or ""
            steam_id = f"{author}_{ts}_{appid}"
        posted_at: datetime | None = None
        if ts:
            try:
                posted_at = unix_to_datetime(int(ts))
            except (ValueError, OSError):
                pass
        playtime_minutes = int(r.get("playtime_at_review") or 0)

        result.append(
            {
                "appid": appid,
                "steam_review_id": steam_id,
                "author_steamid": r.get("author_steamid") or None,
                "voted_up": bool(r.get("voted_up", False)),
                "playtime_hours": min(playtime_minutes // 60, _INT_MAX),
                "body": r.get("review_text", ""),
                "posted_at": posted_at,
                "language": r.get("language") or None,
                "votes_helpful": _safe_votes(r.get("votes_helpful")),
                "votes_funny": _safe_votes(r.get("votes_funny")),
                "written_during_early_access": bool(r.get("written_during_early_access", False)),
                "received_for_free": bool(r.get("received_for_free", False)),
            }
        )
    return result


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
        game_events_topic_arn: str,
        content_events_topic_arn: str,
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
        self._game_events_topic_arn = game_events_topic_arn
        self._content_events_topic_arn = content_events_topic_arn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def crawl_app(self, appid: int, dry_run: bool = False) -> bool:
        """Fetch app details + review summary from Steam. Upsert to DB. Enqueue review crawl if eligible.

        Returns:
            True on success, False on failure (Steam API error or not found).
        """
        try:
            details = self._steam.get_app_details(appid)
        except SteamAPIError as exc:
            logger.error("Steam app_details error", extra={"appid": appid, "error": str(exc)})
            self._catalog_repo.set_meta_status(appid, "failed")
            return False

        if not details:
            logger.info("App not found on Steam — skipping", extra={"appid": appid})
            self._catalog_repo.set_meta_status(appid, "skipped")
            return False

        try:
            summary = self._steam.get_review_summary(appid)
        except SteamAPIError as exc:
            logger.error("Steam review_summary error", extra={"appid": appid, "error": str(exc)})
            self._catalog_repo.set_meta_status(appid, "failed")
            return False

        try:
            deck_compat = self._steam.get_deck_compatibility(appid)
        except SteamAPIError as exc:
            logger.warning(
                "Steam deck_compat unavailable", extra={"appid": appid, "error": str(exc)}
            )
            deck_compat = {}

        name: str = details.get("name") or f"App {appid}"
        logger.info("App fetched", extra={"appid": appid, "game_name": name})

        if dry_run:
            return True

        # Load existing row BEFORE upsert for state comparison (events)
        existing = self._game_repo.find_by_appid(appid)

        game_data = self._ingest_app_data(appid, details, summary, deck_compat)
        if not game_data:
            return False

        # ── Publish domain events (only in direct crawl path) ─────────────
        self._publish_crawl_app_events(appid, game_data, existing)

        return True

    def crawl_reviews(
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
            raw_reviews, _ = self._steam.get_reviews(appid, max_reviews=max_reviews)
        except SteamAPIError as exc:
            logger.warning("Steam reviews API error", extra={"appid": appid, "error": str(exc)})
            return 0

        if not raw_reviews:
            logger.info("No reviews found", extra={"appid": appid})
            return 0

        logger.info("Reviews fetched", extra={"appid": appid, "count": len(raw_reviews)})

        self._archive_to_s3(f"reviews/{appid}/{date.today().isoformat()}.json.gz", raw_reviews)

        if dry_run:
            return len(raw_reviews)

        game = self._game_repo.find_by_appid(appid)
        game_name: str = game.name if game else f"App {appid}"

        reviews_to_upsert = _normalize_reviews(appid, raw_reviews)
        upserted = self._review_repo.bulk_upsert(reviews_to_upsert)
        logger.info("Reviews upserted", extra={"appid": appid, "upserted": upserted})

        has_ea_review = any(r.get("written_during_early_access") for r in reviews_to_upsert)
        if has_ea_review and not getattr(game, "has_early_access_reviews", False):
            self._game_repo.set_has_early_access_reviews(appid)

        self._refresh_post_release_metrics(appid)

        self._trigger_analysis(appid, game_name)

        # Publish reviews-ready event
        try:
            publish_event(
                self._sns,
                self._content_events_topic_arn,
                ReviewsReadyEvent(
                    appid=appid,
                    game_name=game_name,
                    reviews_crawled=upserted,
                ),
            )
        except EventPublishError:
            logger.warning("Failed to publish reviews-ready", extra={"appid": appid})

        return upserted

    def ingest_spoke_metadata(self, appid: int, raw: dict) -> bool:
        """Ingest metadata fetched by a spoke Lambda.

        Writes app data to DB and publishes the same domain events as crawl_app.

        Args:
            appid: Steam app ID
            raw: dict with keys "details", "summary", "deck_compat"

        Returns:
            True on success, False if details are empty.
        """
        details: dict = raw.get("details") or {}
        summary: dict = raw.get("summary") or {}
        deck_compat: dict | None = raw.get("deck_compat")

        if not details:
            logger.warning("ingest_spoke_metadata: empty details", extra={"appid": appid})
            return False

        existing = self._game_repo.find_by_appid(appid)

        game_data = self._ingest_app_data(appid, details, summary, deck_compat)
        if not game_data:
            return False

        self._publish_crawl_app_events(appid, game_data, existing)

        return True

    def ingest_spoke_reviews(self, appid: int, raw_reviews: list[dict]) -> int:
        """Ingest reviews fetched by a spoke Lambda.

        DB write only — no SNS events, no Step Functions trigger.

        Returns:
            Number of reviews upserted.
        """
        if not raw_reviews:
            return 0

        reviews_to_upsert = _normalize_reviews(appid, raw_reviews)
        upserted = self._review_repo.bulk_upsert(reviews_to_upsert)
        logger.info("Spoke reviews ingested", extra={"appid": appid, "upserted": upserted})

        if any(r.get("written_during_early_access") for r in reviews_to_upsert):
            self._game_repo.set_has_early_access_reviews(appid)

        self._refresh_post_release_metrics(appid)

        return upserted

    def _refresh_post_release_metrics(self, appid: int) -> None:
        """Recompute and denormalize English-only post-release aggregates onto games.

        Called from both the direct crawl (`crawl_reviews`) and spoke ingest
        (`ingest_spoke_reviews`) paths. Idempotent; safe to call per batch.

        The pct comes straight from ``aggregate_post_release`` which computes it
        in SQL (ROUND half-away-from-zero) so ingest-path labels stay identical
        to migration 0048's bulk backfill — Python ``round()`` would use
        banker's rounding and drift on .5 boundaries.
        """
        post_count, post_positive, post_pct = self._review_repo.aggregate_post_release(appid)
        post_label = steam_review_label(post_pct, post_count)
        self._game_repo.update_post_release_metrics(
            appid, post_count, post_positive, post_pct, post_label
        )

    # ------------------------------------------------------------------
    # DB ingest (shared by crawl_app and spoke ingest)
    # ------------------------------------------------------------------

    def _ingest_app_data(
        self,
        appid: int,
        details: dict,
        summary: dict,
        deck_compat: dict | None,
    ) -> dict | None:
        """Write pre-fetched Steam app data to DB.

        Called by crawl_app() and ingest_spoke_metadata().
        Pure DB write: game upsert, tags, catalog status, S3 archive.
        Does NOT publish SNS events or trigger Step Functions.

        Returns:
            The game_data dict on success, None on failure.
        """
        total_positive = int(summary.get("total_positive") or 0)
        total_negative = int(summary.get("total_negative") or 0)
        total_reviews = total_positive + total_negative
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
        release_date_raw = release_info.get("date", "") if isinstance(release_info, dict) else ""
        release_date = _parse_release_date(release_date_raw)

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

        content_desc = details.get("content_descriptors") or {}
        support = details.get("support_info") or {}
        fullgame = details.get("fullgame") or {}
        recs = details.get("recommendations") or {}

        game_data: dict = {
            "appid": appid,
            "name": name,
            "slug": slug,
            "type": details.get("type") or "game",
            "developer": devs[0] if devs else None,
            "developer_slug": slugify(devs[0]) if devs else None,
            "publisher": pubs[0] if pubs else None,
            "publisher_slug": slugify(pubs[0]) if pubs else None,
            "developers": json.dumps(devs),
            "publishers": json.dumps(pubs),
            "website": details.get("website") or None,
            "release_date": release_date,
            "release_date_raw": release_date_raw or None,
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
            "required_age": int(str(details.get("required_age") or 0).rstrip("+")),
            "platforms": json.dumps(details.get("platforms") or {}),
            "supported_languages": details.get("supported_languages") or "",
            "achievements_total": achievements_total,
            "metacritic_score": metacritic_score,
            "deck_compatibility": deck_compat.get("resolved_category") if deck_compat else None,
            "deck_test_results": json.dumps(deck_compat.get("resolved_items", []))
            if deck_compat
            else None,
            "content_descriptor_ids": json.dumps(content_desc.get("ids", []))
            if content_desc.get("ids")
            else None,
            "content_descriptor_notes": content_desc.get("notes") or None,
            "controller_support": details.get("controller_support") or None,
            "dlc_appids": json.dumps(details.get("dlc", [])) if details.get("dlc") else None,
            "parent_appid": int(fullgame["appid"]) if fullgame.get("appid") else None,
            "capsule_image": details.get("capsule_imagev5") or None,
            "recommendations_total": recs.get("total") if recs else None,
            "support_url": support.get("url") or None,
            "support_email": support.get("email") or None,
            "legal_notice": details.get("legal_notice") or None,
            "requirements_windows": _req_text(details.get("pc_requirements")),
            "requirements_mac": _req_text(details.get("mac_requirements")),
            "requirements_linux": _req_text(details.get("linux_requirements")),
            "data_source": "steam_direct",
        }

        self._game_repo.upsert(game_data)

        self._tag_repo.upsert_genres(appid, genres)
        self._tag_repo.upsert_categories(appid, categories)

        self._catalog_repo.set_meta_status(
            appid,
            "done",
            review_count=total_reviews_all,
        )

        self._archive_to_s3(f"app-details/{appid}/{date.today().isoformat()}.json.gz", details)

        return game_data

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
        except Exception as exc:
            logger.warning("Failed to archive to S3", extra={"key": key, "error": str(exc)})

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

        topic_arn = self._game_events_topic_arn
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
            logger.warning("Failed to publish crawl_app events", extra={"appid": appid})

    def _trigger_analysis(self, appid: int, game_name: str) -> str | None:
        """Start Step Functions execution. Returns execution ARN or None if SFN not configured."""
        if not self._sfn_arn or not self._sfn:
            logger.info("No SFN_ARN configured — skipping trigger", extra={"appid": appid})
            return None
        resp = self._sfn.start_execution(
            stateMachineArn=self._sfn_arn,
            name=f"analysis-{appid}-{uuid.uuid4().hex[:8]}",
            input=json.dumps({"appid": appid, "game_name": game_name}),
        )
        arn: str = resp["executionArn"]
        logger.info(
            "Step Functions execution started", extra={"appid": appid, "execution_arn": arn}
        )
        return arn


def _parse_release_date(raw: str) -> date | None:
    """Parse a Steam release date string into a date object."""
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%b %Y"):
        try:
            from datetime import datetime as _dt

            return _dt.strptime(raw.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _req_text(req: object) -> str | None:
    """Extract system requirements text from a Steam appdetails requirements field.

    Steam returns either a dict with "minimum" and/or "recommended" keys (HTML strings),
    or an empty string / empty list for games without requirements.
    """
    if not isinstance(req, dict):
        return None
    parts = [req.get("minimum", ""), req.get("recommended", "")]
    joined = "\n".join(p for p in parts if p)
    return joined or None
