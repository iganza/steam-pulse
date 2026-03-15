"""Catalog refresh logic — refreshes the full Steam app catalog.

On each run:
1. Calls GetAppList/v2 to fetch all Steam appids (~170k).
2. Bulk-upserts new entries into app_catalog (status=pending).
   Existing rows are NOT overwritten — only new appids are inserted.
3. Enqueues all pending appids onto app-crawl-queue in batches of 10.

This means every week any newly released game is discovered and crawled.
"""
from __future__ import annotations

import json
import os

import httpx
import psycopg2
import psycopg2.extras
from aws_lambda_powertools import Logger

logger = Logger(service="crawler")

APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
STEAM_API_KEY_SECRET_ARN_ENV = "STEAM_API_KEY_SECRET_ARN"
APP_CRAWL_QUEUE_URL_ENV = "APP_CRAWL_QUEUE_URL"

SQS_BATCH_SIZE = 10

_steam_api_key: str | None = None


def _get_steam_api_key() -> str:
    global _steam_api_key
    if _steam_api_key is None:
        import boto3  # type: ignore[import-untyped]
        secret_arn = os.environ[STEAM_API_KEY_SECRET_ARN_ENV]
        sm = boto3.client("secretsmanager")
        _steam_api_key = sm.get_secret_value(SecretId=secret_arn)["SecretString"]
    return _steam_api_key


# ---------------------------------------------------------------------------
# Core logic (importable for testing)
# ---------------------------------------------------------------------------


def fetch_app_list(client: httpx.Client, api_key: str | None = None) -> list[dict]:
    """Returns [{appid, name}, ...] from IStoreService/GetAppList (cursor-paginated)."""
    if not api_key:
        raise ValueError("STEAM_API_KEY is required for IStoreService/GetAppList/v1/")

    apps: list[dict] = []
    last_appid: int | None = None

    while True:
        params: dict = {"key": api_key, "max_results": 50000, "include_games": 1}
        if last_appid is not None:
            params["last_appid"] = last_appid

        resp = client.get(APP_LIST_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("response", {})

        batch = data.get("apps", [])
        apps.extend({"appid": a["appid"], "name": a.get("name", "")} for a in batch)

        if not data.get("have_more_results"):
            break
        last_appid = data.get("last_appid")

    return apps


def upsert_catalog(conn: "psycopg2.connection", apps: list[dict]) -> int:  # type: ignore[name-defined]
    """Inserts new appids into app_catalog; skips existing rows. Returns count of new rows."""
    if not apps:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO app_catalog (appid, name)
            VALUES %s
            ON CONFLICT (appid) DO NOTHING
            """,
            [(a["appid"], (a.get("name") or f"App {a['appid']}")[:500]) for a in apps],
            page_size=1000,
        )
        new_rows = cur.rowcount
    conn.commit()
    return new_rows


def enqueue_pending(conn: "psycopg2.connection", queue_url: str) -> int:  # type: ignore[name-defined]
    """Sends all pending appids to app-crawl-queue. Returns total enqueued."""
    import boto3  # type: ignore[import-untyped]
    sqs = boto3.client("sqs")

    with conn.cursor() as cur:
        cur.execute("SELECT appid FROM app_catalog WHERE meta_status = 'pending'")
        pending = [row[0] for row in cur.fetchall()]

    if not pending:
        logger.info("No pending appids to enqueue")
        return 0

    total = 0
    for i in range(0, len(pending), SQS_BATCH_SIZE):
        batch = pending[i : i + SQS_BATCH_SIZE]
        entries = [
            {"Id": str(appid), "MessageBody": json.dumps({"appid": appid})}
            for appid in batch
        ]
        resp = sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        if resp.get("Failed"):
            failed_ids = [f["Id"] for f in resp["Failed"]]
            raise RuntimeError(f"SQS batch had {len(failed_ids)} failed messages: {failed_ids}")
        total += len(batch)

    return total


# ---------------------------------------------------------------------------
# Dispatcher entry point
# ---------------------------------------------------------------------------


def run(conn: "psycopg2.connection", context) -> dict:  # type: ignore[name-defined]
    queue_url = os.environ[APP_CRAWL_QUEUE_URL_ENV]
    with httpx.Client() as client:
        apps = fetch_app_list(client, api_key=_get_steam_api_key())
    new_rows = upsert_catalog(conn, apps)
    enqueued = enqueue_pending(conn, queue_url)
    return {"apps_fetched": len(apps), "new_rows": new_rows, "enqueued": enqueued}
