"""FastAPI application — JSON API only, no HTML rendering."""

import logging
import os
import uuid

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from library_layer.analyzer import analyze_reviews
from library_layer.steam_source import DirectSteamSource, SteamAPIError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="SteamPulse", version="0.1.0")

# Module-level singletons — initialized outside handlers for Lambda warm reuse.
_http_client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)
_steam = DirectSteamSource(_http_client)

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Repository wiring — built once at module level.
# Raises RuntimeError at cold start if DATABASE_URL is not set.
# ---------------------------------------------------------------------------

from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.job_repo import JobRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.utils.db import get_conn

_game_repo: GameRepository
_report_repo: ReportRepository
_job_repo: JobRepository
_tag_repo: TagRepository
_db_conn: object  # psycopg2 connection

try:
    _db_conn = get_conn()
    _game_repo = GameRepository(_db_conn)
    _report_repo = ReportRepository(_db_conn)
    _job_repo = JobRepository(_db_conn)
    _tag_repo = TagRepository(_db_conn)
except Exception:
    pass  # DB unavailable — Lambda fails on first DB-dependent request; /health still works


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    appid: int


class ValidateKeyRequest(BaseModel):
    appid: int
    license_key: str = ""  # kept for frontend compatibility, ignored


class AnalyzeRequest(BaseModel):
    appid: int
    force: bool = False


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin(x_admin_key: str | None) -> None:
    expected = os.getenv("ADMIN_KEY", "")
    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=403, detail={"error": "forbidden", "code": "invalid_admin_key"})


async def _get_report(appid: int) -> dict | None:
    result = _report_repo.find_by_appid(appid)
    return result.report_json if result else None


async def _upsert_report(appid: int, report: dict) -> None:
    name = report.get("game_name", f"App {appid}")
    _game_repo.ensure_stub(appid, name)
    _report_repo.upsert({**report, "appid": appid})


async def _get_job(job_id: str) -> dict | None:
    return _job_repo.find(job_id)


async def _set_job(job_id: str, status: str, appid: int) -> None:
    _job_repo.upsert(job_id, status, appid)


async def _trigger_analysis(appid: int, game_name: str) -> str:
    """Start analysis via Step Functions if ARN is set, else run inline (local dev).
    Returns a job_id.
    """
    sfn_arn = os.getenv("STEP_FUNCTIONS_ARN")
    if sfn_arn:
        try:
            import json as _json

            import boto3  # type: ignore[import-untyped]

            sfn = boto3.client("stepfunctions")
            execution = sfn.start_execution(
                stateMachineArn=sfn_arn,
                name=f"analysis-{appid}-{uuid.uuid4().hex[:8]}",
                input=_json.dumps({"appid": appid, "game_name": game_name}),
            )
            job_id: str = execution["executionArn"]
        except ImportError as exc:
            logger.error("boto3 not installed — cannot trigger Step Functions")
            raise HTTPException(
                status_code=503,
                detail={"error": "step_functions_unavailable", "code": "boto3_missing"},
            ) from exc
        await _set_job(job_id, "running", appid)
        return job_id

    # Local dev: run inline synchronously, store result
    job_id = f"local-{appid}-{uuid.uuid4().hex[:8]}"
    await _set_job(job_id, "running", appid)
    reviews = await _steam.get_reviews(appid)
    if reviews:
        result = await analyze_reviews(reviews, game_name, appid=appid)
        await _upsert_report(appid, result)
        await _set_job(job_id, "complete", appid)
    else:
        await _set_job(job_id, "failed", appid)
    return job_id


async def _send_confirmation_email(to_email: str, game_name: str) -> None:
    """Fire-and-forget confirmation email via Resend."""
    try:
        import resend  # type: ignore[import-untyped]

        resend.api_key = os.getenv("RESEND_API_KEY", "")
        if not resend.api_key:
            return
        resend.Emails.send({
            "from": "reports@steampulse.io",
            "to": [to_email],
            "subject": f"SteamPulse: Your report for {game_name} is ready",
            "html": (
                f"<p>Your SteamPulse premium report for <strong>{game_name}</strong> "
                "is now unlocked. Return to the game page to view your full analysis.</p>"
                "<hr><p><small>Powered by SteamPulse</small></p>"
            ),
        })
    except Exception:
        logger.warning("Confirmation email failed for %s", to_email)


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
        "pro_enabled": os.getenv("PRO_ENABLED", "false").lower() == "true",
        "version": VERSION,
    }


