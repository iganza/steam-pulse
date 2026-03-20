# CrawlSpokeStack — Multi-Region General-Purpose Crawler

**Prerequisite:** Run `cdk-lambda-env-refactor.md` first — it adds
`config.to_lambda_env()` which this prompt uses for Lambda environment dicts.

## Goal

Deploy lightweight "spoke" crawl stacks to additional AWS regions to multiply
Steam API throughput. Steam rate-limits per IP; each region provides distinct
NAT IPs. One spoke Lambda handles **all crawl work types** (metadata AND
reviews) by subscribing to all crawl queues.

**Architecture: hub-and-spoke with S3 handoff.**
- **Spoke Lambda:** Fetches from Steam → writes raw data to S3 → notifies primary via SQS
- **Primary Ingest Lambda:** Reads S3 → routes by task type → writes to RDS (no downstream triggers)

Spokes have **zero DB access**. No RDS Proxy, no VPC peering, no public DB.

---

## Pre-requisite: Fix Bucket Config Inconsistency

Before implementing spokes, fix a bug: the crawler Lambda has no S3 bucket,
so `_archive_to_s3()` is silently a no-op in production.

**Root cause:** `SteamPulseConfig` has two bucket fields pointing to the same
physical bucket with different names — `ASSETS_BUCKET_PARAM_NAME` (required, set by
CDK) and `ARCHIVE_BUCKET` (optional, default `""`, never set by CDK). The
crawler reads `ARCHIVE_BUCKET` which is always empty.

**Fix — three files:**

### `src/library-layer/library_layer/config.py`

Remove `ARCHIVE_BUCKET`. `ASSETS_BUCKET_PARAM_NAME` is the one source of truth:

```python
# REMOVE this line:
ARCHIVE_BUCKET: str = ""  # empty means archival disabled

# ASSETS_BUCKET_PARAM_NAME already exists — keep it as-is:
ASSETS_BUCKET_PARAM_NAME: str
```

### `src/lambda-functions/lambda_functions/crawler/handler.py`

Update the `CrawlService` instantiation to use `ASSETS_BUCKET_PARAM_NAME`:

```python
# Change:
archive_bucket=_crawler_config.ARCHIVE_BUCKET,
# To:
archive_bucket=_crawler_config.ASSETS_BUCKET_PARAM_NAME,
```

### `infra/stacks/compute_stack.py`

Add `ASSETS_BUCKET_PARAM_NAME` to the crawler Lambda's environment (it's currently
missing — the loader Lambda has it but the crawler does not).

**Note:** This prompt assumes `cdk-lambda-env-refactor.md` has already been
run, so `config.to_lambda_env()` exists and all infrastructure ARNs/URLs are
SSM-backed. The crawler env becomes:

```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

Also grant the crawler role S3 write access (currently missing):
```python
# After existing grants (grant_send_messages, grant_publish):
assets_bucket.grant_read_write(crawler_role)
```

After this fix, every Lambda reads `config.ASSETS_BUCKET_PARAM_NAME` — one name,
one bucket, consistent everywhere.

---

## Symmetric Design

**Every region is a spoke.** The primary region (us-west-2) also runs a spoke
Lambda. Nobody writes to DB directly from a crawl. There are three distinct
Lambda roles:

```
┌─────────────────────────────────────────────────────────────────┐
│  CONTROL PLANE (handler.py — VPC, DB)                          │
│    EventBridge scheduled → CatalogService.refresh()            │
│      → reads DB → publishes appids to app_crawl_queue          │
│    Direct invocation → one-off crawl (manual ops only)         │
│    CrawlService._enqueue_review_crawl() → review_crawl_queue  │
└─────────────────────────────────────────────────────────────────┘
         ↓ publishes work to queues
┌─────────────────────────────────────────────────────────────────┐
│  SPOKE NODES (spoke_handler.py — NO VPC, NO DB, ALL regions)   │
│    us-west-2 spoke ─┐                                          │
│    us-east-1 spoke ─┤─ all compete for queue messages           │
│    eu-west-1 spoke ─┘                                          │
│                                                                 │
│    Poll app_crawl_queue → fetch metadata → S3 → results queue  │
│    Poll review_crawl_queue → fetch reviews → S3 → results queue│
└─────────────────────────────────────────────────────────────────┘
         ↓ results arrive at spoke_results_queue
