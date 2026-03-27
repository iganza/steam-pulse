# SteamPulse — Batch Analysis Pipeline

## Overview

SteamPulse processes Steam game reviews through a two-pass LLM pipeline:
- **Pass 1 (Haiku):** 50-review chunks → extract 11 signal types into `ChunkSummary` JSON
- **Pass 2 (Sonnet):** aggregated chunk signals → synthesize structured `GameReport` JSON

`sentiment_score`, `hidden_gem_score`, and `sentiment_trend` are computed in Python (never LLM-guessed).

Two execution paths:
- **Batch path** (this spec): Bedrock Batch Inference + STANDARD Step Functions — for bulk seeding, scheduled re-analysis
- **Real-time path**: instructor + Converse API — for `/api/preview` on-demand analysis (Flow-05)

Both paths use the same prompts defined as constants in `analyzer.py`.

---

## Batch Pipeline Flow

Manually triggered by admin. STANDARD Step Functions (not EXPRESS — batch jobs run for hours).

```
Admin (CLI / Lambda)
  │  sfn.start_execution({appids: [int] | "ALL_ELIGIBLE"})
  ▼
Step Functions (STANDARD)
  │
  ├─ [PreparePass1]      Read reviews from DB, chunk into 50-review batches
  │                      Format each chunk as JSONL record (Pass 1 format)
  │                      Upload to s3://{bucket}/jobs/{exec-id}/pass1/input.jsonl
  │                      Returns: {input_s3_uri, output_s3_uri, total_records}
  │
  ├─ [SubmitPass1Job]    bedrock.create_model_invocation_job()
  │                      Model: LLM_MODEL__CHUNKING (Haiku)
  │                      Returns: {job_id (ARN)}
  │
  ├─ [WaitPass1]         Wait 300s
  ├─ [CheckPass1Status]  bedrock.get_model_invocation_job() → Running/Completed/Failed
  ├─ [Pass1Complete?]    Choice: Completed → PreparePass2, Failed → Fail, else → WaitPass1
  │
  ├─ [PreparePass2]      Read Pass1 output JSONL from S3
  │                      Group records by appid, aggregate all signal lists
  │                      Compute sentiment_score, hidden_gem_score (from batch_stats)
  │                      Fetch review timestamps from DB → compute sentiment_trend
  │                      Write per-game scores to s3://.../pass2/scores.json
  │                      Format one JSONL record per game (Pass 2 format)
  │                      Upload to s3://{bucket}/jobs/{exec-id}/pass2/input.jsonl
  │                      Returns: {input_s3_uri, output_s3_uri, total_records}
  │
  ├─ [SubmitPass2Job]    bedrock.create_model_invocation_job()
  │                      Model: LLM_MODEL__SUMMARIZER (Sonnet)
  │                      Returns: {job_id}
  │
  ├─ [WaitPass2]         Wait 300s
  ├─ [CheckPass2Status]  Poll job status
  ├─ [Pass2Complete?]    Choice: Completed → ProcessResults, Failed → Fail, else → WaitPass2
  │
  └─ [ProcessResults]    Read Pass2 output JSONL from S3
                         Parse GameReport JSON per record
                         ReportRepository.upsert() per game
                         Publish report-ready event to ContentEventsTopic per game
                         Publish batch-complete event to SystemEventsTopic
                         Returns: {processed, failed, failed_appids}
```

---

## S3 Structure

Bucket: `steampulse-batch-{env}` (7-day lifecycle expiry, auto-deleted)

```
steampulse-batch-{env}/
  jobs/
    {execution-id}/
      pass1/
        input.jsonl           # uploaded by PreparePass1
        output/               # written by Bedrock
          {job-id}.jsonl.out
      pass2/
        input.jsonl           # uploaded by PreparePass2
        scores.json           # pre-computed Python scores per appid
        output/
          {job-id}.jsonl.out
```

---

## JSONL Record Formats

### Pass 1 Input (one record per 50-review chunk)

```json
{
  "recordId": "{appid}-chunk-{n}",
  "modelInput": {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 1024,
    "system": "<CHUNK_SYSTEM_PROMPT constant from analyzer.py>",
    "messages": [{"role": "user", "content": "<formatted user message>"}]
  }
}
```

