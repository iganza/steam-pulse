"""FastAPI application — JSON API only, no HTML rendering."""

import os
from datetime import UTC, datetime
from typing import Annotated, Literal

import boto3  # type: ignore[import-untyped]
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.parameters import get_parameter
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from library_layer.config import SteamPulseConfig
from library_layer.events import WaitlistConfirmationMessage
from library_layer.models.temporal import build_temporal_context
from library_layer.repositories.analysis_request_repo import AnalysisRequestRepository
from library_layer.repositories.analytics_repo import AnalyticsRepository
from library_layer.repositories.catalog_report_repo import CatalogReportRepository
from library_layer.repositories.game_repo import EARLY_ACCESS_GENRE_ID, GameRepository
from library_layer.repositories.genre_synthesis_repo import GenreSynthesisRepository
from library_layer.repositories.matview_repo import MatviewRepository
from library_layer.repositories.new_releases_repo import NewReleasesRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.repositories.waitlist_repo import WaitlistRepository
from library_layer.repositories.waitlist_suggestion_repo import WaitlistSuggestionRepository
from library_layer.services.analytics_service import AnalyticsService
from library_layer.services.catalog_report_service import CatalogReportService
from library_layer.services.new_releases_service import NewReleasesService
from library_layer.services.new_releases_service import Window as NewReleasesWindow
from library_layer.utils.db import get_conn
from pydantic import BaseModel, EmailStr, Field

logger = Logger(service="api")

app = FastAPI(title="SteamPulse", version="0.1.0")

# Config + SSM resolution at cold start.
# On Lambda: SteamPulseConfig reads env vars set by CDK via to_lambda_env().
# Locally: falls back to DATABASE_URL (no SSM).
_is_lambda = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

if _is_lambda:
    _api_config = SteamPulseConfig()
    _email_queue_url: str | None = get_parameter(_api_config.EMAIL_QUEUE_PARAM_NAME)
else:
    _api_config = None  # type: ignore[assignment]
    _email_queue_url = os.getenv("EMAIL_QUEUE_URL")

_sqs_client = boto3.client("sqs")

VERSION = "0.1.0"

# Edge-cache header for the four SSR-fanout endpoints feeding /games/{appid}/{slug}.
# 7d s-maxage is safe: revalidate_frontend issues a CloudFront invalidation
# covering all four /api/games/{appid}/* paths whenever an analysis completes.
# SWR=30d so a cache expiry never blocks a visitor on a Lambda cold start.
_GAME_PAGE_CACHE_CONTROL = "s-maxage=604800, stale-while-revalidate=2592000"

# ---------------------------------------------------------------------------
# Repository wiring — built once at module level.
# DB connection is lazy (established on first query, reconnects if stale).
# ---------------------------------------------------------------------------

_analytics_repo = AnalyticsRepository(get_conn)
_game_repo = GameRepository(get_conn)
_report_repo = ReportRepository(get_conn)
_review_repo = ReviewRepository(get_conn)
_tag_repo = TagRepository(get_conn)
_waitlist_repo = WaitlistRepository(get_conn)
_waitlist_suggestion_repo = WaitlistSuggestionRepository(get_conn)
_matview_repo = MatviewRepository(get_conn)
_new_releases_repo = NewReleasesRepository(get_conn)
_new_releases_service = NewReleasesService(_new_releases_repo)
_analytics_service = AnalyticsService(_analytics_repo)
_catalog_report_repo = CatalogReportRepository(get_conn)
_analysis_request_repo = AnalysisRequestRepository(get_conn)
_catalog_report_service = CatalogReportService(_catalog_report_repo, _analysis_request_repo)
_genre_synthesis_repo = GenreSynthesisRepository(get_conn)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WaitlistRequest(BaseModel):
    email: EmailStr


class WaitlistSuggestionRequest(BaseModel):
    email: EmailStr
    suggestion: str = Field(min_length=1, max_length=2000)


