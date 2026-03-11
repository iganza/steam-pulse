"""Fetches Steam appdetails + SteamSpy tags and writes to PostgreSQL."""

import asyncio
import os

import httpx

from .db import get_connection, upsert_categories, upsert_game, upsert_genres, upsert_tags

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAMSPY_URL = "https://steamspy.com/api.php"


async def _fetch_steam_details(appid: int) -> dict | None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            APPDETAILS_URL,
            params={"appids": str(appid), "l": "english"},
        )
        resp.raise_for_status()
        data = resp.json()

    key = str(appid)
    if key not in data or not data[key].get("success"):
        return None

    d = data[key]["data"]

    price_usd: float | None = None
    if not d.get("is_free") and d.get("price_overview"):
        price_usd = d["price_overview"].get("final", 0) / 100.0

    metacritic_score: int | None = None
    if d.get("metacritic"):
        metacritic_score = d["metacritic"].get("score")

    return {
        "appid": appid,
        "name": d.get("name", ""),
        "type": d.get("type", ""),
        "short_description": d.get("short_description", ""),
        "is_free": d.get("is_free", False),
        "price_usd": price_usd,
        "developers": d.get("developers", []),
        "publishers": d.get("publishers", []),
        "platforms": d.get("platforms", {}),
        "metacritic_score": metacritic_score,
        "genres": [g["description"] for g in d.get("genres", [])],
        "categories": [c["description"] for c in d.get("categories", [])],
        "release_date": d.get("release_date", {}).get("date", "") or None,
        "total_positive": d.get("recommendations", {}).get("total", 0),
        "total_negative": 0,
        "review_score_desc": d.get("review_score_desc", ""),
    }


async def _fetch_steamspy(appid: int) -> dict:
    steamspy_key = os.getenv("STEAMSPY_API_KEY")
    params: dict = {"request": "appdetails", "appid": str(appid)}
    if steamspy_key:
        params["key"] = steamspy_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(STEAMSPY_URL, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError):
            return {}


async def crawl_app(appid: int) -> bool:
    """
    Fetch Steam appdetails + SteamSpy for a given appid and upsert into PostgreSQL.
    Returns True on success.
    """
    steam_data, spy_data = await asyncio.gather(
        _fetch_steam_details(appid),
        _fetch_steamspy(appid),
    )

    if steam_data is None:
        print(f"[app_crawler] App {appid} not found on Steam, skipping.")
        return False

    # Merge SteamSpy tags
    tags: list[str] = list((spy_data.get("tags") or {}).keys())

    conn = get_connection()
    try:
        upsert_game(conn, appid, steam_data)
        upsert_genres(conn, appid, steam_data.get("genres", []))
        upsert_categories(conn, appid, steam_data.get("categories", []))
        upsert_tags(conn, appid, tags)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[app_crawler] Crawled app {appid} — {steam_data['name']}")
    return True
