"""Lambda handler — crawls app metadata from Steam + SteamSpy and upserts to DB.

Triggered by SQS app-crawl-queue. Each message body: {"appid": <int>}
Writes to: games, tags, game_tags, genres, game_genres, game_categories.
"""

import asyncio
import json
import logging
import os
import re
import sys
from datetime import date, datetime

import httpx
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from steampulse.steam_source import DirectSteamSource, SteamAPIError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _parse_release_date(raw: str) -> date | None:
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B, %Y", "%b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    secret_arn = os.getenv("DB_SECRET_ARN")
    if secret_arn:
        import boto3  # type: ignore[import-untyped]
        sm = boto3.client("secretsmanager")
        secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
        return (
            f"postgresql://{secret['username']}:{secret['password']}"
            f"@{secret['host']}:{secret['port']}/{secret['dbname']}"
        )
    raise RuntimeError("No DATABASE_URL or DB_SECRET_ARN configured")


# ---------------------------------------------------------------------------
# Core crawl logic (importable for testing)
# ---------------------------------------------------------------------------


async def crawl_app(
    appid: int,
    steam: DirectSteamSource,
    conn: "psycopg2.connection",  # type: ignore[name-defined]
    dry_run: bool = False,
) -> bool:
    """Fetch and upsert one app. Returns True on success."""
    try:
        details = await steam.get_app_details(appid)
    except SteamAPIError as exc:
        logger.warning("Steam API error for appid=%s: %s", appid, exc)
        return False

    if not details:
        logger.info("appid=%s not found on Steam — skipping", appid)
        return False

    try:
        spy = await steam.get_steamspy_data(appid)
    except SteamAPIError:
        spy = {}

    # Identity
    devs: list[str] = details.get("developers") or []
    pubs: list[str] = details.get("publishers") or []

    # Dates
    release_info = details.get("release_date") or {}
    coming_soon: bool = bool(release_info.get("coming_soon", False)) if isinstance(release_info, dict) else False
    release_date = _parse_release_date(
        release_info.get("date", "") if isinstance(release_info, dict) else ""
    )

    # Pricing
    price_info = details.get("price_overview") or {}
    is_free: bool = bool(details.get("is_free", False))
    price_usd: float | None = (
        price_info.get("final", 0) / 100.0 if price_info and not is_free else None
    )

    # Review metrics — prefer SteamSpy counts (more accurate than recommendations)
    spy_positive: int = int(spy.get("positive") or 0)
    spy_negative: int = int(spy.get("negative") or 0)
    total_reviews = spy_positive + spy_negative
    positive_pct: int | None = (
        round(spy_positive / total_reviews * 100) if total_reviews > 0 else None
    )

    # Miscellaneous
    achievements = details.get("achievements") or {}
    achievements_total: int = (
        int(achievements.get("total", 0)) if isinstance(achievements, dict) else 0
    )
    metacritic = details.get("metacritic") or {}
    metacritic_score: int | None = (
        metacritic.get("score") if isinstance(metacritic, dict) else None
    )

    name: str = details.get("name") or f"App {appid}"
    slug = _slugify(name) or f"app-{appid}"

    game_row: dict = {
        "appid": appid,
        "name": name,
        "slug": slug,
        "type": details.get("type") or "game",
        "developer": devs[0] if devs else None,
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
        "review_count": total_reviews,
        "total_positive": spy_positive,
        "total_negative": spy_negative,
        "positive_pct": positive_pct,
        "review_score_desc": details.get("review_score_desc") or "",
        "steamspy_owners": str(spy.get("owners") or ""),
        "header_image": details.get("header_image") or "",
        "background_image": details.get("background") or "",
        "required_age": int(details.get("required_age") or 0),
        "platforms": json.dumps(details.get("platforms") or {}),
        "supported_languages": details.get("supported_languages") or "",
        "achievements_total": achievements_total,
        "metacritic_score": metacritic_score,
        "data_source": "steam_direct",
    }

    tags: dict = spy.get("tags") or {} if isinstance(spy.get("tags"), dict) else {}
    genres: list[dict] = details.get("genres") or []
    categories: list[dict] = details.get("categories") or []

    logger.info(
        "appid=%s name=%r — tags=%d genres=%d categories=%d",
        appid, name, len(tags), len(genres), len(categories),
    )

    if dry_run:
        return True

    with conn.cursor() as cur:
        # --- games ---
        cur.execute(
            """
            INSERT INTO games (
                appid, name, slug, type, developer, publisher, developers, publishers,
                website, release_date, coming_soon, price_usd, is_free,
                short_desc, detailed_description, about_the_game,
                review_count, total_positive, total_negative, positive_pct,
                review_score_desc, steamspy_owners, header_image, background_image,
                required_age, platforms, supported_languages,
                achievements_total, metacritic_score, crawled_at, data_source
            ) VALUES (
                %(appid)s, %(name)s, %(slug)s, %(type)s, %(developer)s, %(publisher)s,
                %(developers)s, %(publishers)s,
                %(website)s, %(release_date)s, %(coming_soon)s, %(price_usd)s, %(is_free)s,
                %(short_desc)s, %(detailed_description)s, %(about_the_game)s,
                %(review_count)s, %(total_positive)s, %(total_negative)s, %(positive_pct)s,
                %(review_score_desc)s, %(steamspy_owners)s, %(header_image)s,
                %(background_image)s, %(required_age)s, %(platforms)s,
                %(supported_languages)s, %(achievements_total)s, %(metacritic_score)s,
                NOW(), %(data_source)s
            )
            ON CONFLICT (appid) DO UPDATE SET
                name                 = EXCLUDED.name,
                slug                 = EXCLUDED.slug,
                type                 = EXCLUDED.type,
                developer            = EXCLUDED.developer,
                publisher            = EXCLUDED.publisher,
                developers           = EXCLUDED.developers,
                publishers           = EXCLUDED.publishers,
                website              = EXCLUDED.website,
                release_date         = EXCLUDED.release_date,
                coming_soon          = EXCLUDED.coming_soon,
                price_usd            = EXCLUDED.price_usd,
                is_free              = EXCLUDED.is_free,
                short_desc           = EXCLUDED.short_desc,
                detailed_description = EXCLUDED.detailed_description,
                about_the_game       = EXCLUDED.about_the_game,
                review_count         = EXCLUDED.review_count,
                total_positive       = EXCLUDED.total_positive,
                total_negative       = EXCLUDED.total_negative,
                positive_pct         = EXCLUDED.positive_pct,
                review_score_desc    = EXCLUDED.review_score_desc,
                steamspy_owners      = EXCLUDED.steamspy_owners,
                header_image         = EXCLUDED.header_image,
                background_image     = EXCLUDED.background_image,
                required_age         = EXCLUDED.required_age,
                platforms            = EXCLUDED.platforms,
                supported_languages  = EXCLUDED.supported_languages,
                achievements_total   = EXCLUDED.achievements_total,
                metacritic_score     = EXCLUDED.metacritic_score,
                crawled_at           = NOW(),
                data_source          = EXCLUDED.data_source
            """,
            game_row,
        )

        # --- tags (SteamSpy format: {"Tag Name": vote_count, ...}) ---
        for tag_name, votes in tags.items():
            tag_slug = _slugify(tag_name) or tag_name.lower()[:50]
            cur.execute(
                """
                INSERT INTO tags (name, slug) VALUES (%s, %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (tag_name, tag_slug),
            )
            cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    INSERT INTO game_tags (appid, tag_id, votes) VALUES (%s, %s, %s)
                    ON CONFLICT (appid, tag_id) DO UPDATE SET votes = EXCLUDED.votes
                    """,
                    (appid, row[0], int(votes)),
                )

        # --- genres (Steam API format: [{"id": "1", "description": "Action"}, ...]) ---
        for genre in genres:
            genre_id = int(genre.get("id") or 0)
            genre_name: str = genre.get("description") or ""
            genre_slug = _slugify(genre_name) or f"genre-{genre_id}"
            if genre_id and genre_name:
                cur.execute(
                    """
                    INSERT INTO genres (id, name, slug) VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, slug = EXCLUDED.slug
                    """,
                    (genre_id, genre_name, genre_slug),
                )
                cur.execute(
                    """
                    INSERT INTO game_genres (appid, genre_id) VALUES (%s, %s)
                    ON CONFLICT (appid, genre_id) DO NOTHING
                    """,
                    (appid, genre_id),
                )

        # --- categories (Steam API format: [{"id": 2, "description": "Multi-player"}, ...]) ---
        for cat in categories:
            cat_id = int(cat.get("id") or 0)
            cat_name: str = cat.get("description") or ""
            if cat_id and cat_name:
                cur.execute(
                    """
                    INSERT INTO game_categories (appid, category_id, category_name)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (appid, category_id) DO UPDATE
                        SET category_name = EXCLUDED.category_name
                    """,
                    (appid, cat_id, cat_name),
                )

    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handler(event: dict, context: object) -> dict:
    """SQS-triggered Lambda. Each record body: {"appid": <int>}"""

    async def _run() -> dict:
        db_url = _get_db_url()
        conn = psycopg2.connect(db_url)
        success = failure = 0
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                steam = DirectSteamSource(client)
                for record in event.get("Records", []):
                    try:
                        body = json.loads(record["body"])
                        appid = int(body["appid"])
                    except (KeyError, ValueError, json.JSONDecodeError) as exc:
                        logger.error("Bad SQS message body=%r error=%s", record.get("body"), exc)
                        failure += 1
                        continue
                    ok = await crawl_app(appid, steam, conn)
                    if ok:
                        success += 1
                    else:
                        failure += 1
        finally:
            conn.close()
        return {"success": success, "failure": failure}

    return asyncio.run(_run())