class AnalysisRequestBody(BaseModel):
    appid: int
    email: EmailStr


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_report(appid: int) -> dict | None:
    result = _report_repo.find_by_appid(appid)
    return result.report_json if result else None


def _backend_name() -> str:
    return "postgres" if os.getenv("DATABASE_URL") else "memory"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "storage": _backend_name(),
        "version": VERSION,
    }


_COMPACT_GAME_FIELDS = (
    "appid",
    "name",
    "slug",
    "header_image",
    "review_count",
    "positive_pct",
    "review_score_desc",
)


@app.get("/api/games")
async def list_games(
    response: Response,
    q: str | None = None,
    genre: str | None = None,
    tag: str | None = None,
    developer: str | None = None,
    publisher: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    min_reviews: int | None = None,
    has_analysis: bool | None = None,
    sentiment: str | None = None,
    price_tier: str | None = None,
    deck: str | None = None,
    sort: str = "review_count",
    limit: int = Query(default=24, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    fields: Literal["compact"] | None = None,
) -> dict:
    result = _game_repo.list_games(
        q=q,
        genre=genre,
        tag=tag,
        developer=developer,
        publisher=publisher,
        year_from=year_from,
        year_to=year_to,
        min_reviews=min_reviews,
        has_analysis=has_analysis if has_analysis else None,
        sentiment=sentiment if sentiment else None,
        price_tier=price_tier if price_tier else None,
        deck_status=deck if deck else None,
        sort=sort,
        limit=limit,
        offset=offset,
    )

    # Resolve total from pre-computed matviews or estimates — never scan.
    games = result["games"]
    has_extra = (
        q is not None
        or developer is not None
        or publisher is not None
        or year_from is not None
        or year_to is not None
        or min_reviews is not None
        or has_analysis is True
        or bool(sentiment)
        or bool(price_tier)
        or bool(deck)
        # Leaderboard sorts apply implicit WHERE filters (e.g. last_analyzed
        # IS NOT NULL); the catalog-wide matview count would overstate the
        # filtered population.
        or sort in GameRepository.SORTS_WITH_IMPLIED_FILTERS
    )

    total: int | None
    if genre and not tag and not has_extra:
        total = _matview_repo.get_genre_count(genre) or 0
    elif tag and not genre and not has_extra:
        total = _matview_repo.get_tag_count(tag) or 0
    elif not genre and not tag and not has_extra:
        total = _matview_repo.get_total_games_count()
    else:
        # Complex filters — exact total unknown without an expensive scan.
        total = None

    has_more = (offset + len(games) < total) if total is not None else len(games) == limit

    if fields == "compact":
        games = [{k: g.get(k) for k in _COMPACT_GAME_FIELDS} for g in games]

    response.headers["Cache-Control"] = "private, max-age=300"
    return {"total": total, "has_more": has_more, "games": games}


@app.get("/api/games/basics")
async def get_games_basics(appids: str) -> JSONResponse:
    """Lightweight crosslink lookup — returns [{appid, name, slug, header_image}, ...]
    for a comma-separated list of appids.

    Purpose: the genre synthesis page (/genre/[slug]/) renders up to ~11
    crosslinks per SSR — benchmark cards, friction-quote source-game links,
    wishlist-quote source-game links. Hitting /api/games/{appid}/report
    for each would pull the full report JSON per game; this endpoint is
    a single DB round-trip for the four fields actually rendered.

    Order is preserved from the input list; unknown appids are silently
    omitted rather than 404-ing the whole batch. Hard-capped at 50 to
    prevent accidental large fan-outs.
    """
    # Parse + dedupe while preserving first-seen order. Cap the raw input
    # generously to guard the parser, then cap the deduped list to the real
    # DB-fanout limit — so appids=1,1,1,... (many duplicates) doesn't 400
    # when the actual lookup is a single row.
    RAW_LIMIT = 500
    UNIQUE_LIMIT = 50
    if len(appids) > RAW_LIMIT * 10:  # rough byte guard before the split
        raise HTTPException(
            status_code=400,
            detail={"error": "query_too_long"},
        )
    parsed: list[int] = []
    for part in appids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            parsed.append(int(part))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "invalid_appid", "value": part},
            )
    seen: set[int] = set()
    unique: list[int] = []
    for a in parsed:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    if len(unique) > UNIQUE_LIMIT:
        raise HTTPException(
            status_code=400,
            detail={"error": "too_many_appids", "limit": UNIQUE_LIMIT, "given": len(unique)},
        )
    basics = _game_repo.find_basics_by_appids(unique)
    return JSONResponse(
        content={"games": basics},
        headers={"Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400"},
    )


