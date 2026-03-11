"""PostgreSQL connection and upsert helpers for the V2 crawler (Lambda environment)."""

import json
import os
from typing import Optional

import psycopg2
import psycopg2.extras


def get_connection():
    """Return a psycopg2 connection using DATABASE_URL from environment."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(db_url)


def upsert_game(conn, appid: int, data: dict) -> None:
    """Upsert a game record into the games table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO games (
                appid, name, type, release_date, price_usd, is_free,
                metacritic_score, total_positive, total_negative,
                review_score_desc, short_description, developers,
                publishers, platforms, last_crawled
            ) VALUES (
                %(appid)s, %(name)s, %(type)s, %(release_date)s,
                %(price_usd)s, %(is_free)s, %(metacritic_score)s,
                %(total_positive)s, %(total_negative)s,
                %(review_score_desc)s, %(short_description)s,
                %(developers)s, %(publishers)s, %(platforms)s, NOW()
            )
            ON CONFLICT (appid) DO UPDATE SET
                name               = EXCLUDED.name,
                type               = EXCLUDED.type,
                release_date       = EXCLUDED.release_date,
                price_usd          = EXCLUDED.price_usd,
                is_free            = EXCLUDED.is_free,
                metacritic_score   = EXCLUDED.metacritic_score,
                total_positive     = EXCLUDED.total_positive,
                total_negative     = EXCLUDED.total_negative,
                review_score_desc  = EXCLUDED.review_score_desc,
                short_description  = EXCLUDED.short_description,
                developers         = EXCLUDED.developers,
                publishers         = EXCLUDED.publishers,
                platforms          = EXCLUDED.platforms,
                last_crawled       = NOW()
            """,
            {
                **data,
                "platforms": json.dumps(data.get("platforms", {})),
                "developers": data.get("developers", []),
                "publishers": data.get("publishers", []),
            },
        )


def upsert_tags(conn, appid: int, tags: list[str]) -> None:
    """Upsert tags for a game, replacing existing ones."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM game_tags WHERE appid = %s", (appid,))
        if tags:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO game_tags (appid, tag) VALUES %s ON CONFLICT DO NOTHING",
                [(appid, tag) for tag in tags],
            )


def upsert_genres(conn, appid: int, genres: list[str]) -> None:
    """Upsert genres for a game, replacing existing ones."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM game_genres WHERE appid = %s", (appid,))
        if genres:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO game_genres (appid, genre) VALUES %s ON CONFLICT DO NOTHING",
                [(appid, genre) for genre in genres],
            )


def upsert_categories(conn, appid: int, categories: list[str]) -> None:
    """Upsert categories for a game, replacing existing ones."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM game_categories WHERE appid = %s", (appid,))
        if categories:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO game_categories (appid, category) VALUES %s ON CONFLICT DO NOTHING",
                [(appid, cat) for cat in categories],
            )