┌─────────────────────────────────────────────────────────────────┐
│  INGEST (ingest_handler.py — VPC, DB, primary region only)     │
│    Single DB writer — reads S3, routes by task type:            │
│    metadata → crawl_service.ingest_spoke_metadata() → RDS      │
│    reviews  → crawl_service.ingest_spoke_reviews()  → RDS      │
│    DB writes only — no SNS, no Step Functions, no triggers      │
└─────────────────────────────────────────────────────────────────┘
```

**Key insight:** `handler.py` loses its SQS event sources. It no longer
processes `app_crawl_queue` or `review_crawl_queue` directly. Those queues
are consumed exclusively by spoke nodes (including the primary-region spoke).
`handler.py` becomes pure control plane: EventBridge + direct invocations.

**Benefits:**
- Single code path for all crawl data — spoke_handler.py runs everywhere
- IngestFn is the **only** Lambda that writes crawl data to RDS
- Primary spoke comes **out of the VPC** — faster cold starts
- If DB goes down, data sits safely in S3/SQS until it recovers
- Adding a spoke to any region is just a CDK deploy — no code changes

SQS delivers each message to exactly one consumer. Spokes compete for messages
— no coordination needed. More spokes = more throughput.

**S3 for everything:** metadata payloads can exceed 256KB (long HTML
descriptions), so both task types use the same S3 handoff. Simpler, consistent.

---

## Scaling Math

| Active nodes           | Total concurrency | ~Time for 500-game review crawl |
|------------------------|-------------------|---------------------------------|
| 1 (primary spoke only) | 3                 | 7 days                          |
| +2 remote spokes       | 9                 | ~2.5 days                       |
| +4 remote spokes       | 15                | ~1.5 days                       |
| +6 remote spokes       | 21                | ~1 day                          |

Spokes cost **~$0 when idle** — Lambda, SQS, and S3 are pay-per-use.
Full 500-game review crawl across 6 spokes costs ~$1.

---

## Files to Create / Modify

### 1. `src/library-layer/library_layer/services/crawl_service.py` (REFACTOR)

**Refactor `crawl_app()` to extract the DB-write half** so the ingest Lambda
can write pre-fetched metadata without duplicating logic.

Add three things:

#### a) Extract `_ingest_app_data()` private method

Move everything after the `if dry_run: return True` check in `crawl_app()`
into a new private method:

```python
def _ingest_app_data(
    self,
    appid: int,
    details: dict,
    summary: dict,
    deck_compat: dict | None,
) -> bool:
    """Write pre-fetched Steam app data to DB.

    Called by crawl_app() and ingest_spoke_metadata().
    Contains everything that was after `if dry_run` in crawl_app():
    game_data dict, upsert game, upsert tags, update catalog status,
    archive to S3, and review enqueue logic.

    NOTE: Do NOT trigger SNS events or Step Functions from here.
    The spoke ingest path is pure DB write. LLM analysis is kicked
    off by a separate scheduled process.
    """
    # (Move existing body here — game_data dict, upsert, tags, catalog status,
    #  archive, review enqueue logic. Strip out SNS publish + SFN trigger calls.)
    ...
    return True
```

Then `crawl_app()` becomes:

```python
async def crawl_app(self, appid: int, dry_run: bool = False) -> bool:
    # ... existing Steam fetch code (unchanged) ...
    self._archive_to_s3(f"app-details/{appid}/{date.today().isoformat()}.json.gz", details)
    if dry_run:
        return True
    return self._ingest_app_data(appid, details, summary, deck_compat)
```

#### b) Add `ingest_spoke_metadata()` method

```python
async def ingest_spoke_metadata(self, appid: int, raw: dict) -> bool:
    """Ingest metadata fetched by a spoke Lambda.

    Args:
        appid: Steam app ID
        raw: dict with keys "details", "summary", "deck_compat"
    """
    details: dict = raw.get("details") or {}
    summary: dict = raw.get("summary") or {}
    deck_compat: dict | None = raw.get("deck_compat")

    if not details:
        logger.warning("ingest_spoke_metadata: empty details for appid=%s", appid)
        return False

    return self._ingest_app_data(appid, details, summary, deck_compat)
```

#### c) Add `ingest_spoke_reviews()` method

```python
async def ingest_spoke_reviews(self, appid: int, raw_reviews: list[dict]) -> int:
    """Ingest reviews fetched by a spoke Lambda.

    DB write only — no SNS events, no Step Functions trigger.
    LLM analysis is kicked off by a separate scheduled process.

    Returns:
        Number of reviews upserted.
    """
    if not raw_reviews:
        return 0

    self._game_repo.ensure_stub(appid)

    # Build upsert rows — same logic as crawl_reviews()
    reviews_to_upsert = []
    for r in raw_reviews:
        ts = r.get("timestamp_created")
        steam_id = f"{ts}_{appid}"
        posted_at = None
        if ts:
            try:
                posted_at = unix_to_datetime(int(ts))
            except (ValueError, OSError):
                pass
        playtime_minutes = int(r.get("playtime_at_review") or 0)
        reviews_to_upsert.append({
            "appid": appid,
            "steam_review_id": steam_id,
            "author_steamid": r.get("author_steamid", ""),
            "voted_up": bool(r.get("voted_up", False)),
            "playtime_hours": playtime_minutes // 60,
            "body": r.get("review_text", ""),
            "posted_at": posted_at,
            "language": r.get("language", ""),
            "votes_helpful": int(r.get("votes_helpful") or 0),
            "votes_funny": int(r.get("votes_funny") or 0),
            "written_during_early_access": bool(r.get("written_during_early_access", False)),
            "received_for_free": bool(r.get("received_for_free", False)),
        })

    upserted = self._review_repo.bulk_upsert(reviews_to_upsert)
    logger.info("Ingested %d spoke reviews for appid=%s", upserted, appid)

    return upserted