@app.get("/api/games/{appid}/report")
async def get_game_report(appid: int) -> JSONResponse:
    """Return the full report JSON if it exists, or a status object.
    Always includes game metadata (short_desc, developer, etc.) alongside the report.
    """
    logger.append_keys(appid=appid)
    game = _game_repo.find_by_appid(appid)
    game_meta: dict = {}
    if game:
        genre_rows = _tag_repo.find_genres_for_game(appid)
        genres = [g["name"] for g in genre_rows]
        tags = [t["name"] for t in _tag_repo.find_tags_for_game(appid)]
        game_meta = {
            "name": game.name,
            "slug": game.slug,
            "header_image": game.header_image,
            "short_desc": game.short_desc,
            "developer": game.developer,
            "developer_slug": game.developer_slug,
            "publisher": game.publisher,
            "publisher_slug": game.publisher_slug,
            "release_date": game.release_date,
            "coming_soon": game.coming_soon,
            "price_usd": float(game.price_usd) if game.price_usd else None,
            "is_free": game.is_free,
            "is_early_access": any(g["id"] == EARLY_ACCESS_GENRE_ID for g in genre_rows),
            "genres": genres,
            "tags": tags,
            "deck_compatibility": game.deck_compatibility,
            "deck_test_results": game.deck_test_results,
            # Steam-sourced sentiment numbers. review_count_english is
            # English-aligned and stays consistent with positive_pct /
            # review_score_desc; review_count is all-language.
            "positive_pct": float(game.positive_pct) if game.positive_pct is not None else None,
            "review_score_desc": game.review_score_desc,
            "review_count": game.review_count,
            "review_count_english": game.review_count_english,
            # Per-source freshness — UI renders these in the Steam Facts zone
            "meta_crawled_at": game.meta_crawled_at.isoformat() if game.meta_crawled_at else None,
            "review_crawled_at": game.review_crawled_at.isoformat()
            if game.review_crawled_at
            else None,
            "reviews_completed_at": game.reviews_completed_at.isoformat()
            if game.reviews_completed_at
            else None,
            "tags_crawled_at": game.tags_crawled_at.isoformat() if game.tags_crawled_at else None,
            "last_analyzed": game.last_analyzed.isoformat() if game.last_analyzed else None,
        }
        # Boxleiter v1 revenue estimate — omit keys when unset.
        # Backend returns unconditionally; Pro-gating is frontend-only.
        # method is only surfaced alongside actual estimate values so clients
        # can treat "method present" as "estimate available".
        has_revenue_estimate = False
        if game.estimated_owners is not None:
            game_meta["estimated_owners"] = game.estimated_owners
            has_revenue_estimate = True
        if game.estimated_revenue_usd is not None:
            game_meta["estimated_revenue_usd"] = float(game.estimated_revenue_usd)
            has_revenue_estimate = True
        if has_revenue_estimate and game.revenue_estimate_method is not None:
            game_meta["revenue_estimate_method"] = game.revenue_estimate_method
        # Reason code is surfaced independently of the numeric estimate so the
        # frontend empty-state can render precise, reason-specific copy
        # (e.g. "Free-to-play — revenue estimates don't apply").
        if game.revenue_estimate_reason is not None:
            game_meta["revenue_estimate_reason"] = game.revenue_estimate_reason

    report = _get_report(appid)
    if report:
        temporal_dict = None
        if game:
            velocity_data = _review_repo.find_review_velocity(appid)
            ea_data = _review_repo.find_early_access_impact(appid)
            temporal = build_temporal_context(game, velocity_data, ea_data)
            # mode="json" — JSONResponse bypasses jsonable_encoder, so dates need stringifying.
            temporal_dict = temporal.model_dump(mode="json")
        body = {
            "status": "available",
            "report": report,
            "game": game_meta,
            "temporal": temporal_dict,
        }
    else:
        body = {
            "status": "not_available",
            "game": game_meta,
        }
    return JSONResponse(
        content=body,
        headers={"Cache-Control": _GAME_PAGE_CACHE_CONTROL},
    )


