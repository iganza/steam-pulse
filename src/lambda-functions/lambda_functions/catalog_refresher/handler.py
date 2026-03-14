"""Lambda handler — refreshes the full Steam app catalog.

Triggered by EventBridge schedule (weekly). On each run:
1. Calls GetAppList/v2 to fetch all Steam appids (~170k).
2. Bulk-upserts new entries into app_catalog (status=pending).
   Existing rows are NOT overwritten — only new appids are inserted.
3. Enqueues all pending appids onto app-crawl-queue in batches of 10.

This means every week any newly released game is discovered and crawled.
"""

import json
import os

import httpx
import psycopg2
import psycopg2.extras
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger(service="catalog-refresher")
tracer = Tracer(service="catalog-refresher")
metrics = Metrics(namespace="SteamPulse", service="catalog-refresher")

APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
STEAM_API_KEY_ENV = "STEAM_API_KEY"

APP_CRAWL_QUEUE_URL_ENV = "APP_CRAWL_QUEUE_URL"
DB_SECRET_ARN_ENV = "DB_SECRET_ARN"

# SQS send_message_batch limit
SQS_BATCH_SIZE = 10


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_conn: "psycopg2.connection | None" = None  # type: ignore[name-defined]


def _get_db_url() -> str:
    secret_arn = os.environ[DB_SECRET_ARN_ENV]
    import boto3  # type: ignore[import-untyped]
    sm = boto3.client("secretsmanager")
    secret = json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])
    host = secret["host"]
    port = secret.get("port", 5432)
    dbname = secret.get("dbname", "steampulse")
    user = secret["username"]
    password = secret["password"]
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _get_conn() -> "psycopg2.connection":  # type: ignore[name-defined]
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(_get_db_url())
    return _conn


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
        sqs.send_message_batch(QueueUrl=queue_url, Entries=entries)
        total += len(batch)

    return total


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    """EventBridge-scheduled Lambda. Refreshes app_catalog and enqueues pending crawls."""
    queue_url = os.environ[APP_CRAWL_QUEUE_URL_ENV]

    with httpx.Client() as client:
        apps = fetch_app_list(client, api_key=os.environ.get(STEAM_API_KEY_ENV))

    logger.info("Fetched %d apps from Steam GetAppList", len(apps))
    metrics.add_metric(name="AppListSize", unit=MetricUnit.Count, value=len(apps))

    conn = _get_conn()
    new_rows = upsert_catalog(conn, apps)
    logger.info("Inserted %d new appids into app_catalog", new_rows)
    metrics.add_metric(name="NewAppsDiscovered", unit=MetricUnit.Count, value=new_rows)

    enqueued = enqueue_pending(conn, queue_url)
    logger.info("Enqueued %d pending appids for crawl", enqueued)
    metrics.add_metric(name="AppsCrawlEnqueued", unit=MetricUnit.Count, value=enqueued)

    return {"apps_fetched": len(apps), "new_rows": new_rows, "enqueued": enqueued}