```

---

### 2. `src/lambda-functions/lambda_functions/crawler/handler.py` (MODIFY)

**Slim handler.py to pure control plane.** Remove SQS event sources — those
are now handled by spoke nodes exclusively.

**Remove these functions:**
- `_app_crawl_record()`
- `_review_crawl_record()`
- `app_crawl_processor` and `review_crawl_processor` `BatchProcessor` instances

**Remove SQS routing** from `handler()`. The `if "Records" in event:` block
goes away entirely. After this, handler.py only handles:
1. EventBridge scheduled → `CatalogService.refresh()`
2. Direct invocation → `CrawlService.crawl_app()`, `.crawl_reviews()`

**Important:** direct invocations still call `crawl_app()` / `crawl_reviews()`
which do Steam fetch → DB write directly. This is fine for manual ops / one-off
debugging. The queue-driven path (production) goes through spokes + ingest.

The slimmed handler:

```python
@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    # 1. EventBridge scheduled trigger
    if event.get("source") == "aws.events":
        logger.info("EventBridge trigger — running catalog refresh")
        result = _catalog_service.refresh()
        metrics.add_metric(name="CatalogRefreshRun", unit=MetricUnit.Count, value=1)
        return result

    # 2. Direct invocation (from web Lambda or manual)
    if "action" in event:
        try:
            req = _direct_adapter.validate_python(event)
        except ValidationError as exc:
            logger.error("Invalid direct invocation payload: %s", exc)
            raise
        logger.info("Direct invocation: action=%s", event["action"])
        match req:
            case CrawlAppsRequest():
                ok = asyncio.run(_crawl_service.crawl_app(req.appid))
                return {"appid": req.appid, "success": ok}
            case CrawlReviewsRequest():
                n = asyncio.run(
                    _crawl_service.crawl_reviews(req.appid, max_reviews=req.max_reviews)
                )
                return {"appid": req.appid, "reviews_upserted": n}
            case CatalogRefreshRequest():
                return _catalog_service.refresh()

    raise ValueError(f"Unrecognised event shape: {list(event.keys())}")