@app.get("/api/games/{appid}/review-stats")
async def get_review_stats(appid: int) -> JSONResponse:
    """Weekly sentiment timeline + playtime buckets + velocity for a game."""
    logger.append_keys(appid=appid)
    return JSONResponse(
        content=_review_repo.find_review_stats(appid),
        headers={"Cache-Control": _GAME_PAGE_CACHE_CONTROL},
    )


@app.get("/api/games/{appid}/benchmarks")
async def get_benchmarks(appid: int) -> JSONResponse:
    """Percentile ranking vs. genre+year+price cohort (Pro context)."""
    logger.append_keys(appid=appid)
    game = _game_repo.find_by_appid(appid)
    if not game:
        raise HTTPException(
            status_code=404, detail={"error": "Game not found", "code": "not_found"}
        )

    genres = [g["name"] for g in _tag_repo.find_genres_for_game(appid)]
    release_date = game.release_date
    if not genres or not release_date:
        body: dict = {"sentiment_rank": None, "popularity_rank": None, "cohort_size": 0}
    else:
        year = int(str(release_date)[:4])
        body = _game_repo.find_benchmarks(
            appid=appid,
            genre=genres[0],
            year=year,
            price=float(game.price_usd) if game.price_usd else None,
            is_free=game.is_free or False,
        )
    return JSONResponse(
        content=body,
        headers={"Cache-Control": _GAME_PAGE_CACHE_CONTROL},
    )


@app.get("/api/genres")
async def list_genres() -> list[dict]:
    return _matview_repo.list_genre_counts()


@app.get("/api/tags/{slug}/insights")
async def get_tag_insights(slug: str) -> JSONResponse:
    """Phase-4 cross-tag synthesis for `slug`. Refreshed weekly.

    Path uses `tags` — the synthesizer joins `tags`/`game_tags` (not the
    separate `genres`/`game_genres` tables). The persisted table is
    `mv_genre_synthesis` for historical/marketing reasons, but the
    identifier space is tags.slug.
    """
    logger.append_keys(slug=slug)
    row = _genre_synthesis_repo.get_by_slug(slug)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "no_synthesis", "code": "not_found", "slug": slug},
        )
    return JSONResponse(
        content=row.model_dump(mode="json"),
        headers={"Cache-Control": "public, s-maxage=3600, stale-while-revalidate=86400"},
    )


@app.get("/api/tags/top")
async def list_top_tags(limit: int = 24) -> list[dict]:
    limit = min(limit, 100)
    return _matview_repo.list_tag_counts(limit=limit)


@app.get("/api/tags/grouped")
async def list_tags_grouped(
    limit_per_category: int = Query(default=20, ge=1, le=200),
) -> list[dict]:
    return _matview_repo.list_tags_grouped(limit_per_category=limit_per_category)


@app.get("/api/games/{appid}/audience-overlap")
async def get_audience_overlap(appid: int, limit: int = 20) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(
            status_code=404, detail={"error": "game_not_found", "code": "not_found"}
        )
    return _matview_repo.get_audience_overlap(appid, limit=max(1, min(limit, 50)))


@app.get("/api/games/{appid}/playtime-sentiment")
async def get_playtime_sentiment(appid: int) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(
            status_code=404, detail={"error": "game_not_found", "code": "not_found"}
        )
    return _review_repo.find_playtime_sentiment(appid)


