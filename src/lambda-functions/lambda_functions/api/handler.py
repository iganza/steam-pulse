"""FastAPI application — JSON API only, no HTML rendering."""

import os
import uuid

import boto3  # type: ignore[import-untyped]
import httpx
from aws_lambda_powertools import Logger, Tracer
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from library_layer.config import SteamPulseConfig
from library_layer.events import WaitlistConfirmationMessage
from library_layer.models.temporal import build_temporal_context
from library_layer.steam_source import DirectSteamSource, SteamAPIError
from pydantic import BaseModel, EmailStr

logger = Logger(service="api")
tracer = Tracer(service="api")

app = FastAPI(title="SteamPulse", version="0.1.0")

# Module-level singletons — initialized outside handlers for Lambda warm reuse.
_http_client: httpx.Client = httpx.Client(timeout=30.0)
_steam = DirectSteamSource(_http_client)

# Config + SSM resolution at cold start.
# On Lambda: SteamPulseConfig reads env vars set by CDK via to_lambda_env().
# Locally: falls back to DATABASE_URL and inline analysis (no SSM).
_is_lambda = bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

if _is_lambda:
    # Running inside Lambda — no try/except.  Any config or SSM failure must
    # crash the cold start immediately; silent fallback would hide misconfigured
    # SSM parameters or missing IAM permissions and allow the API to run inline
    # analysis instead of Step Functions.
    _api_config = SteamPulseConfig()
    from aws_lambda_powertools.utilities.parameters import get_parameter
    _sfn_arn: str | None = get_parameter(_api_config.STEP_FUNCTIONS_PARAM_NAME)
    _email_queue_url: str | None = get_parameter(_api_config.EMAIL_QUEUE_PARAM_NAME)
else:
    # Local dev — no SSM, no full config.
    _api_config = None  # type: ignore[assignment]
    _sfn_arn = os.getenv("STEP_FUNCTIONS_ARN")
    _email_queue_url = os.getenv("EMAIL_QUEUE_URL")

_sqs_client = boto3.client("sqs")

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Repository wiring — built once at module level.
# Raises RuntimeError at cold start if DATABASE_URL is not set.
# ---------------------------------------------------------------------------

from library_layer.repositories.analytics_repo import AnalyticsRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.job_repo import JobRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.repositories.waitlist_repo import WaitlistRepository
from library_layer.utils.db import get_conn

_conn = get_conn()
_analytics_repo = AnalyticsRepository(_conn)
_game_repo = GameRepository(_conn)
_report_repo = ReportRepository(_conn)
_review_repo = ReviewRepository(_conn)
_job_repo = JobRepository(_conn)
_tag_repo = TagRepository(_conn)
_waitlist_repo = WaitlistRepository(_conn)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    appid: int


class WaitlistRequest(BaseModel):
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


def _upsert_report(appid: int, report: dict) -> None:
    name = report.get("game_name", f"App {appid}")
    _game_repo.ensure_stub(appid, name)
    _report_repo.upsert({**report, "appid": appid})


def _get_job(job_id: str) -> dict | None:
    return _job_repo.find(job_id)


def _set_job(job_id: str, status: str, appid: int) -> None:
    _job_repo.upsert(job_id, status, appid)


def _trigger_analysis(appid: int, game_name: str) -> str:
    """Start analysis via Step Functions. Returns a job_id (executionArn)."""
    if _sfn_arn:
        try:
            import json as _json

            import boto3  # type: ignore[import-untyped]

            sfn = boto3.client("stepfunctions")
            execution = sfn.start_execution(
                stateMachineArn=_sfn_arn,
                name=f"analysis-{appid}-{uuid.uuid4().hex[:8]}",
                input=_json.dumps({"appid": appid, "game_name": game_name}),
            )
            job_id: str = execution["executionArn"]
        except ImportError as exc:
            logger.error("boto3 not installed — cannot trigger Step Functions", extra={"appid": appid})
            raise HTTPException(
                status_code=503,
                detail={"error": "step_functions_unavailable", "code": "boto3_missing"},
            ) from exc
        _set_job(job_id, "running", appid)
        return job_id

    raise HTTPException(
        status_code=503,
        detail={"error": "step_functions_unavailable", "code": "sfn_arn_not_configured"},
    )



def _preview_fields(report: dict) -> dict:
    return {
        "game_name": report.get("game_name", ""),
        "overall_sentiment": report.get("overall_sentiment", ""),
        "sentiment_score": report.get("sentiment_score", 0.0),
        "one_liner": report.get("one_liner", ""),
        "audience_profile": report.get("audience_profile", {}),
        "appid": report.get("appid"),
    }


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