**Note:** No `cache_control` in batch JSONL. Prompt caching only works in real-time Converse calls.

### Pass 2 Input (one record per game)

```json
{
  "recordId": "{appid}-synthesis",
  "modelInput": {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 5000,
    "system": "<SYNTHESIS_SYSTEM_PROMPT constant from analyzer.py>",
    "messages": [{"role": "user", "content": "<formatted user message with aggregated signals>"}]
  }
}
```

### Bedrock Output Format (written by Bedrock)

```json
{
  "recordId": "440-chunk-0",
  "modelOutput": {
    "id": "msg_xxx",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "{...extracted json...}"}],
    "stop_reason": "end_turn"
  }
}
```

---

## Lambda Functions

All under: `src/lambda-functions/lambda_functions/batch_analysis/`

### `prepare_pass1.py`
- Input: `{execution_id: str, appids: list[int] | "ALL_ELIGIBLE"}`
- If `"ALL_ELIGIBLE"`: query DB for games with sufficient reviews (`review_count >= 50`)
- Reads reviews via `ReviewRepository.find_by_appid(appid, limit=2000)`
- Sorts reviews by `posted_at` ascending (chronological signal)
- Chunks into 50-review batches, formats Pass 1 JSONL records
- Uploads to `s3://{BATCH_BUCKET_NAME}/jobs/{execution_id}/pass1/input.jsonl`
- Returns: `{input_s3_uri, output_s3_uri, total_records}`

### `submit_batch_job.py`
- Input: `{execution_id: str, pass: str, model_id: str, input_s3_uri: str, output_s3_uri: str}`
- Calls `bedrock.create_model_invocation_job()` with `BEDROCK_BATCH_ROLE_ARN` env var
- Returns: `{job_id: resp["jobArn"]}`

### `check_batch_status.py`
- Input: `{job_id: str}`
- Calls `bedrock.get_model_invocation_job(jobIdentifier=job_id)`
- Maps: `Submitted|InProgress|Stopping` → `"Running"`, `Completed` → `"Completed"`, `Failed|Stopped` → `"Failed"`
- Returns: `{status: str, message: str}`

### `prepare_pass2.py`
- Input: `{execution_id: str, pass1_output_s3_uri: str}`
- Reads Pass 1 output JSONL from S3 (lists objects under the output prefix)
- Parses each record: validates `modelOutput.content[0].text` as `ChunkSummary` JSON
- Groups chunk summaries by appid (parsed from `recordId`: `{appid}-chunk-{n}`)
- For each game:
  - Aggregates signals with `_aggregate_chunk_summaries()`
  - Computes `sentiment_score`, `hidden_gem_score` from aggregated `total_stats`
  - Fetches `(voted_up, posted_at)` from DB via `ReviewRepository` → computes `sentiment_trend`
  - Formats Pass 2 JSONL record with pre-computed scores in `<game_context>`
- Saves scores to `s3://{bucket}/jobs/{execution_id}/pass2/scores.json`
- Uploads Pass 2 JSONL
- Returns: `{input_s3_uri, output_s3_uri, total_records}`

### `process_results.py`
- Input: `{pass2_output_s3_uri: str, execution_id: str}`
- Reads Pass 2 output JSONL from S3
- For each record:
  - Parses `modelOutput.content[0].text` as `GameReport` JSON
  - Validates with Pydantic
  - `ReportRepository.upsert(report)` — overwrites on conflict
  - Publishes `report-ready` event to `CONTENT_EVENTS_TOPIC_ARN` (SSM-resolved)
- Publishes `batch-complete` event to `SYSTEM_EVENTS_TOPIC_ARN` (SSM-resolved)
- Returns: `{processed: int, failed: int, failed_appids: list[int]}`

---

## Signal Aggregation (Pass 1 → Pass 2 Handoff)

PreparePass2 flattens chunk signals so Sonnet sees one clean view per signal type:

```python
def _aggregate_chunk_summaries(chunks: list[ChunkSummary]) -> dict:
    return {
        "design_praise": [item for cs in chunks for item in cs.design_praise],
        "gameplay_friction": [item for cs in chunks for item in cs.gameplay_friction],
        "wishlist_items": [item for cs in chunks for item in cs.wishlist_items],
        "dropout_moments": [item for cs in chunks for item in cs.dropout_moments],
        "competitor_refs": [item for cs in chunks for item in cs.competitor_refs],
        "notable_quotes": [item for cs in chunks for item in cs.notable_quotes],
        "technical_issues": [item for cs in chunks for item in cs.technical_issues],
        "refund_signals": [item for cs in chunks for item in cs.refund_signals],
        "community_health": [item for cs in chunks for item in cs.community_health],
        "monetization_sentiment": [item for cs in chunks for item in cs.monetization_sentiment],
        "content_depth": [item for cs in chunks for item in cs.content_depth],
        "total_stats": {
            "positive_count": sum(cs.batch_stats.positive_count for cs in chunks),
            "negative_count": sum(cs.batch_stats.negative_count for cs in chunks),
            "avg_playtime_hours": sum(cs.batch_stats.avg_playtime_hours * (cs.batch_stats.positive_count + cs.batch_stats.negative_count) for cs in chunks) / max(sum((cs.batch_stats.positive_count + cs.batch_stats.negative_count) for cs in chunks), 1),
            "high_playtime_count": sum(cs.batch_stats.high_playtime_count for cs in chunks),
            "early_access_count": sum(cs.batch_stats.early_access_count for cs in chunks),
            "free_key_count": sum(cs.batch_stats.free_key_count for cs in chunks),
        }
    }
```

This lives in `library_layer/analyzer.py` (public as `_aggregate_chunk_summaries`) and is imported by `prepare_pass2.py`.

---

## CDK Stack: `BatchAnalysisStack`

File: `infra/stacks/batch_analysis_stack.py`

### Resources

- **S3 bucket**: `steampulse-batch-{env}`, 7-day lifecycle, `DESTROY` removal policy
- **Bedrock batch IAM role**: assumed by `bedrock.amazonaws.com`, S3 read/write on batch bucket
- **Lambda execution role**: Bedrock batch APIs, S3 R/W on batch bucket, `iam:PassRole`, DB secret, SSM params, SNS publish
- **5 Lambda functions**: PreparePass1, SubmitBatchJob, CheckBatchStatus, PreparePass2, ProcessResults
- **STANDARD Step Functions state machine**: JSON ASL definition with Wait/Choice polling loops
- **EventBridge rule**: weekly schedule, `enabled=False` until ready

### Lambda Environment Variables

All batch Lambdas share:
- `DB_SECRET_NAME` — database credentials
- `BATCH_BUCKET_NAME` — S3 batch bucket name (literal, set in CDK)
- `BEDROCK_BATCH_ROLE_ARN` — SSM parameter path
- `LLM_MODEL__CHUNKING` — from config
- `LLM_MODEL__SUMMARIZER` — from config
- `CONTENT_EVENTS_TOPIC_PARAM_NAME` — SSM path for ContentEventsTopic ARN
- `SYSTEM_EVENTS_TOPIC_PARAM_NAME` — SSM path for SystemEventsTopic ARN

### IAM

Bedrock batch role (assumed by Bedrock service):
```python
iam.Role(assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
    inline_policies={"BatchS3": PolicyDocument([
        PolicyStatement(actions=["s3:GetObject", "s3:PutObject"], resources=[bucket_arn + "/*"])
    ])}
)
```

Lambda execution role:
```python
role.add_to_policy(PolicyStatement(actions=[
    "bedrock:CreateModelInvocationJob",
    "bedrock:GetModelInvocationJob",
    "bedrock:ListModelInvocationJobs",
    "bedrock:StopModelInvocationJob",
], resources=["*"]))
role.add_to_policy(PolicyStatement(actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
    resources=[bucket_arn, bucket_arn + "/*"]))
role.add_to_policy(PolicyStatement(actions=["iam:PassRole"], resources=[batch_role_arn]))
```

---

## LLM Prompts (stored as constants in `analyzer.py`)

Both paths (real-time via instructor, batch via JSONL) use the same prompt constants.
The batch path embeds them verbatim into JSONL `modelInput.system` / `modelInput.messages[0].content`.

### Pass 1 System Prompt (`CHUNK_SYSTEM_PROMPT`)

Uses XML tags: `<rules>`, `<signal_weighting>`, `<examples>`.