@app.get("/api/games/{appid}/early-access-impact")
async def get_early_access_impact(appid: int) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(
            status_code=404, detail={"error": "game_not_found", "code": "not_found"}
        )
    return _review_repo.find_early_access_impact(appid)


@app.get("/api/games/{appid}/review-velocity")
async def get_review_velocity(appid: int) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(
            status_code=404, detail={"error": "game_not_found", "code": "not_found"}
        )
    return _review_repo.find_review_velocity(appid)


@app.get("/api/games/{appid}/related-analyzed")
async def get_related_analyzed(appid: int, limit: int = 6) -> JSONResponse:
    """Analyzed games most similar to the target by tag overlap.

    Falls back to recent public reports when tag overlap yields fewer than 3
    matches — including when the target game row is missing entirely. The
    un-analyzed page still renders a slug-derived fallback for unknown appids
    and benefits from having on-site cross-links, so a 404 here would just
    produce a dead-end for SEO visitors.
    """
    logger.append_keys(appid=appid)
    rows = _report_repo.find_related_analyzed(appid, limit=max(1, min(limit, 12)))
    body = {
        "games": [
            {
                "appid": int(row["appid"]),
                "slug": row["slug"],
                "name": row["name"],
                "header_image": row.get("header_image") or "",
                "positive_pct": int(row["positive_pct"])
                if row.get("positive_pct") is not None
                else None,
                "one_liner": row.get("one_liner") or "",
            }
            for row in rows
        ],
    }
    return JSONResponse(
        content=body,
        headers={"Cache-Control": _GAME_PAGE_CACHE_CONTROL},
    )


@app.get("/api/games/{appid}/top-reviews")
async def get_top_reviews(appid: int, sort: str = "helpful", limit: int = 10) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(
            status_code=404, detail={"error": "game_not_found", "code": "not_found"}
        )
    if sort not in ("helpful", "funny"):
        sort = "helpful"
    return {
        "sort": sort,
        "reviews": _review_repo.find_top_reviews(appid, sort, max(1, min(limit, 50))),
    }


@app.get("/api/analytics/price-positioning")
async def get_price_positioning(genre: str) -> dict:
    return _analytics_repo.find_price_positioning(genre)


@app.get("/api/analytics/release-timing")
async def get_release_timing(genre: str) -> dict:
    return _analytics_repo.find_release_timing(genre)


@app.get("/api/analytics/platform-gaps")
async def get_platform_gaps(genre: str) -> dict:
    return _analytics_repo.find_platform_distribution(genre)


@app.get("/api/tags/{slug}/trend")
async def get_tag_trend(slug: str) -> dict:
    return _analytics_repo.find_tag_trend(slug)


@app.get("/api/developers/{slug}/analytics")
async def get_developer_analytics(slug: str) -> dict:
    return _analytics_repo.find_developer_portfolio(slug)


@app.get("/api/publishers/{slug}/analytics")
async def get_publisher_analytics(slug: str) -> dict:
    return _analytics_repo.find_publisher_portfolio(slug)


# ---------------------------------------------------------------------------
# Analytics trends — catalog-wide time-series (analytics dashboard)
# ---------------------------------------------------------------------------