```

**Also clean up unused imports** after removing BatchProcessor, EventType,
process_partial_response (unless _extract_payload is used elsewhere — check).

---

### 3. `src/lambda-functions/lambda_functions/crawler/spoke_handler.py` (NEW)

General-purpose spoke handler — runs in **all regions including primary.**
No VPC, no DB imports, routes on queue ARN.
Follows the same Powertools + `process_partial_response` pattern as `handler.py`.

```python
"""Spoke crawler — fetch from Steam, hand off to primary via S3 + SQS.

No DB access. Task type inferred from which SQS queue triggered the Lambda.
Routing (same pattern as primary handler.py):
  "app-crawl" or "metadata" in eventSourceARN → task = metadata
  "review-crawl" in eventSourceARN             → task = reviews

All payloads written to S3 (consistent, handles large metadata HTML).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os

import boto3
import httpx
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.typing import LambdaContext

from library_layer.config import SteamPulseConfig
from library_layer.steam_source import DirectSteamSource, SteamAPIError

logger = Logger(service="crawler-spoke")
tracer = Tracer(service="crawler-spoke")
metrics = Metrics(namespace="SteamPulse", service="crawler-spoke")

app_crawl_processor = BatchProcessor(event_type=EventType.SQS)
review_crawl_processor = BatchProcessor(event_type=EventType.SQS)

_config = SteamPulseConfig()
_PRIMARY_REGION = os.environ["PRIMARY_REGION"]
_SPOKE_RESULTS_QUEUE_URL = os.environ["SPOKE_RESULTS_QUEUE_URL"]

_http = httpx.AsyncClient(timeout=90.0)
_steam = DirectSteamSource(_http)
_sqs = boto3.client("sqs", region_name=_PRIMARY_REGION)
_s3 = boto3.client("s3")


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    source_arn = event["Records"][0].get("eventSourceARN", "")
    if "review-crawl" in source_arn:
        return process_partial_response(
            event=event,
            record_handler=_review_crawl_record,
            processor=review_crawl_processor,
            context=context,
        )
    if "app-crawl" in source_arn or "metadata" in source_arn:
        return process_partial_response(
            event=event,
            record_handler=_app_crawl_record,
            processor=app_crawl_processor,
            context=context,
        )
    raise ValueError(f"Unrecognised queue ARN: {source_arn}")


def _app_crawl_record(record: dict) -> None:
    body = _extract_payload(record["body"])
    appid = int(body["appid"])
    result = asyncio.run(_process_metadata(appid))
    if result:
        metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)


def _review_crawl_record(record: dict) -> None:
    body = _extract_payload(record["body"])
    appid = int(body["appid"])
    count = asyncio.run(_process_reviews(appid))
    metrics.add_metric(name="ReviewsCrawled", unit=MetricUnit.Count, value=count)


def _extract_payload(record_body: str) -> dict:
    """Unwrap SNS envelope if present, otherwise return plain SQS body."""
    body = json.loads(record_body)
    if "Type" in body and body["Type"] == "Notification":
        return json.loads(body["Message"])
    return body


async def _process_reviews(appid: int) -> int:
    try:
        reviews = await _steam.get_reviews(appid, max_reviews=None)
    except SteamAPIError as exc:
        logger.warning("Steam reviews error appid=%s: %s", appid, exc)
        _notify(appid, task="reviews", s3_key=None, count=0)
        return 0

    if not reviews:
        _notify(appid, task="reviews", s3_key=None, count=0)
        return 0

    s3_key = _write_s3(f"spoke-results/reviews/{appid}.json.gz", reviews)
    _notify(appid, task="reviews", s3_key=s3_key, count=len(reviews))
    return len(reviews)


async def _process_metadata(appid: int) -> bool:
    try:
        details = await _steam.get_app_details(appid)
    except SteamAPIError as exc:
        logger.warning("Steam metadata error appid=%s: %s", appid, exc)
        _notify(appid, task="metadata", s3_key=None, count=0)
        return False

    if not details:
        _notify(appid, task="metadata", s3_key=None, count=0)
        return False

    summary = await _steam.get_review_summary(appid)
    deck_compat = await _steam.get_deck_compatibility(appid)

    payload = {"details": details, "summary": summary, "deck_compat": deck_compat}
    s3_key = _write_s3(f"spoke-results/metadata/{appid}.json.gz", payload)
    _notify(appid, task="metadata", s3_key=s3_key, count=1)
    return True


def _write_s3(key: str, data: dict | list) -> str:
    payload = gzip.compress(json.dumps(data).encode())
    _s3.put_object(Bucket=_config.ASSETS_BUCKET_PARAM_NAME, Key=key, Body=payload)
    logger.info("Wrote %d bytes to s3://%s/%s", len(payload), _config.ASSETS_BUCKET_PARAM_NAME, key)
    return key


def _notify(appid: int, task: str, s3_key: str | None, count: int) -> None:
    _sqs.send_message(
        QueueUrl=_SPOKE_RESULTS_QUEUE_URL,
        MessageBody=json.dumps({
            "appid": appid,
            "task": task,
            "s3_key": s3_key,
            "count": count,
            "spoke_region": os.environ.get("AWS_REGION", "unknown"),
        }),
    )
```

---

### 4. `src/lambda-functions/lambda_functions/crawler/ingest_handler.py` (NEW)

Primary-region ingest handler — routes by `task` field.
Pure DB writer — no SNS, no Step Functions, no downstream triggers.
Follows the same Powertools + `process_partial_response` pattern as `handler.py`.

```python
"""Spoke ingest handler — reads S3, routes to CrawlService, writes to RDS.

Pure data acquisition: fetch from S3 → upsert to DB → done.
LLM analysis is a separate scheduled concern — NOT triggered from here.

Triggered by: spoke_results_queue (SQS, primary region only)
Routes on message["task"]:
  "metadata" → crawl_service.ingest_spoke_metadata()
  "reviews"  → crawl_service.ingest_spoke_reviews()