@app.post("/api/preview", response_model=None)
async def preview(body: PreviewRequest) -> JSONResponse | dict:
    appid = body.appid
    logger.append_keys(appid=appid)

    # Cache hit — return preview fields only
    cached = _get_report(appid)
    if cached:
        return _preview_fields(cached)

    # Fetch game details to get name
    try:
        details = _steam.get_app_details(appid)
    except SteamAPIError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc), "code": "steam_api_error"}) from exc

    if not details:
        raise HTTPException(
            status_code=404,
            detail={"error": f"App {appid} not found on Steam", "code": "not_found"},
        )

    game_name: str = details.get("name", f"App {appid}")

    # Trigger analysis — Step Functions (async) or inline (local dev, sync)
    job_id = _trigger_analysis(appid, game_name)

    # If inline run completed, report is already stored
    report = _get_report(appid)
    if report:
        return report

    # Step Functions path — return 202 for polling
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "appid": appid, "status": "running"},
    )



@app.get("/api/status/{job_id:path}")
async def job_status(job_id: str) -> dict:
    if _sfn_arn and not job_id.startswith("local-"):
        try:
            import boto3  # type: ignore[import-untyped]

            sfn = boto3.client("stepfunctions")
            sfn_resp = sfn.describe_execution(executionArn=job_id)
            sfn_status: str = sfn_resp["status"]
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": "boto3 not installed", "code": "boto3_missing"},
            ) from exc
        except Exception as exc:
            logger.error("Step Functions describe_execution failed", extra={"error": str(exc)})
            raise HTTPException(
                status_code=503,
                detail={"error": "Could not fetch job status", "code": "sfn_error"},
            ) from exc

        match sfn_status:
            case "RUNNING":
                return {"status": "running"}
            case "SUCCEEDED":
                job = _get_job(job_id)
                report = _get_report(job["appid"]) if job else None
                return {"status": "complete", "report": report}
            case _:
                return {"status": "failed"}

    # Local dev / inline path
    job = _get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Job not found", "code": "not_found"},
        )

    match job["status"]:
        case "complete":
            report = _get_report(job["appid"])
            return {"status": "complete", "report": report}
        case "failed":
            return {"status": "failed"}
        case _:
            return {"status": "running"}


