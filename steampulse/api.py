"""FastAPI application — V1 + V2 endpoints."""

import asyncio
import json
import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import analyze_reviews
from .fetcher import fetch_app_metadata, fetch_reviews
from .rate_limiter import consume, get_client_ip, is_rate_limited
from .storage import get_storage

app = FastAPI(title="SteamPulse", version="0.1.0")

TEMPLATES_DIR = Path(__file__).parent / "templates"
_storage = get_storage()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    appid: int


class ValidateKeyRequest(BaseModel):
    license_key: str
    appid: int


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


# ---------------------------------------------------------------------------
# Lemon Squeezy helpers
# ---------------------------------------------------------------------------

LS_API_BASE = "https://api.lemonsqueezy.com/v1"


def _ls_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.getenv('LEMON_SQUEEZY_API_KEY', '')}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }


async def _ls_validate(license_key: str, instance_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{LS_API_BASE}/licenses/validate",
            headers=_ls_headers(),
            json={"license_key": license_key, "instance_id": instance_id},
        )
        return resp.json()


async def _ls_activate(license_key: str, instance_name: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{LS_API_BASE}/licenses/activate",
            headers=_ls_headers(),
            json={"license_key": license_key, "instance_name": instance_name},
        )
        return resp.json()


# ---------------------------------------------------------------------------
# Email helper (fire-and-forget)
# ---------------------------------------------------------------------------


async def _send_report_email(to_email: str, game_name: str, result: dict) -> None:
    """Send the full analysis report via Resend. Called as a background task."""
    import resend

    resend.api_key = os.getenv("RESEND_API_KEY", "")
    from_email = os.getenv("RESEND_FROM_EMAIL", "reports@steampulse.gg")

    if not resend.api_key or not to_email:
        return

    body_lines = [
        f"<h1>SteamPulse Report: {game_name}</h1>",
        f"<p><strong>Overall sentiment:</strong> {result.get('overall_sentiment')} "
        f"({result.get('sentiment_score', 0):.0%})</p>",
        f"<p><em>{result.get('one_liner', '')}</em></p>",
        "<h2>Top Praises</h2><ul>",
        *[f"<li>{p}</li>" for p in result.get("top_praises", [])],
        "</ul><h2>Top Complaints</h2><ul>",
        *[f"<li>{c}</li>" for c in result.get("top_complaints", [])],
        "</ul><h2>Developer Action Items</h2><ol>",
        *[f"<li>{a}</li>" for a in result.get("dev_action_items", [])],
        "</ol>",
        "<hr><p><small>Powered by SteamPulse</small></p>",
    ]

    try:
        resend.Emails.send(
            {
                "from": from_email,
                "to": [to_email],
                "subject": f"SteamPulse Report: {game_name}",
                "html": "\n".join(body_lines),
            }
        )
    except Exception:
        pass  # Email failure is non-fatal


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = TEMPLATES_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "storage": _storage.backend_name(),
        "pro_enabled": os.getenv("PRO_ENABLED", "false").lower() == "true",
    }


