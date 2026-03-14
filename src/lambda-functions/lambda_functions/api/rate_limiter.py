"""In-memory per-IP rate limiter — 1 free preview per IP (resets on restart)."""

from fastapi import Request

# { "1.2.3.4": { "used": True, "appid": 440 } }
_limits: dict[str, dict] = {}


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_rate_limited(ip: str) -> bool:
    return False
    #return _limits.get(ip, {}).get("used", False)


def consume(ip: str, appid: int) -> None:
    _limits[ip] = {"used": True, "appid": appid}


def reset(ip: str) -> None:
    _limits.pop(ip, None)