@app.post("/api/preview", response_model=None)
async def preview(body: PreviewRequest) -> JSONResponse | dict:
    appid = body.appid

    # Cache hit — return full report (no more rate limiting)
    cached = await _get_report(appid)
    if cached:
        return cached

    # Fetch game details to get name
    try:
        details = await _steam.get_app_details(appid)
    except SteamAPIError as exc:
        raise HTTPException(status_code=503, detail={"error": str(exc), "code": "steam_api_error"}) from exc

    if not details:
        raise HTTPException(
            status_code=404,
            detail={"error": f"App {appid} not found on Steam", "code": "not_found"},
        )

    game_name: str = details.get("name", f"App {appid}")

    # Trigger analysis — Step Functions (async) or inline (local dev, sync)
    job_id = await _trigger_analysis(appid, game_name)

    # If inline run completed, report is already stored
    report = await _get_report(appid)
    if report:
        return report

    # Step Functions path — return 202 for polling
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "appid": appid, "status": "running"},
    )


@app.post("/api/validate-key", response_model=None)
async def validate_key(body: ValidateKeyRequest) -> JSONResponse | dict:
    appid = body.appid
    report = await _get_report(appid)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={"error": f"No cached report for appid {appid}. Run the analysis first.", "code": "not_found"},
        )
    return {**report, "activations_remaining": 99}


@app.get("/api/status/{job_id:path}")
async def job_status(job_id: str) -> dict:
    sfn_arn = os.getenv("STEP_FUNCTIONS_ARN")

    if sfn_arn and not job_id.startswith("local-"):
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
            logger.error("Step Functions describe_execution failed: %s", exc)
            raise HTTPException(
                status_code=503,
                detail={"error": "Could not fetch job status", "code": "sfn_error"},
            ) from exc

        match sfn_status:
            case "RUNNING":
                return {"status": "running"}
            case "SUCCEEDED":
                job = await _get_job(job_id)
                report = await _get_report(job["appid"]) if job else None
                return {"status": "complete", "report": report}
            case _:
                return {"status": "failed"}

    # Local dev / inline path
    job = await _get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Job not found", "code": "not_found"},
        )

    match job["status"]:
        case "complete":
            report = await _get_report(job["appid"])
            return {"status": "complete", "report": report}
        case "failed":
            return {"status": "failed"}
        case _:
            return {"status": "running"}


@app.post("/api/analyze")
async def trigger_analyze(
    body: AnalyzeRequest,
    x_admin_key: str | None = Header(default=None),
) -> dict:
    _require_admin(x_admin_key)

    if not body.force:
        cached = await _get_report(body.appid)
        if cached:
            return {"job_id": f"cached-{body.appid}", "cached": True}

    try:
        details = await _steam.get_app_details(body.appid)
    except SteamAPIError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": str(exc), "code": "steam_api_error"},
        ) from exc

    if not details:
        raise HTTPException(
            status_code=404,
            detail={"error": f"App {body.appid} not found on Steam", "code": "not_found"},
        )

    game_name = details.get("name", f"App {body.appid}")
    job_id = await _trigger_analysis(body.appid, game_name)
    return {"job_id": job_id}


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
        sort=sort,
        limit=limit,
        offset=offset,
    )


@app.get("/api/games/{appid}/report")
async def get_game_report(appid: int) -> dict:
    """Return the full report JSON if it exists, or a status object.
    Always includes game metadata (short_desc, developer, etc.) alongside the report.
    """
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
        }

    report = await _get_report(appid)
    if report:
        return {"status": "available", "report": report, "game": game_meta}

    review_count = game.review_count if game else _game_repo.get_review_count(appid)
    return {
        "status": "not_available",
        "review_count": review_count,
        "threshold": 500,
        "game": game_meta,
    }


@app.get("/api/genres")
async def list_genres() -> list[dict]:
    return _game_repo.list_genres()


@app.get("/api/tags/top")
async def list_top_tags(limit: int = 24) -> list[dict]:
    limit = min(limit, 100)
    return _game_repo.list_tags(limit=limit)


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict:
    if os.getenv("PRO_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail={"error": "Pro features not enabled", "code": "pro_disabled"})

    from .chat import answer_query

    # Thin storage adapter — uses the module-level DB connection
    class _ChatStorage:
        def query_catalog(self, sql: str, params: tuple = ()) -> list:
            with _db_conn.cursor() as cur:  # type: ignore[union-attr]
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
    handler = Mangum(app, lifespan="off")
except ImportError:
    # Mangum not available; Lambda Web Adapter extension handles routing instead
    def handler(event: dict, context: object) -> dict:  # type: ignore[misc]
        raise RuntimeError("mangum is required for Lambda deployment — install it in the layer")
