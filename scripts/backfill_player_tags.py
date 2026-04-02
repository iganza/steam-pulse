"""Backfill player tags from SteamSpy into the tags/game_tags tables.

Usage:
  # Test a single game locally (dry run)
  poetry run python scripts/backfill_player_tags.py --appids 440 --dry-run

  # Backfill specific games locally
  poetry run python scripts/backfill_player_tags.py --appids 440,570,730

  # Clear polluted category tags (one-time cleanup)
  poetry run python scripts/backfill_player_tags.py --clear

  # Backfill all games via cloud spoke fan-out
  poetry run python scripts/backfill_player_tags.py --cloud

  # Cloud backfill with limit (for testing)
  poetry run python scripts/backfill_player_tags.py --cloud --limit 100
"""

import argparse
import json
import logging
import os
import random
import signal
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL", "postgresql://steampulse:dev@127.0.0.1:5432/steampulse")
STEAMSPY_API_URL = "https://steamspy.com/api.php"

_interrupted = False


def _on_sigint(sig: int, frame: object) -> None:
    global _interrupted
    _interrupted = True
    logger.info("Ctrl+C received — finishing current batch…")


# ---------------------------------------------------------------------------
# SteamSpy fetch
# ---------------------------------------------------------------------------


def _fetch_steamspy(client: httpx.Client, appid: int) -> dict:
    """Fetch SteamSpy data for a single game. Returns {} on failure."""
    try:
        resp = client.get(STEAMSPY_API_URL, params={"request": "appdetails", "appid": str(appid)})
        resp.raise_for_status()
        data = resp.json()
        if "tags" not in data:
            return {}
        return data
    except Exception as exc:
        logger.warning("SteamSpy fetch failed for %s: %s", appid, exc)
        return {}


# ---------------------------------------------------------------------------
# Local mode
# ---------------------------------------------------------------------------


def _run_local(
    appids: list[int],
    dry_run: bool,
    resume: bool,
) -> None:
    import psycopg2
    import psycopg2.extras
    from library_layer.repositories.steamspy_repo import SteamspyRepository
    from library_layer.repositories.tag_repo import TagRepository

    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    tag_repo = TagRepository(conn)
    steamspy_repo = SteamspyRepository(conn)

    # Resolve game names for logging
    with conn.cursor() as cur:
        cur.execute(
            "SELECT appid, name FROM games WHERE appid = ANY(%s)",
            (appids,),
        )
        names = {row["appid"]: row["name"] for row in cur.fetchall()}

    if resume:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT appid FROM game_tags WHERE appid = ANY(%s)",
                (appids,),
            )
            existing = {row["appid"] for row in cur.fetchall()}
        before = len(appids)
        appids = [a for a in appids if a not in existing]
        logger.info("Resume: skipped %d already-tagged games", before - len(appids))

    total = len(appids)
    logger.info("Backfilling %d games (dry_run=%s)", total, dry_run)

    client = httpx.Client(timeout=30.0)
    total_tags = 0
    batch_count = 0

    for i, appid in enumerate(appids, 1):
        if _interrupted:
            logger.info("Interrupted at game %d/%d", i, total)
            break

        game_name = names.get(appid, "<unknown>")
        raw = _fetch_steamspy(client, appid)

        if not raw:
            logger.info("[%d/%d] %s (%s): no SteamSpy data", i, total, appid, game_name)
            time.sleep(0.25 + random.uniform(-0.05, 0.05))
            continue

        tags_dict: dict = raw.get("tags") or {}
        tags = [{"name": k, "votes": int(v)} for k, v in tags_dict.items()]

        steamspy_fields = (
            "score_rank",
            "positive",
            "negative",
            "userscore",
            "owners",
            "average_forever",
            "average_2weeks",
            "median_forever",
            "median_2weeks",
            "price",
            "initialprice",
            "discount",
            "ccu",
            "languages",
        )
        steamspy_payload = {k: raw[k] for k in steamspy_fields if k in raw}

        if dry_run:
            tag_names = [t["name"] for t in tags[:5]]
            logger.info(
                "[%d/%d] %s (%s): %d tags %s",
                i,
                total,
                appid,
                game_name,
                len(tags),
                tag_names,
            )
        else:
            if tags:
                tag_repo.upsert_tags(
                    [{"appid": appid, "name": t["name"], "votes": t["votes"]} for t in tags]
                )
            if steamspy_payload:
                steamspy_repo.upsert(appid, steamspy_payload)

            batch_count += 1
            if batch_count >= 50:
                conn.commit()
                batch_count = 0

            logger.info("[%d/%d] %s (%s): %d tags", i, total, appid, game_name, len(tags))

        total_tags += len(tags)
        time.sleep(0.25 + random.uniform(-0.05, 0.05))

    if not dry_run:
        conn.commit()

    client.close()
    conn.close()
    logger.info("Done. Total tags written: %d", total_tags)


