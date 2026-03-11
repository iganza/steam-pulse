"""Fetches review counts from Steam and updates the games table."""

from typing import Optional

import httpx

from .db import get_connection

REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"


async def _fetch_review_summary(appid: int) -> Optional[dict]:
    """Fetch a quick review summary (total positive/negative) from the Steam API."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                REVIEWS_URL.format(appid=appid),
                params={
                    "json": "1",
                    "filter": "summary",
                    "language": "english",
                    "num_per_page": "0",
                    "cursor": "*",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError):
            return None

    if not data.get("success"):
        return None

    qs = data.get("query_summary", {})
    return {
        "total_positive": qs.get("total_positive", 0),
        "total_negative": qs.get("total_negative", 0),
        "review_score_desc": qs.get("review_score_desc", ""),
    }


async def crawl_reviews(appid: int) -> bool:
    """
    Fetch review counts for a given appid and update the games table.
    Returns True on success.
    """
    summary = await _fetch_review_summary(appid)
    if summary is None:
        print(f"[review_crawler] Could not fetch review summary for {appid}")
        return False

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE games
                SET total_positive     = %(total_positive)s,
                    total_negative     = %(total_negative)s,
                    review_score_desc  = %(review_score_desc)s
                WHERE appid = %(appid)s
                """,
                {**summary, "appid": appid},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[review_crawler] Updated review counts for {appid}: "
        f"+{summary['total_positive']} / -{summary['total_negative']}"
    )
    return True