"""

from __future__ import annotations

import asyncio
import gzip
import json

import boto3
import httpx
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.typing import LambdaContext

from library_layer.config import SteamPulseConfig
from library_layer.repositories.catalog_repo import CatalogRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.review_repo import ReviewRepository
from library_layer.repositories.tag_repo import TagRepository
from library_layer.services.crawl_service import CrawlService
from library_layer.steam_source import DirectSteamSource
from library_layer.utils.db import get_conn

logger = Logger(service="spoke-ingest")
tracer = Tracer(service="spoke-ingest")
metrics = Metrics(namespace="SteamPulse", service="spoke-ingest")

ingest_processor = BatchProcessor(event_type=EventType.SQS)

_conn = get_conn()
_sqs = boto3.client("sqs")
_s3 = boto3.client("s3")
_config = SteamPulseConfig()

_crawl_service = CrawlService(
    game_repo=GameRepository(_conn),
    review_repo=ReviewRepository(_conn),
    catalog_repo=CatalogRepository(_conn),
    tag_repo=TagRepository(_conn),
    steam=DirectSteamSource(httpx.AsyncClient(timeout=60.0)),
    sqs_client=_sqs,
    review_queue_url=_config.REVIEW_CRAWL_QUEUE_PARAM_NAME,
    config=_config,
    s3_client=_s3,
    archive_bucket=_config.ASSETS_BUCKET_PARAM_NAME,
)


@tracer.capture_lambda_handler
@metrics.log_metrics(capture_cold_start_metric=True)
def handler(event: dict, context: LambdaContext) -> dict:
    return process_partial_response(
        event=event,
        record_handler=_ingest_record,
        processor=ingest_processor,
        context=context,
    )


def _ingest_record(record: dict) -> None:
    body = json.loads(record["body"])
    appid = int(body["appid"])
    task: str = body["task"]
    s3_key: str | None = body.get("s3_key")
    count = int(body.get("count", 0))

    if not s3_key or count == 0:
        logger.info("Spoke reported 0 results: task=%s appid=%s", task, appid)
        return

    response = _s3.get_object(Bucket=_config.ASSETS_BUCKET_PARAM_NAME, Key=s3_key)
    data = json.loads(gzip.decompress(response["Body"].read()))

    if task == "metadata":
        success = asyncio.run(_crawl_service.ingest_spoke_metadata(appid, data))
        logger.info("Ingested metadata appid=%s success=%s", appid, success)
        if success:
            metrics.add_metric(name="AppsCrawled", unit=MetricUnit.Count, value=1)
    elif task == "reviews":
        upserted = asyncio.run(_crawl_service.ingest_spoke_reviews(appid, data))
        logger.info("Ingested %d reviews for appid=%s", upserted, appid)
        metrics.add_metric(name="ReviewsUpserted", unit=MetricUnit.Count, value=upserted)
    else:
        raise ValueError(f"Unknown task: {task} for appid={appid}")

    _s3.delete_object(Bucket=_config.ASSETS_BUCKET_PARAM_NAME, Key=s3_key)
```

---

### 5. `infra/stacks/messaging_stack.py` (MODIFY)

Add `spoke_results_queue` with DLQ:

```python
self.spoke_results_dlq = sqs.Queue(
    self, "SpokeResultsDlq",
    retention_period=cdk.Duration.days(14),
)
self.spoke_results_queue = sqs.Queue(
    self, "SpokeResultsQueue",
    visibility_timeout=cdk.Duration.minutes(15),
    dead_letter_queue=sqs.DeadLetterQueue(
        max_receive_count=3,
        queue=self.spoke_results_dlq,
    ),
)
```

Add SSM exports alongside existing queue exports:
```python
ssm.StringParameter(self, "SpokeResultsQueueArnParam",
    parameter_name=f"/steampulse/{env}/messaging/spoke-results-queue-arn",
    string_value=self.spoke_results_queue.queue_arn,
)
ssm.StringParameter(self, "SpokeResultsQueueUrlParam",
    parameter_name=f"/steampulse/{env}/messaging/spoke-results-queue-url",
    string_value=self.spoke_results_queue.queue_url,
)
```

---

### 6. `infra/stacks/compute_stack.py` (MODIFY)

**First: fix the circular dependency.** Currently `assets_bucket` is created in
`DeliveryStack`, which depends on `ComputeStack`. We need the bucket available
in `ComputeStack` too. The fix is to move bucket creation to `DataStack`
(which already manages persistent data resources and deploys before Compute).

**In `infra/stacks/data_stack.py`** — add the S3 bucket:

```python
# After RDS and secrets creation, add:
import aws_cdk.aws_s3 as s3

self.assets_bucket = s3.Bucket(
    self, "AssetsBucket",
    removal_policy=cdk.RemovalPolicy.RETAIN,
    encryption=s3.BucketEncryption.S3_MANAGED,
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
)
ssm.StringParameter(self, "AssetsBucketNameParam",
    parameter_name=f"/steampulse/{env}/data/assets-bucket-name",
    string_value=self.assets_bucket.bucket_name,
)
```

Remove the bucket creation from `DeliveryStack` and `AppStack` — replace with:
```python
# In DeliveryStack / AppStack, receive as parameter instead:
self.assets_bucket = assets_bucket  # passed in from application_stage.py
```

**In `infra/application_stage.py`** — pass the bucket down the chain:
```python
# DeliveryStack and ComputeStack both receive data.assets_bucket
compute = ComputeStack(
    ...
    assets_bucket=data.assets_bucket,   # ADD
    spoke_results_queue=messaging.spoke_results_queue,  # ADD
    ...
)
delivery = DeliveryStack(
    ...
    assets_bucket=data.assets_bucket,   # ADD (replace self-created bucket)
    ...
)
```

**In `ComputeStack.__init__`** — add both new parameters:
```python
def __init__(
    self,
    scope: Construct,
    construct_id: str,
    *,
    config: SteamPulseConfig,
    vpc: ec2.IVpc,
    intra_sg: ec2.ISecurityGroup,
    db_secret: secretsmanager.ISecret,
    app_crawl_queue: sqs.IQueue,
    review_crawl_queue: sqs.IQueue,
    game_events_topic: sns.ITopic,
    content_events_topic: sns.ITopic,
    system_events_topic: sns.ITopic,
    assets_bucket: s3.IBucket,          # ADD
    spoke_results_queue: sqs.IQueue,    # ADD
    **kwargs: object,
) -> None:
```

**Update the crawler Lambda environment** — with SSM-backed config,
infrastructure ARNs come from `.env.staging` via SSM resolution:
```python
environment=config.to_lambda_env(
    POWERTOOLS_SERVICE_NAME="crawler",
    POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
),
```

**Grant S3 access to crawler_role** (currently missing):
```python
assets_bucket.grant_read_write(crawler_role)
```

**Remove SQS event sources from CrawlerFn.** The crawler Lambda no longer
consumes queues directly — spokes handle that. Delete both `add_event_source`
calls (currently around lines 330-343 in compute_stack.py):
```python
# DELETE these two blocks:
# crawler_fn.add_event_source(SqsEventSource(app_crawl_queue, ...))
# crawler_fn.add_event_source(SqsEventSource(review_crawl_queue, ...))
```

**Add ingest Lambda** after the crawler Lambda definition:

```python
ingest_fn = PythonFunction(
    self, "SpokeIngestFn",
    entry="src/lambda-functions",
    index="lambda_functions/crawler/ingest_handler.py",
    handler="handler",
    runtime=lambda_.Runtime.PYTHON_3_12,
    layers=[library_layer],
    role=crawler_role,
    vpc=vpc,
    vpc_subnets=private_subnets,
    security_groups=[intra_sg],
    timeout=cdk.Duration.minutes(15),
    memory_size=256,
    tracing=lambda_.Tracing.ACTIVE,
    log_group=logs.LogGroup(self, "SpokeIngestLogs",
        retention=logs.RetentionDays.ONE_MONTH,
        removal_policy=cdk.RemovalPolicy.DESTROY,
    ),
    environment=config.to_lambda_env(
        POWERTOOLS_SERVICE_NAME="spoke-ingest",
        POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
    ),
)
ingest_fn.add_event_source(
    event_sources.SqsEventSource(
        spoke_results_queue,
        batch_size=1,
        report_batch_item_failures=True,
    )
)
```

---

### 7. `infra/stacks/spoke_stack.py` (NEW)

Minimal spoke — subscribes to **both** crawl queues. No VPC, no DB.

```python
"""CrawlSpokeStack — multi-purpose crawl worker for a remote AWS region.