# ---------------------------------------------------------------------------
# Clear mode
# ---------------------------------------------------------------------------


def _run_clear() -> None:
    import psycopg2

    conn = psycopg2.connect(DB_URL)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE game_tags")
        cur.execute("DELETE FROM tags")
    conn.commit()
    conn.close()
    logger.info("Cleared all tags and game_tags rows")


# ---------------------------------------------------------------------------
# Cloud mode
# ---------------------------------------------------------------------------


def _run_cloud(limit: int | None) -> None:
    import boto3

    env = os.getenv("ENVIRONMENT", "staging")

    # Find crawler Lambda by convention
    lambda_client = boto3.client("lambda")

    # List functions matching pattern
    fn_name = f"SteamPulse-{env.title()}"
    paginator = lambda_client.get_paginator("list_functions")
    crawler_fn = None
    for page in paginator.paginate():
        for fn in page["Functions"]:
            if "Crawler" in fn["FunctionName"] and fn_name in fn["FunctionName"]:
                # Skip spoke/ingest functions
                if "Spoke" not in fn["FunctionName"] and "Ingest" not in fn["FunctionName"]:
                    crawler_fn = fn["FunctionName"]
                    break
        if crawler_fn:
            break

    if not crawler_fn:
        logger.error("Could not find crawler Lambda function matching %s", fn_name)
        sys.exit(1)

    payload = {"action": "backfill_tags"}
    if limit:
        payload["limit"] = limit

    logger.info("Invoking %s with payload: %s", crawler_fn, payload)
    resp = lambda_client.invoke(
        FunctionName=crawler_fn,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    result = json.loads(resp["Payload"].read())
    logger.info("Result: %s", result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="backfill_player_tags",
        description="Backfill player tags from SteamSpy into tags/game_tags",
    )
    p.add_argument("--appids", type=str, help="Comma-separated appids for local mode")
    p.add_argument("--cloud", action="store_true", help="Invoke crawler Lambda for spoke fan-out")
    p.add_argument("--clear", action="store_true", help="Truncate game_tags + delete tags")
    p.add_argument(
        "--dry-run", action="store_true", help="Fetch from SteamSpy but don't write to DB"
    )
    p.add_argument("--resume", action="store_true", help="Skip appids already in game_tags")
    p.add_argument("--limit", type=int, default=None, help="Cap number of games (cloud mode)")
    return p


def main() -> None:
    signal.signal(signal.SIGINT, _on_sigint)
    args = _build_parser().parse_args()

    if args.clear:
        _run_clear()
        return

    if args.cloud:
        _run_cloud(args.limit)
        return

    if not args.appids:
        logger.error("Provide --appids (local mode) or --cloud (spoke fan-out)")
        sys.exit(1)

    appids = [int(a.strip()) for a in args.appids.split(",")]
    _run_local(appids, dry_run=args.dry_run, resume=args.resume)


if __name__ == "__main__":
    main()