@app.get("/api/games")
async def list_games(
    q: str | None = None,
    genre: str | None = None,
    tag: str | None = None,
    developer: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    min_reviews: int | None = None,
    has_analysis: bool | None = None,
    sentiment: str | None = None,
    price_tier: str | None = None,
    deck: str | None = None,
    sort: str = "review_count",
    limit: int = 24,
    offset: int = 0,
) -> dict:
    limit = min(limit, 100)
    return _game_repo.list_games(
        q=q,
        genre=genre,
        tag=tag,
        developer=developer,
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


@app.get("/api/games/{appid}/report")
async def get_game_report(appid: int) -> dict:
    """Return the full report JSON if it exists, or a status object.
    Always includes game metadata (short_desc, developer, etc.) alongside the report.
    """
    logger.append_keys(appid=appid)
    game = _game_repo.find_by_appid(appid)
    game_meta: dict = {}
    if game:
        genres = [g["name"] for g in _tag_repo.find_genres_for_game(appid)]
        tags = [t["name"] for t in _tag_repo.find_tags_for_game(appid)]
        game_meta = {
            "short_desc": game.short_desc,
            "developer": game.developer,
            "release_date": game.release_date,
            "price_usd": float(game.price_usd) if game.price_usd else None,
            "is_free": game.is_free,
            "genres": genres,
            "tags": tags,
            "deck_compatibility": game.deck_compatibility,
            "deck_test_results": game.deck_test_results,
        }

    report = _get_report(appid)
    if report:
        temporal_dict = None
        if game:
            velocity_data = _review_repo.find_review_velocity(appid)
            ea_data = _review_repo.find_early_access_impact(appid)
            temporal = build_temporal_context(game, velocity_data, ea_data)
            temporal_dict = temporal.model_dump()
        return {"status": "available", "report": report, "game": game_meta, "temporal": temporal_dict}

    review_count = (game.review_count_english or game.review_count) if game else _game_repo.get_review_count(appid)
    return {
        "status": "not_available",
        "review_count": review_count,
        "game": game_meta,
    }


@app.get("/api/games/{appid}/review-stats")
async def get_review_stats(appid: int) -> dict:
    """Weekly sentiment timeline + playtime buckets + velocity for a game."""
    logger.append_keys(appid=appid)
    return _review_repo.find_review_stats(appid)


@app.get("/api/games/{appid}/benchmarks")
async def get_benchmarks(appid: int) -> dict:
    """Percentile ranking vs. genre+year+price cohort (Pro context)."""
    logger.append_keys(appid=appid)
    game = _game_repo.find_by_appid(appid)
    if not game:
        raise HTTPException(status_code=404, detail={"error": "Game not found", "code": "not_found"})

    genres = [g["name"] for g in _tag_repo.find_genres_for_game(appid)]
    release_date = game.release_date
    if not genres or not release_date:
        return {"sentiment_rank": None, "popularity_rank": None, "cohort_size": 0}

    year = int(str(release_date)[:4])
    return _game_repo.find_benchmarks(
        appid=appid,
        genre=genres[0],
        year=year,
        price=float(game.price_usd) if game.price_usd else None,
        is_free=game.is_free or False,
    )


@app.get("/api/genres")
async def list_genres() -> list[dict]:
    return _game_repo.list_genres()


@app.get("/api/tags/top")
async def list_top_tags(limit: int = 24) -> list[dict]:
    limit = min(limit, 100)
    return _game_repo.list_tags(limit=limit)


@app.get("/api/games/{appid}/audience-overlap")
async def get_audience_overlap(appid: int, limit: int = 20) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(status_code=404, detail={"error": "game_not_found", "code": "not_found"})
    return _analytics_repo.find_audience_overlap(appid, max(1, min(limit, 50)))


@app.get("/api/games/{appid}/playtime-sentiment")
async def get_playtime_sentiment(appid: int) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(status_code=404, detail={"error": "game_not_found", "code": "not_found"})
    return _review_repo.find_playtime_sentiment(appid)


@app.get("/api/games/{appid}/early-access-impact")
async def get_early_access_impact(appid: int) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(status_code=404, detail={"error": "game_not_found", "code": "not_found"})
    return _review_repo.find_early_access_impact(appid)


@app.get("/api/games/{appid}/review-velocity")
async def get_review_velocity(appid: int) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(status_code=404, detail={"error": "game_not_found", "code": "not_found"})
    return _review_repo.find_review_velocity(appid)


@app.get("/api/games/{appid}/top-reviews")
async def get_top_reviews(appid: int, sort: str = "helpful", limit: int = 10) -> dict:
    logger.append_keys(appid=appid)
    if not _game_repo.find_by_appid(appid):
        raise HTTPException(status_code=404, detail={"error": "game_not_found", "code": "not_found"})
    if sort not in ("helpful", "funny"):
        sort = "helpful"
    return {"sort": sort, "reviews": _review_repo.find_top_reviews(appid, sort, max(1, min(limit, 50)))}


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


@app.post("/api/waitlist")
async def join_waitlist(body: WaitlistRequest) -> dict:
    """Add an email to the waitlist and enqueue a confirmation email."""
    normalized_email = body.email.strip().lower()
    inserted = _waitlist_repo.add(normalized_email)
    if not inserted:
        # Already on the waitlist — return 200 so the UI shows success.
        return {"status": "already_registered"}

    if _email_queue_url:
        msg = WaitlistConfirmationMessage(email=normalized_email)
        try:
            _sqs_client.send_message(
                QueueUrl=_email_queue_url,
                MessageBody=msg.model_dump_json(),
            )
            logger.info("Waitlist confirmation queued", extra={"email": normalized_email})
        except Exception:
            # SQS failure must not return 500 — email is already registered.
            # Confirmation will be missing but the signup succeeded.
            logger.exception("Failed to enqueue waitlist confirmation", extra={"email": normalized_email})
    else:
        logger.warning("EMAIL_QUEUE_URL not set — skipping confirmation email", extra={"email": normalized_email})

    return {"status": "registered"}


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict:
    # TODO: gate via JWT "pro" role claim — see scripts/prompts/auth0-authentication.md
    raise HTTPException(status_code=404, detail={"error": "Not yet available", "code": "not_implemented"})

    from .chat import answer_query

    # Thin storage adapter — uses the module-level DB connection
    class _ChatStorage:
        def query_catalog(self, sql: str, params: tuple = ()) -> list:
            with _conn.cursor() as cur:
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
    @tracer.capture_lambda_handler
    def handler(event: dict, context: object) -> dict:  # type: ignore[misc]
        return _mangum(event, context)
except ImportError:
    # Mangum not available; Lambda Web Adapter extension handles routing instead
    def handler(event: dict, context: object) -> dict:  # type: ignore[misc]
        raise RuntimeError("mangum is required for Lambda deployment — install it in the layer")