One Lambda, two event sources (metadata + reviews), reserved concurrency = 3.
No DB access. Connects to public internet (Steam) and cross-region S3/SQS.
"""

import aws_cdk as cdk
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_lambda_event_sources as event_sources
import aws_cdk.aws_logs as logs
import aws_cdk.aws_sqs as sqs
import aws_cdk.aws_ssm as ssm
from aws_cdk.aws_lambda_python_alpha import PythonFunction, PythonLayerVersion
from constructs import Construct


class CrawlSpokeStack(cdk.Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        primary_region: str,
        environment: str,
        app_crawl_queue_arn: str,
        review_crawl_queue_arn: str,
        spoke_results_queue_url: str,
        assets_bucket_name: str,
        steam_api_key_secret_arn: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        spoke_region = cdk.Stack.of(self).region
        account = cdk.Stack.of(self).account

        library_layer = PythonLayerVersion(
            self, "LibraryLayer",
            entry="src/library-layer",
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description=f"SteamPulse shared layer (spoke-{spoke_region})",
        )

        role = iam.Role(
            self, "SpokeCrawlerRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole",
                ),
            ],
        )

        # Cross-region SQS: read both work queues
        role.add_to_policy(iam.PolicyStatement(
            actions=["sqs:ReceiveMessage", "sqs:DeleteMessage",
                     "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"],
            resources=[app_crawl_queue_arn, review_crawl_queue_arn],
        ))

        # Cross-region SQS: write to results queue
        spoke_results_queue_arn = (
            f"arn:aws:sqs:{primary_region}:{account}:SpokeResultsQueue"
        )
        role.add_to_policy(iam.PolicyStatement(
            actions=["sqs:SendMessage"],
            resources=[spoke_results_queue_arn],
        ))

        # Cross-region S3: write results
        role.add_to_policy(iam.PolicyStatement(
            actions=["s3:PutObject"],
            resources=[f"arn:aws:s3:::{assets_bucket_name}/spoke-results/*"],
        ))

        # Cross-region Secrets Manager: Steam API key only
        role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[steam_api_key_secret_arn],
        ))

        crawler_fn = PythonFunction(
            self, "SpokeCrawlerFn",
            entry="src/lambda-functions",
            index="lambda_functions/crawler/spoke_handler.py",
            handler="handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[library_layer],
            role=role,
            timeout=cdk.Duration.minutes(10),
            memory_size=256,
            reserved_concurrent_executions=3,
            tracing=lambda_.Tracing.ACTIVE,
            log_group=logs.LogGroup(self, "SpokeLogs",
                retention=logs.RetentionDays.ONE_MONTH,
                removal_policy=cdk.RemovalPolicy.DESTROY,
            ),
            environment={
                # Spoke Lambda uses inline env — cross-region stack, can't resolve
                # SSM from primary region. _PARAM_NAME fields hold ACTUAL values
                # here (not SSM paths). Spoke handler uses them directly without
                # get_parameter(). config.to_lambda_env() is used for primary-region
                # Lambdas only.
                "ENVIRONMENT": environment,
                "PRIMARY_REGION": primary_region,
                "SPOKE_RESULTS_QUEUE_URL": spoke_results_queue_url,
                "ASSETS_BUCKET_PARAM_NAME": assets_bucket_name,       # actual value
                "STEAM_API_KEY_PARAM_NAME": steam_api_key_secret_arn,  # actual value
                "POWERTOOLS_SERVICE_NAME": f"crawler-spoke-{spoke_region}",
                "POWERTOOLS_METRICS_NAMESPACE": "SteamPulse",
            },
        )

        # Two event sources — one per work type, shared concurrency pool
        for queue_arn, source_id in [
            (app_crawl_queue_arn, "AppCrawlSource"),
            (review_crawl_queue_arn, "ReviewCrawlSource"),
        ]:
            queue = sqs.Queue.from_queue_arn(self, source_id, queue_arn=queue_arn)
            crawler_fn.add_event_source(
                event_sources.SqsEventSource(
                    queue, batch_size=1, report_batch_item_failures=True,
                )
            )

        ssm.StringParameter(
            self, "SpokeStatus",
            parameter_name=f"/steampulse/{environment}/spokes/{spoke_region}/status",
            string_value="active",
        )
```

---

### 8. `infra/application_stage.py` (MODIFY)

Wire spoke stacks after delivery. **Include the primary region as a spoke** —
symmetric design means us-west-2 is also a spoke node.

```python
from infra.stacks.spoke_stack import CrawlSpokeStack

# Symmetric: every region in spoke_region_list is a spoke, including primary
for region in config.spoke_region_list:
    CrawlSpokeStack(
        self, f"Spoke-{region}",
        stack_name=f"SteamPulse-{env_name}-Spoke-{region}",
        primary_region=self.region,
        environment=environment,
        app_crawl_queue_arn=messaging.app_crawl_queue.queue_arn,
        review_crawl_queue_arn=messaging.review_crawl_queue.queue_arn,
        spoke_results_queue_url=messaging.spoke_results_queue.queue_url,
        assets_bucket_name=data.assets_bucket.bucket_name,
        steam_api_key_secret_arn=data.steam_api_key_secret_arn,
        env=cdk.Environment(account=self.account, region=region),
    )
```

**Important:** `SPOKE_REGIONS` should always include the primary region
(e.g., `us-west-2,us-east-1`). The primary region spoke handles its share of
the crawl load just like any other spoke.

---

### 9. `src/library-layer/library_layer/config.py` (MODIFY)

```python
SPOKE_REGIONS: str = ""

@property
def spoke_region_list(self) -> list[str]:
    return [r.strip() for r in self.SPOKE_REGIONS.split(",") if r.strip()]
```

`.env.staging`:
```bash
SPOKE_REGIONS=us-west-2,us-east-1
# SPOKE_REGIONS=us-west-2,us-east-1,eu-west-1,eu-central-1  # add more when ready
```

---

## Deployment Order

```bash
# 1. Deploy messaging (creates spoke_results_queue)
cdk deploy SteamPulse-Staging-Messaging

# 2. Deploy compute (creates ingest Lambda, removes SQS sources from CrawlerFn)
cdk deploy SteamPulse-Staging-Compute

# 3. Set SPOKE_REGIONS=us-west-2,us-east-1 in .env.staging, then:
cdk deploy SteamPulse-Staging-Spoke-us-west-2   # primary spoke
cdk deploy SteamPulse-Staging-Spoke-us-east-1   # first remote spoke

# 4. Test with a metadata message:
aws sqs send-message --region us-west-2 \
  --queue-url <app-crawl-queue-url> \
  --message-body '{"appid": 440}'

# Test with a review message:
aws sqs send-message --region us-west-2 \
  --queue-url <review-crawl-queue-url> \
  --message-body '{"appid": 440}'

# 5. Watch spoke logs (primary):
aws logs tail /aws/lambda/SteamPulse-Staging-SpokeCrawlerFn \
  --region us-west-2 --follow

# Watch spoke logs (remote):
aws logs tail /aws/lambda/SteamPulse-Staging-SpokeCrawlerFn \
  --region us-east-1 --follow

# Watch ingest logs (us-west-2):
aws logs tail /aws/lambda/SteamPulse-Staging-SpokeIngestFn \
  --region us-west-2 --follow

# 6. If working: add more spokes (SPOKE_REGIONS=us-west-2,us-east-1,eu-west-1)
```

---

## Tests

### `tests/infra/test_spoke_stack.py` (NEW)

```python
import aws_cdk as cdk
from aws_cdk.assertions import Template
import pytest
from infra.stacks.spoke_stack import CrawlSpokeStack


@pytest.fixture
def template():
    app = cdk.App()
    stack = CrawlSpokeStack(
        app, "TestSpoke",
        primary_region="us-west-2",
        environment="staging",
        app_crawl_queue_arn="arn:aws:sqs:us-west-2:123456789012:AppCrawlQueue",
        review_crawl_queue_arn="arn:aws:sqs:us-west-2:123456789012:ReviewCrawlQueue",
        spoke_results_queue_url="https://sqs.us-west-2.amazonaws.com/123456789012/SpokeResultsQueue",
        assets_bucket_name="steampulse-assets-test",
        steam_api_key_secret_arn="arn:aws:secretsmanager:us-west-2:123456789012:secret:steam-key",
        env=cdk.Environment(account="123456789012", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_one_lambda(template):
    template.resource_count_is("AWS::Lambda::Function", 1)


def test_reserved_concurrency_three(template):
    template.has_resource_properties("AWS::Lambda::Function", {
        "ReservedConcurrentExecutions": 3,
    })


def test_no_vpc(template):
    template.resource_count_is("AWS::EC2::VPC", 0)


def test_two_event_source_mappings(template):
    """Two SQS triggers: metadata + reviews."""
    template.resource_count_is("AWS::Lambda::EventSourceMapping", 2)


def test_ssm_status_param(template):
    template.resource_count_is("AWS::SSM::Parameter", 1)
```

### `tests/services/test_ingest_spoke.py` (NEW)

```python
import asyncio
import pytest
from unittest.mock import MagicMock


def test_ingest_spoke_reviews_returns_count(crawl_service):
    reviews = [{"review_text": "good", "voted_up": True, "playtime_at_review": 60,
                "timestamp_created": 1700000001, "language": "english",
                "author_steamid": "u1", "votes_helpful": 0, "votes_funny": 0,
                "written_during_early_access": False, "received_for_free": False}]
    crawl_service._review_repo.bulk_upsert = MagicMock(return_value=1)
    crawl_service._game_repo.ensure_stub = MagicMock()
    crawl_service._game_repo.find_by_appid = MagicMock(return_value=None)
    assert asyncio.run(crawl_service.ingest_spoke_reviews(440, reviews)) == 1


def test_ingest_spoke_reviews_empty(crawl_service):
    assert asyncio.run(crawl_service.ingest_spoke_reviews(440, [])) == 0


def test_ingest_spoke_metadata_delegates(crawl_service):
    crawl_service._ingest_app_data = MagicMock(return_value=True)
    raw = {"details": {"name": "TF2", "type": "game"}, "summary": {}, "deck_compat": None}
    assert asyncio.run(crawl_service.ingest_spoke_metadata(440, raw)) is True
    crawl_service._ingest_app_data.assert_called_once()


def test_ingest_spoke_metadata_empty_details(crawl_service):
    assert asyncio.run(crawl_service.ingest_spoke_metadata(440, {})) is False
```

---

## Verification

```bash
poetry run pytest tests/ -x -q
poetry run pytest tests/infra/test_spoke_stack.py -v
poetry run pytest tests/services/test_ingest_spoke.py -v
cd infra && poetry run cdk synth
```
