"""FastAPI application — JSON API only, no HTML rendering."""

import logging
import os
import uuid

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
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
LS_API_BASE = "https://api.lemonsqueezy.com/v1"

# ---------------------------------------------------------------------------
# Repository wiring — built once at module level.
# Falls back to None (in-memory) when DATABASE_URL is not set.
# ---------------------------------------------------------------------------

_report_cache: dict[int, dict] = {}
_job_cache: dict[str, dict] = {}

_game_repo = None
_report_repo = None
_job_repo = None


def _get_db_conn() -> object | None:
    """Return a psycopg2 connection if DATABASE_URL is set, else None."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return None
    try:
        import psycopg2  # type: ignore[import-untyped]
        import psycopg2.extras
        return psycopg2.connect(db_url, cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception:
        return None


def _init_repos() -> None:
    global _game_repo, _report_repo, _job_repo
    conn = _get_db_conn()
    if conn:
        from library_layer.repositories.game_repo import GameRepository
        from library_layer.repositories.job_repo import JobRepository
        from library_layer.repositories.report_repo import ReportRepository
        _game_repo = GameRepository(conn)
        _report_repo = ReportRepository(conn)
        _job_repo = JobRepository(conn)


_init_repos()


async def _get_report(appid: int) -> dict | None:
    if _report_repo is not None:
        result = _report_repo.find_by_appid(appid)
        return result.report_json if result else None
    return _report_cache.get(appid)


async def _upsert_report(appid: int, report: dict) -> None:
    if _report_repo is not None and _game_repo is not None:
        name = report.get("game_name", f"App {appid}")
        _game_repo.ensure_stub(appid, name)
        _report_repo.upsert({**report, "appid": appid})
        return
    _report_cache[appid] = report


async def _get_job(job_id: str) -> dict | None:
    if _job_repo is not None:
        return _job_repo.find(job_id)
    return _job_cache.get(job_id)


async def _set_job(job_id: str, status: str, appid: int) -> None:
    if _job_repo is not None:
        _job_repo.upsert(job_id, status, appid)
        return
    _job_cache[job_id] = {"job_id": job_id, "status": status, "appid": appid}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    appid: int


class ValidateKeyRequest(BaseModel):
    license_key: str
    appid: int


class AnalyzeRequest(BaseModel):
    appid: int
    force: bool = False


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ls_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv('LEMONSQUEEZY_API_KEY', '')}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }


def _require_admin(x_admin_key: str | None) -> None:
    expected = os.getenv("ADMIN_KEY", "")
    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=403, detail={"error": "forbidden", "code": "invalid_admin_key"})


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

    # Cache hit — return immediately
    cached = await _get_report(appid)
    if cached:
        return _preview_fields(cached)

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
        return _preview_fields(report)

    # Step Functions path — return 202 for polling
    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "appid": appid, "status": "running"},
    )


@app.post("/api/validate-key", response_model=None)
async def validate_key(body: ValidateKeyRequest) -> JSONResponse | dict:
    appid = body.appid

    # Dev bypass — set DEV_KEY in .env to skip Lemon Squeezy validation locally
    dev_key = os.getenv("DEV_KEY", "")
    if dev_key and body.license_key == dev_key:
        report = await _get_report(appid)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail={"error": f"No cached report for appid {appid}. Run the analysis first.", "code": "not_found"},
            )
        return {**report, "activations_remaining": 99}

    # Validate with Lemon Squeezy
    try:
        resp = await _http_client.post(
            f"{LS_API_BASE}/licenses/validate",
            headers=_ls_headers(),
            json={"license_key": body.license_key, "instance_id": str(appid)},
        )
        ls_data = resp.json()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"License server unreachable: {exc}", "code": "ls_unavailable"},
        ) from exc

    if not ls_data.get("valid"):
        return JSONResponse(
            status_code=403,
            content={"error": "invalid_key", "code": "invalid_key"},
        )

    ls_key = ls_data.get("license_key", {})
    activations_remaining = ls_key.get("activations_limit", 1) - ls_key.get("activation_usage", 0)
    if activations_remaining <= 0:
        return JSONResponse(
            status_code=402,
            content={"error": "no_credits", "code": "no_credits"},
        )

    # Consume one activation (non-fatal if it fails)
    try:
        await _http_client.post(
            f"{LS_API_BASE}/licenses/activate",
            headers=_ls_headers(),
            json={"license_key": body.license_key, "instance_name": f"analysis-{appid}"},
        )
    except Exception:
        pass

    # Get or run full analysis
    report = await _get_report(appid)
    if report is None:
        try:
            details = await _steam.get_app_details(appid)
        except SteamAPIError as exc:
            raise HTTPException(
                status_code=503,
                detail={"error": str(exc), "code": "steam_api_error"},
            ) from exc
        if not details:
            raise HTTPException(
                status_code=404,
                detail={"error": f"App {appid} not found", "code": "not_found"},
            )
        game_name = details.get("name", f"App {appid}")
        reviews = await _steam.get_reviews(appid)
        if not reviews:
            raise HTTPException(
                status_code=422,
                detail={"error": "No reviews found for this app", "code": "no_reviews"},
            )
        report = await analyze_reviews(reviews, game_name, appid=appid)
        await _upsert_report(appid, report)

    return {**report, "activations_remaining": max(0, activations_remaining - 1)}


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
    genre: str | None = None,
    tag: str | None = None,
    developer: str | None = None,
    sort: str = "review_count",
    limit: int = 48,
    offset: int = 0,
) -> list[dict]:
    if _game_repo is None:
        return []
    limit = min(limit, 200)
    return _game_repo.list_games(
        genre=genre,
        tag=tag,
        developer=developer,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@app.get("/api/genres")
async def list_genres() -> list[dict]:
    if _game_repo is None:
        return []
    return _game_repo.list_genres()


@app.get("/api/tags/top")
async def list_top_tags(limit: int = 24) -> list[dict]:
    if _game_repo is None:
        return []
    limit = min(limit, 100)
    return _game_repo.list_tags(limit=limit)


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request) -> dict:
    if os.getenv("PRO_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail={"error": "Pro features not enabled", "code": "pro_disabled"})

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing license key", "code": "unauthorized"})

    license_key = auth.removeprefix("Bearer ").strip()

    try:
        resp = await _http_client.post(
            f"{LS_API_BASE}/licenses/validate",
            headers=_ls_headers(),
            json={"license_key": license_key, "instance_id": "pro-session"},
        )
        ls_data = resp.json()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": f"License server unreachable: {exc}", "code": "ls_unavailable"},
        ) from exc

    if not ls_data.get("valid"):
        raise HTTPException(
            status_code=403,
            detail={"error": "Invalid or expired Pro subscription", "code": "invalid_key"},
        )

    from .chat import answer_query

    # Build a thin storage-like object for the chat query
    class _ChatStorage:
        def query_catalog(self, sql: str, params: tuple = ()) -> list:
            conn = _get_db_conn()
            if not conn:
                return []
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = [dict(r) for r in cur.fetchall()]
            conn.close()
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