@app.get("/api/analytics/trends/release-volume")
async def get_trend_release_volume(
    granularity: str = "month",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_release_volume(
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/sentiment")
async def get_trend_sentiment(
    granularity: str = "month",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_sentiment_distribution(
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/genre-share")
async def get_trend_genre_share(
    granularity: str = "year",
    top_n: int = 5,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_genre_share(
            granularity=granularity,
            top_n=max(1, min(top_n, 15)),
            game_type=game_type,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/velocity")
async def get_trend_velocity(
    granularity: str = "month",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_velocity_distribution(
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/pricing")
async def get_trend_pricing(
    granularity: str = "year",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_price_trend(
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/early-access")
async def get_trend_early_access(
    granularity: str = "year",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_ea_trend(
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/platforms")
async def get_trend_platforms(
    granularity: str = "year",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_platform_trend(
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/engagement")
async def get_trend_engagement(
    granularity: str = "year",
    genre: str | None = None,
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_engagement_depth(
            granularity=granularity,
            genre_slug=genre,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/trends/categories")
async def get_trend_categories(
    granularity: str = "year",
    top_n: int = 4,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 100,
) -> dict:
    try:
        return _analytics_service.get_category_trend(
            granularity=granularity,
            top_n=max(1, min(top_n, 8)),
            game_type=game_type,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@app.get("/api/analytics/metrics")
async def get_analytics_metrics() -> dict:
    """Return the metric catalog powering the Builder lens picker."""
    return {"metrics": _analytics_service.list_metrics()}


@app.get("/api/analytics/trend-query")
async def get_analytics_trend_query(
    metrics: str,
    granularity: str = "month",
    genre: str | None = None,
    tag: str | None = None,
    game_type: Annotated[str, Query(alias="type")] = "game",
    limit: int = 24,
) -> dict:
    """Generic trend query — pick any combination of metrics from the catalog."""
    # De-duplicate while preserving order so `metrics=releases,releases`
    # doesn't double-count toward the 6-metric cap or duplicate entries in
    # the returned metric metadata.
    seen: set[str] = set()
    metric_ids: list[str] = []
    for m in metrics.split(","):
        cleaned = m.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        metric_ids.append(cleaned)
    try:
        return _analytics_service.trend_query(
            metric_ids=metric_ids,
            granularity=granularity,
            game_type=game_type,
            genre_slug=genre,
            tag_slug=tag,
            limit=max(1, min(limit, 200)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


_NEW_RELEASES_CACHE = "public, s-maxage=300, stale-while-revalidate=600"


@app.get("/api/new-releases/released")
async def new_releases_released(
    window: NewReleasesWindow = "week",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = None,
    tag: str | None = None,
) -> JSONResponse:
    # `window` is the service's Literal — FastAPI validates against the allowed
    # values and emits a 422 for anything else, so no manual membership check.
    data = _new_releases_service.get_released(
        window,
        page,
        page_size,
        genre=genre,
        tag=tag,
    )
    return JSONResponse(content=data, headers={"Cache-Control": _NEW_RELEASES_CACHE})


@app.get("/api/new-releases/upcoming")
async def new_releases_upcoming(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = None,
    tag: str | None = None,
) -> JSONResponse:
    data = _new_releases_service.get_upcoming(page, page_size, genre=genre, tag=tag)
    return JSONResponse(content=data, headers={"Cache-Control": _NEW_RELEASES_CACHE})


@app.get("/api/new-releases/added")
async def new_releases_added(
    window: NewReleasesWindow = "week",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = None,
    tag: str | None = None,
) -> JSONResponse:
    data = _new_releases_service.get_added(
        window,
        page,
        page_size,
        genre=genre,
        tag=tag,
    )
    return JSONResponse(content=data, headers={"Cache-Control": _NEW_RELEASES_CACHE})


_DISCOVERY_CACHE = "public, s-maxage=300, stale-while-revalidate=600"

DiscoveryFeedKind = Literal["popular", "top_rated", "hidden_gem", "new_release", "just_analyzed"]


@app.get("/api/discovery/{kind}")
async def discovery_feed(
    kind: DiscoveryFeedKind,
    limit: int = Query(default=8, ge=1, le=24),
) -> JSONResponse:
    """Top-N catalog-wide games for a homepage discovery row.

    Reads from mv_discovery_feeds (pre-computed). Replaces the five unfiltered
    `/api/games?sort=...` calls the homepage previously made, which went through
    GameRepository.list_games() slow path against the base `games` table.
    """
    games = _matview_repo.list_discovery_feed(kind, limit)
    return JSONResponse(
        content={"games": games},
        headers={"Cache-Control": _DISCOVERY_CACHE},
    )


@app.get("/api/catalog/stats")
async def catalog_stats() -> JSONResponse:
    """Cheap headline counts for the homepage ProofBar.

    `total_games` is a pg_class.reltuples estimate, not a COUNT(*) — instant.
    """
    return JSONResponse(
        content={"total_games": _matview_repo.get_total_games_count()},
        headers={"Cache-Control": _DISCOVERY_CACHE},
    )


_REPORTS_CACHE = "public, s-maxage=300, stale-while-revalidate=600"


# Sample game pinned to BG3 — high coverage across timeline/overlap/report tables,
# stable identity for snapshot-driven mini-visualisations on the homepage.
_HOME_INTEL_SAMPLE_APPID = 1086940
_HOME_INTEL_CACHE = "public, s-maxage=21600, stale-while-revalidate=86400"


@app.get("/api/home/intel-snapshot")
async def get_home_intel_snapshot() -> JSONResponse:
    """Single-call snapshot powering the homepage 4-card intelligence preview.

    Option A in 02-landing-positioning-reconcile.md: direct repo pulls behind
    one endpoint. If latency becomes a concern, upgrade to mv_home_intel_snapshot.
    Each sub-block is independently fault-tolerant — a missing source returns
    null for that block while the rest of the snapshot still renders.
    """
    sentiment_sample: dict | None = None
    overlap_sample: dict | None = None
    trend_sample: dict | None = None
    report_sample: dict | None = None
    sample_name: str | None = None

    try:
        sample_game = _game_repo.find_by_appid(_HOME_INTEL_SAMPLE_APPID)
        sample_name = sample_game.name if sample_game else None
    except Exception:  # pragma: no cover — partial-data fallback
        logger.exception("home_intel: sample_name lookup failed")

    try:
        stats = _review_repo.find_review_stats(_HOME_INTEL_SAMPLE_APPID)
        timeline = stats.get("timeline") or []
        if timeline:
            sentiment_sample = {
                "appid": _HOME_INTEL_SAMPLE_APPID,
                "name": sample_name,
                "timeline": timeline,
            }
    except Exception:  # pragma: no cover — partial-data fallback
        logger.exception("home_intel: sentiment_sample failed")

    try:
        overlap = _matview_repo.get_audience_overlap(_HOME_INTEL_SAMPLE_APPID, limit=5)
        if overlap.get("overlaps"):
            overlap_sample = {
                "appid": _HOME_INTEL_SAMPLE_APPID,
                "name": sample_name,
                "total_reviewers": overlap.get("total_reviewers", 0),
                "overlaps": overlap["overlaps"],
            }
    except Exception:  # pragma: no cover
        logger.exception("home_intel: overlap_sample failed")

    try:
        trend = _analytics_service.get_sentiment_distribution(granularity="month", limit=12)
        if trend.get("periods"):
            trend_sample = {
                "granularity": trend["granularity"],
                "periods": trend["periods"],
            }
    except Exception:  # pragma: no cover
        logger.exception("home_intel: trend_sample failed")

    try:
        report = _report_repo.find_by_appid(_HOME_INTEL_SAMPLE_APPID)
        if report and report.report_json:
            rj = report.report_json
            report_sample = {
                "appid": _HOME_INTEL_SAMPLE_APPID,
                "name": sample_name,
                "one_liner": rj.get("one_liner") or "",
                "design_strengths": list(rj.get("design_strengths") or [])[:3],
            }
    except Exception:  # pragma: no cover
        logger.exception("home_intel: report_sample failed")

    return JSONResponse(
        content={
            "sentiment_sample": sentiment_sample,
            "overlap_sample": overlap_sample,
            "trend_sample": trend_sample,
            "report_sample": report_sample,
            "computed_at": datetime.now(UTC).isoformat(),
        },
        headers={"Cache-Control": _HOME_INTEL_CACHE},
    )


@app.get("/api/reports")
async def catalog_reports(
    sort: str = "last_analyzed",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = None,
    tag: str | None = None,
) -> JSONResponse:
    data = _catalog_report_service.get_available_reports(
        genre=genre,
        tag=tag,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return JSONResponse(content=data, headers={"Cache-Control": _REPORTS_CACHE})


@app.get("/api/reports/coming-soon")
async def catalog_coming_soon(
    sort: str = "request_count",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
) -> JSONResponse:
    data = _catalog_report_service.get_coming_soon(
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return JSONResponse(content=data, headers={"Cache-Control": _REPORTS_CACHE})


@app.post("/api/reports/request-analysis")
async def request_analysis(body: AnalysisRequestBody) -> dict:
    normalized_email = body.email.strip().lower()
    return _catalog_report_service.request_analysis(
        appid=body.appid,
        email=normalized_email,
    )


@app.get("/api/reports/request-count/{appid}")
async def report_request_count(appid: int) -> JSONResponse:
    count = _catalog_report_service.get_request_count(appid=appid)
    return JSONResponse(
        content={"appid": appid, "request_count": count},
        headers={"Cache-Control": _REPORTS_CACHE},
    )


@app.post("/api/waitlist")
async def join_waitlist(body: WaitlistRequest) -> dict:
    """Add an email to the waitlist and enqueue a confirmation email."""
    normalized_email = body.email.strip().lower()
    inserted = _waitlist_repo.add(normalized_email)
    should_enqueue = inserted or _waitlist_repo.needs_confirmation(normalized_email)

    if should_enqueue and _email_queue_url:
        msg = WaitlistConfirmationMessage(email=normalized_email)
        try:
            _sqs_client.send_message(
                QueueUrl=_email_queue_url,
                MessageBody=msg.model_dump_json(),
            )
            logger.info("Waitlist confirmation queued", extra={"email": normalized_email})
        except Exception:
            logger.exception(
                "Failed to enqueue waitlist confirmation", extra={"email": normalized_email}
            )
    elif should_enqueue:
        logger.warning(
            "EMAIL_QUEUE_URL not set, skipping confirmation email",
            extra={"email": normalized_email},
        )

    return {"status": "registered" if inserted else "already_registered"}


@app.post("/api/waitlist/suggestion")
async def submit_waitlist_suggestion(body: WaitlistSuggestionRequest) -> dict:
    """Record a freeform Pro-feature suggestion from a waitlist member."""
    normalized_email = body.email.strip().lower()
    suggestion = body.suggestion.strip()
    if not suggestion:
        raise HTTPException(
            status_code=400,
            detail={"error": "Suggestion cannot be empty", "code": "empty_suggestion"},
        )
    _waitlist_suggestion_repo.add(normalized_email, suggestion)
    return {"status": "received"}


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict:
    # TODO: gate via JWT "pro" role claim — see scripts/prompts/auth0-authentication.md
    raise HTTPException(
        status_code=404, detail={"error": "Not yet available", "code": "not_implemented"}
    )

    from .chat import answer_query

    # Thin storage adapter — obtains a DB connection via get_conn() per query
    class _ChatStorage:
        def query_catalog(self, sql: str, params: tuple = ()) -> list:
            with get_conn().cursor() as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
            return rows

    try:
        return await answer_query(body.message, _ChatStorage())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": f"Query failed: {exc}", "code": "query_error"},
        ) from exc


# Lambda handler — wraps FastAPI app for Lambda Web Adapter / Mangum
try:
    from mangum import Mangum  # type: ignore[import-untyped]

    _mangum = Mangum(app, lifespan="off")

    @logger.inject_lambda_context(clear_state=True)
    def handler(event: dict, context: object) -> dict:  # type: ignore[misc]
        return _mangum(event, context)
except ImportError:
    # Mangum not available; Lambda Web Adapter extension handles routing instead
    def handler(event: dict, context: object) -> dict:  # type: ignore[misc]
        raise RuntimeError("mangum is required for Lambda deployment — install it in the layer")