**Prompting techniques applied:**
- XML tags for unambiguous structure parsing
- One good + one bad extraction example (few-shot)
- Signal weighting instructions (helpful votes > playtime > free key)
- Strict accuracy rules (no invention, verbatim quotes)
- Direct output format (no chain-of-thought needed for Haiku)

### Pass 1 User Message (built per chunk)

Uses XML tags: `<task>`, `<signal_definitions>`, `<examples>`, `<reviews>`, `<output_format>`.

Each signal definition includes:
- What to include (specific examples)
- What to exclude (cross-signal boundary enforcement)

### Pass 2 System Prompt (`SYNTHESIS_SYSTEM_PROMPT`)

Uses XML tags: `<audience>`, `<anti_duplication_rules>`, `<tone>`, `<accuracy>`.

### Pass 2 User Message (built per game / per execution)

Uses XML tags: `<game_context>`, `<aggregated_signals>`, `<section_definitions>`, `<self_check>`, `<output_format>`.

`<game_context>` includes pre-computed scores verbatim — LLM instructed to include them exactly as given.

`<self_check>` before returning:
1. No issue appears with same framing in two sections
2. Every claim traces to a signal in aggregated_signals
3. dev_priorities ranked by impact × frequency
4. Enum values match exactly (e.g. "thriving" not "Thriving")

---

## Triggering a Bulk Seed

```python
# scripts/trigger_batch_analysis.py
import boto3, json, sys
sfn = boto3.client("stepfunctions")
sfn.start_execution(
    stateMachineArn="arn:aws:states:...:stateMachine:steampulse-batch-analysis-{env}",
    name=f"seed-{datetime.now().strftime('%Y%m%d-%H%M')}",
    input=json.dumps({"appids": "ALL_ELIGIBLE"})
)
```

---

## Drift Checklist

- Step Functions type: STANDARD (not EXPRESS) — batch jobs run for hours
- Bedrock Batch Inference API (not Converse) — `create_model_invocation_job()`
- No `cache_control` in batch JSONL — prompt caching not supported in batch
- `recordId` format: `{appid}-chunk-{n}` (Pass 1), `{appid}-synthesis` (Pass 2)
- `sentiment_score`, `hidden_gem_score` computed from `total_stats.positive_count/negative_count`
- `sentiment_trend` computed via `compute_sentiment_trend(reviews)` — needs DB query in PreparePass2
- Pre-computed scores embedded in Pass 2 prompt context; LLM told to include them verbatim
- `ReportRepository.upsert()` overwrites on conflict — re-analysis is always a full replace
- `report-ready` event published per game by ProcessResults
- `batch-complete` event published once at end by ProcessResults
- S3 bucket 7-day lifecycle — intermediate files auto-deleted
- Bedrock batch role assumed by `bedrock.amazonaws.com` (not Lambda role)
- `iam:PassRole` required on Lambda execution role to pass batch role to Bedrock
- `BATCH_BUCKET_NAME` env var is a literal value (not SSM param) — no resolution needed
- `BEDROCK_BATCH_ROLE_ARN` env var is a literal ARN set by CDK (not SSM) — passed directly
- Real-time path: instructor + `AnthropicBedrock()` + prompt caching — unchanged
- `_aggregate_chunk_summaries()` in `analyzer.py` — used by both real-time path and PreparePass2
- Scoring functions in `library_layer/utils/scores.py` — imported by `analyzer.py` and batch Lambdas

---

## Definition of Done

- [ ] `BatchAnalysisStack` deploys to staging (`cdk synth` clean)
- [ ] All 5 Lambda functions pass unit tests (moto mock_s3 + mock_bedrock)
- [ ] Prompts use XML tags throughout; `CHUNK_SYSTEM_PROMPT` and `SYNTHESIS_SYSTEM_PROMPT` updated in `analyzer.py`
- [ ] `utils/scores.py` extracted and used by both paths
- [ ] `_aggregate_chunk_summaries()` in `analyzer.py` used by real-time path and PreparePass2
- [ ] ARCHITECTURE.org Flow-04 updated with batch design
- [ ] EventBridge rule present but `enabled=False`
- [ ] S3 bucket 7-day lifecycle configured
- [ ] `scripts/trigger_batch_analysis.py` CLI trigger exists
