"""Lambda handler — crawls app metadata from Steam and upserts to DB.

Triggered by SQS app-crawl-queue. Each message body: {"appid": <int>}
Writes to: games, tags, game_tags, genres, game_genres, game_categories.
After upsert, queues appid to review-crawl-queue if new reviews since last
crawl exceed the tiered delta threshold (_reanalysis_threshold).
"""

import asyncio
import json
import os
import re
from datetime import date, datetime

import httpx
import psycopg2
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.typing import LambdaContext

from library_layer.steam_source import DirectSteamSource, SteamAPIError

logger = Logger(service="app-crawler")
tracer = Tracer(service="app-crawler")
metrics = Metrics(namespace="SteamPulse", service="app-crawler")
processor = BatchProcessor(event_type=EventType.SQS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


REVIEW_QUEUE_ENV = "REVIEW_CRAWL_QUEUE_URL"


def _reanalysis_threshold(total_reviews: int) -> int:
    """New reviews needed since last crawl to trigger re-analysis."""
    if total_reviews < 200:
        return 25
    elif total_reviews < 2_000:
        return 150
    elif total_reviews < 20_000:
        return 500
    elif total_reviews < 200_000:
        return 2_000
    else:
        return 10_000


def _queue_for_review_crawl(appid: int) -> None:
    """Send appid to review-crawl-queue if REVIEW_CRAWL_QUEUE_URL is set."""
    queue_url = os.getenv(REVIEW_QUEUE_ENV)
    if not queue_url:
        logger.info("No %s set — skipping review-crawl queue for appid=%s", REVIEW_QUEUE_ENV, appid)
        return
    import boto3  # type: ignore[import-untyped]
    sqs = boto3.client("sqs")
    sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps({"appid": appid}))
    logger.info("Queued appid=%s to review-crawl-queue", appid)


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
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_catalog (appid, name, meta_status)
                VALUES (%s, %s, 'failed')
                ON CONFLICT (appid) DO UPDATE SET meta_status = 'failed', meta_crawled_at = NOW()
                """,
                (appid, f"App {appid}"),
            )
        conn.commit()
        return False

    if not details:
        logger.info("appid=%s not found on Steam — skipping", appid)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_catalog (appid, name, meta_status)
                VALUES (%s, %s, 'skipped')
                ON CONFLICT (appid) DO UPDATE SET meta_status = 'skipped', meta_crawled_at = NOW()
                """,
                (appid, f"App {appid}"),
            )
        conn.commit()
        return False

    # Review counts from Steam reviews API query_summary
    summary = await steam.get_review_summary(appid)
    total_positive: int = int(summary.get("total_positive") or 0)
    total_negative: int = int(summary.get("total_negative") or 0)
    total_reviews = total_positive + total_negative
    positive_pct: int | None = (
        round(total_positive / total_reviews * 100) if total_reviews > 0 else None
    )
    review_score_desc: str = summary.get("review_score_desc", "") or ""

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

    genres: list[dict] = details.get("genres") or []
    categories: list[dict] = details.get("categories") or []

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
        "total_positive": total_positive,
        "total_negative": total_negative,
        "positive_pct": positive_pct,
        "review_score_desc": review_score_desc,
        "header_image": details.get("header_image") or "",
        "background_image": details.get("background") or "",
        "required_age": int(details.get("required_age") or 0),
        "platforms": json.dumps(details.get("platforms") or {}),
        "supported_languages": details.get("supported_languages") or "",
        "achievements_total": achievements_total,
        "metacritic_score": metacritic_score,
        "data_source": "steam_direct",
    }

    logger.info(
        "appid=%s name=%r — genres=%d categories=%d reviews=%d",
        appid, name, len(genres), len(categories), total_reviews,
    )

    if dry_run:
        return True

    # Read old review_count before upsert to compute delta
    with conn.cursor() as cur:
        cur.execute("SELECT review_count FROM games WHERE appid = %s", (appid,))
        row = cur.fetchone()
    old_review_count: int = int(row[0]) if row and row[0] is not None else 0

    with conn.cursor() as cur:
        # --- games ---
        cur.execute(
            """
            INSERT INTO games (
                appid, name, slug, type, developer, publisher, developers, publishers,
                website, release_date, coming_soon, price_usd, is_free,
                short_desc, detailed_description, about_the_game,
                review_count, total_positive, total_negative, positive_pct,
                review_score_desc, header_image, background_image,
                required_age, platforms, supported_languages,
                achievements_total, metacritic_score, crawled_at, data_source
            ) VALUES (
                %(appid)s, %(name)s, %(slug)s, %(type)s, %(developer)s, %(publisher)s,
                %(developers)s, %(publishers)s,
                %(website)s, %(release_date)s, %(coming_soon)s, %(price_usd)s, %(is_free)s,
                %(short_desc)s, %(detailed_description)s, %(about_the_game)s,
                %(review_count)s, %(total_positive)s, %(total_negative)s, %(positive_pct)s,
                %(review_score_desc)s, %(header_image)s,
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

        # --- tags: genres + categories stored with vote_count=0 ---
        tag_items = genres + categories
        for item in tag_items:
            tag_name = item.get("description") or ""
            if not tag_name:
                continue
            tag_slug = _slugify(tag_name) or tag_name.lower()[:50]
            cur.execute(
                """
                INSERT INTO tags (name, slug) VALUES (%s, %s)
                ON CONFLICT (name) DO NOTHING
                """,
                (tag_name, tag_slug),
            )
            cur.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
            tag_row = cur.fetchone()
            if tag_row:
                cur.execute(
                    """
                    INSERT INTO game_tags (appid, tag_id, votes) VALUES (%s, %s, %s)
                    ON CONFLICT (appid, tag_id) DO UPDATE SET votes = EXCLUDED.votes
                    """,
                    (appid, tag_row[0], 0),
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

    # Update app_catalog crawl tracking
    with conn.cursor() as cur:
        review_status = "pending" if total_reviews >= 500 else "ineligible"
        cur.execute(
            """
            INSERT INTO app_catalog (appid, name, meta_status, meta_crawled_at, review_count, review_status)
            VALUES (%s, %s, 'done', NOW(), %s, %s)
            ON CONFLICT (appid) DO UPDATE SET
                name              = EXCLUDED.name,
                meta_status       = 'done',
                meta_crawled_at   = NOW(),
                review_count      = EXCLUDED.review_count,
                review_status     = CASE
                    WHEN app_catalog.review_status IN ('done', 'failed') THEN app_catalog.review_status
                    ELSE EXCLUDED.review_status
                END
            """,
            (appid, name, total_reviews, review_status),
        )

    conn.commit()

    # Delta-triggered review crawl: queue if new reviews exceed tiered threshold
    delta = total_reviews - old_review_count
    threshold = _reanalysis_threshold(total_reviews)
    if delta >= threshold:
        logger.info(
            "appid=%s delta=%d >= threshold=%d — queuing for review crawl",
            appid, delta, threshold,
        )
        _queue_for_review_crawl(appid)
    else:
        logger.info(
            "appid=%s delta=%d < threshold=%d — skipping review crawl",
            appid, delta, threshold,
        )

    return True


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

# Module-level DB connection — reused across warm invocations
_conn: "psycopg2.connection | None" = None  # type: ignore[name-defined]


def _get_conn() -> "psycopg2.connection":  # type: ignore[name-defined]
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_get_db_url())
    return _conn


def _record_handler(record: dict) -> None:
    """Process a single SQS record. Raises on unexpected failure so BatchProcessor marks it for DLQ.
    Steam API errors (404/500) are logged and skipped — not DLQ'd."""
    body = json.loads(record["body"])
    appid = int(body["appid"])
    logger.append_keys(appid=appid)

    async def _run() -> bool:
        async with httpx.AsyncClient(timeout=30.0) as client:
            steam = DirectSteamSource(client)
            return await crawl_app(appid, steam, _get_conn())

    ok = asyncio.run(_run())
    if ok:
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)
    else:
        logger.warning("crawl_app skipped appid=%s (Steam data unavailable)", appid)


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """SQS-triggered Lambda. Each record body: {"appid": <int>}"""
    return process_partial_response(
        event=event,
        record_handler=_record_handler,
        processor=processor,
        context=context,
    )