@app.post("/preview")
async def preview(body: PreviewRequest, request: Request):
    appid = body.appid

    # Rate limit check
    ip = get_client_ip(request)
    if is_rate_limited(ip):
        return JSONResponse(
            status_code=402,
            content={
                "error": "free_limit_reached",
                "checkout_url": os.getenv("LEMON_SQUEEZY_SINGLE_CHECKOUT_URL", ""),
                "checkout_url_pack5": os.getenv("LEMON_SQUEEZY_PACK5_CHECKOUT_URL", ""),
            },
        )

    # Cache hit
    cached = _storage.get_analysis(appid)
    if cached:
        return _free_tier_response(cached)

    # Fetch metadata
    try:
        meta = await fetch_app_metadata(appid)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if meta is None:
        raise HTTPException(status_code=404, detail=f"App {appid} not found on Steam")

    # Fetch reviews
    try:
        reviews = await fetch_reviews(appid)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not reviews:
        raise HTTPException(
            status_code=422,
            detail="No English reviews found for this game",
        )

    # Run LLM analysis
    try:
        result = await analyze_reviews(reviews, meta["name"], appid=appid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    # Merge metadata fields
    result.update(
        {
            "appid": appid,
            "header_image": meta.get("header_image", ""),
        }
    )

    _storage.store_analysis(appid, result)

    # Consume rate limit slot
    consume(ip, appid)

    return _free_tier_response(result)


def _free_tier_response(result: dict) -> dict:
    return {
        "game_name": result.get("game_name", ""),
        "overall_sentiment": result.get("overall_sentiment", ""),
        "sentiment_score": result.get("sentiment_score", 0.0),
        "one_liner": result.get("one_liner", ""),
        "appid": result.get("appid"),
        "header_image": result.get("header_image", ""),
        "checkout_single": os.getenv("LEMON_SQUEEZY_SINGLE_CHECKOUT_URL", ""),
        "checkout_pack5": os.getenv("LEMON_SQUEEZY_PACK5_CHECKOUT_URL", ""),
    }


@app.post("/validate-key")
async def validate_key(body: ValidateKeyRequest, request: Request):
    license_key = body.license_key
    appid = body.appid
    instance_id = str(appid)

    # 1. Validate with Lemon Squeezy
    try:
        ls_resp = await _ls_validate(license_key, instance_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"License server unreachable: {e}")

    if not ls_resp.get("valid"):
        return JSONResponse(
            status_code=403,
            content={"error": "invalid_key"},
        )

    activations_remaining = ls_resp.get("license_key", {}).get("activations_limit", 1) - ls_resp.get(
        "license_key", {}
    ).get("activation_usage", 0)

    if activations_remaining <= 0:
        return JSONResponse(
            status_code=402,
            content={
                "error": "no_credits",
                "checkout_url": os.getenv("LEMON_SQUEEZY_SINGLE_CHECKOUT_URL", ""),
            },
        )

    # 2. Activate (consume one credit)
    try:
        await _ls_activate(license_key, f"analysis-{appid}")
    except Exception:
        pass  # Non-fatal — we still return the result

    activations_remaining = max(0, activations_remaining - 1)

    # 3. Get (or run) full analysis
    result = _storage.get_analysis(appid)
    if result is None:
        meta = await fetch_app_metadata(appid)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"App {appid} not found")
        reviews = await fetch_reviews(appid)
        if not reviews:
            raise HTTPException(status_code=422, detail="No English reviews found")
        result = await analyze_reviews(reviews, meta["name"], appid=appid)
        result["appid"] = appid
        result["header_image"] = meta.get("header_image", "")
        _storage.store_analysis(appid, result)

    # 4. Fire-and-forget email
    customer_email = ls_resp.get("meta", {}).get("customer_email", "")
    if customer_email:
        asyncio.create_task(
            _send_report_email(customer_email, result.get("game_name", ""), result)
        )

    return {
        **result,
        "activations_remaining": activations_remaining,
        "checkout_single": os.getenv("LEMON_SQUEEZY_SINGLE_CHECKOUT_URL", ""),
        "checkout_pack5": os.getenv("LEMON_SQUEEZY_PACK5_CHECKOUT_URL", ""),
    }


# ---------------------------------------------------------------------------
# V2 Pro endpoints
# ---------------------------------------------------------------------------


@app.post("/chat")
async def chat(body: ChatRequest, request: Request):
    pro_enabled = os.getenv("PRO_ENABLED", "false").lower() == "true"
    if not pro_enabled:
        raise HTTPException(status_code=404, detail="Pro features not enabled")

    # Validate Pro subscription via Authorization header
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing license key")

    license_key = auth.removeprefix("Bearer ").strip()

    try:
        ls_resp = await _ls_validate(license_key, "pro-session")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"License server unreachable: {e}")

    if not ls_resp.get("valid"):
        raise HTTPException(status_code=403, detail="Invalid or expired Pro subscription")

    from .chat import answer_query

    try:
        result = await answer_query(body.message, _storage)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")

    return result
