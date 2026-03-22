# SteamPulse — Bedrock Batch Inference + Step Functions Redesign

## Context

SteamPulse processes Steam game reviews through a two-pass LLM pipeline:
- **Pass 1 (Haiku):** 50-review chunks → extract signals (complaints, praises, requests)
- **Pass 2 (Sonnet):** all chunk summaries → synthesize structured report

The current implementation calls Bedrock `InvokeModel` synchronously inside an Analysis Lambda
(10-min timeout, Express Step Functions). This is fine for on-demand single games but suboptimal
for the bulk seed (6,000 games × ~40 chunks = ~240k Haiku calls + 6k Sonnet calls).

**Goal:** Add a Bedrock Batch Inference path for bulk processing. Keep the real-time path for
on-demand single-game analysis. Use the Converse API for all real-time Bedrock calls going forward.

---

## Why Bedrock Batch Inference

- **~50% cost reduction** on the $2k seed cost
- **No Lambda timeout risk** — batch jobs run for hours
- **Parallelism at scale** — one JSONL file, AWS handles the rest
- **Cleaner retry semantics** — Bedrock retries internally, not Lambda

---

## Two Processing Modes

### Mode A: Real-Time (on-demand, single game)
*Keep existing path. Triggered when a user requests a game not yet in DB.*

```
Review Crawler → CrawlService._trigger_analysis() → Step Functions (EXPRESS)
→ Analysis Lambda → AnthropicBedrock InvokeModel (sync, per chunk) → DB
```

**Changes:** Migrate real-time Bedrock calls from `InvokeModel` raw SDK to **Converse API**.
This makes model swapping trivial (one env var change).

### Mode B: Batch (bulk seed, scheduled re-analysis)
*New path. Triggered by admin action or scheduled EventBridge rule.*

```
Trigger (admin invoke / EventBridge)
→ Step Functions (STANDARD — long-running)
→ [PreparePass1]   Lambda: reads reviews from DB, writes JSONL to S3
→ [SubmitPass1Job] Lambda: creates Bedrock batch job
→ [PollPass1]      Loop: check job status every 5 min until Complete/Failed
→ [PreparePass2]   Lambda: reads Pass 1 S3 output, writes Pass 2 JSONL to S3
→ [SubmitPass2Job] Lambda: creates Bedrock batch job
→ [PollPass2]      Loop: check job status every 5 min until Complete/Failed
→ [ProcessResults] Lambda: reads Pass 2 S3 output, upserts reports to DB
→ [NotifyDone]     Lambda: log summary, optionally send SNS alert
```

---

## S3 Structure

Use a dedicated bucket: `steampulse-batch-{env}`

```
steampulse-batch-{env}/
  jobs/
    {execution-id}/
      pass1/
        input.jsonl          # uploaded by PreparePass1
        output/              # written by Bedrock
          {job-id}.jsonl.out
      pass2/
        input.jsonl          # uploaded by PreparePass2
        output/
          {job-id}.jsonl.out
```

---

## JSONL Formats

### Pass 1 Input (one record per review chunk)

```json
{
  "recordId": "appid-{appid}-chunk-{n}",
  "modelInput": {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 1024,
    "system": "<pass1 system prompt — same text as current analyzer.py>",
    "messages": [
      {
        "role": "user",
        "content": "Analyze these 50 reviews for {game_name}:\n\n{reviews_text}"
      }
    ]
  }
}
```

**Note:** Bedrock Batch does NOT support `cache_control` prompt caching. Remove the
`{"type": "ephemeral"}` block from batch requests. Prompt caching only works in real-time calls.

### Pass 2 Input (one record per game)

```json
{
  "recordId": "appid-{appid}-synthesis",
  "modelInput": {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 4096,
    "system": "<pass2 system prompt — same text as current analyzer.py>",
    "messages": [
      {
        "role": "user",
        "content": "Synthesize these chunk summaries for {game_name}:\n\n{all_chunk_summaries_json}"
      }
    ]
  }
}
```

### Output format (Bedrock writes this)

```json
{
  "recordId": "appid-440-chunk-0",
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

## Step Functions State Machine (STANDARD workflow)

```json
{
  "Comment": "SteamPulse bulk analysis via Bedrock Batch Inference",
  "StartAt": "PreparePass1",
  "States": {
    "PreparePass1": {
      "Type": "Task",
      "Resource": "${PreparePass1FunctionArn}",
      "Parameters": {
        "execution_id.$": "$$.Execution.Name",
        "appids.$": "$.appids",
        "bucket": "${BatchBucketName}"
      },
      "ResultPath": "$.pass1",
      "Next": "SubmitPass1Job"
    },
    "SubmitPass1Job": {
      "Type": "Task",
      "Resource": "${SubmitBatchJobFunctionArn}",
      "Parameters": {
        "execution_id.$": "$$.Execution.Name",
        "pass": "pass1",
        "model_id": "${HaikuModelId}",
        "input_s3_uri.$": "$.pass1.input_s3_uri",
        "output_s3_uri.$": "$.pass1.output_s3_uri",
        "bucket": "${BatchBucketName}"
      },
      "ResultPath": "$.pass1.job",
      "Next": "WaitPass1"
    },
    "WaitPass1": {
      "Type": "Wait",
      "Seconds": 300,
      "Next": "CheckPass1Status"
    },
    "CheckPass1Status": {
      "Type": "Task",
      "Resource": "${CheckBatchStatusFunctionArn}",
      "Parameters": {
        "job_id.$": "$.pass1.job.job_id"
      },
      "ResultPath": "$.pass1.job.status_result",
      "Next": "Pass1Complete?"
    },
    "Pass1Complete?": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.pass1.job.status_result.status",
          "StringEquals": "Completed",
          "Next": "PreparePass2"
        },
        {
          "Variable": "$.pass1.job.status_result.status",
          "StringEquals": "Failed",
          "Next": "JobFailed"
        }
      ],
      "Default": "WaitPass1"
    },
    "PreparePass2": {
      "Type": "Task",
      "Resource": "${PreparePass2FunctionArn}",
      "Parameters": {
        "execution_id.$": "$$.Execution.Name",
        "pass1_output_s3_uri.$": "$.pass1.output_s3_uri",
        "bucket": "${BatchBucketName}"
      },
      "ResultPath": "$.pass2",
      "Next": "SubmitPass2Job"
    },
    "SubmitPass2Job": {
      "Type": "Task",
      "Resource": "${SubmitBatchJobFunctionArn}",
      "Parameters": {
        "execution_id.$": "$$.Execution.Name",
        "pass": "pass2",
        "model_id": "${SonnetModelId}",
        "input_s3_uri.$": "$.pass2.input_s3_uri",
        "output_s3_uri.$": "$.pass2.output_s3_uri",
        "bucket": "${BatchBucketName}"
      },
      "ResultPath": "$.pass2.job",
      "Next": "WaitPass2"
    },
    "WaitPass2": {
      "Type": "Wait",
      "Seconds": 300,
      "Next": "CheckPass2Status"
    },
    "CheckPass2Status": {
      "Type": "Task",
      "Resource": "${CheckBatchStatusFunctionArn}",
      "Parameters": {
        "job_id.$": "$.pass2.job.job_id"
      },
      "ResultPath": "$.pass2.job.status_result",
      "Next": "Pass2Complete?"
    },
    "Pass2Complete?": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.pass2.job.status_result.status",
          "StringEquals": "Completed",
          "Next": "ProcessResults"
        },
        {
          "Variable": "$.pass2.job.status_result.status",
          "StringEquals": "Failed",
          "Next": "JobFailed"
        }
      ],
      "Default": "WaitPass2"
    },
    "ProcessResults": {
      "Type": "Task",
      "Resource": "${ProcessResultsFunctionArn}",
      "Parameters": {
        "pass2_output_s3_uri.$": "$.pass2.output_s3_uri"
      },
      "ResultPath": "$.results",
      "Next": "NotifyDone"
    },
    "NotifyDone": {
      "Type": "Task",
      "Resource": "${NotifyDoneFunctionArn}",
      "Parameters": {
        "results.$": "$.results"
      },
      "End": true
    },
    "JobFailed": {
      "Type": "Fail",
      "Error": "BedrockBatchJobFailed",
      "Cause": "Bedrock batch inference job failed"
    }
  }
}
```

---

## Lambda Functions to Create

All under: `src/lambda-functions/lambda_functions/batch_analysis/`

### `prepare_pass1.py`
- Input: `{execution_id, appids: [int], bucket}`
- Reads reviews from DB (up to 2000 per game) using `ReviewRepository`
- Chunks reviews into 50-review batches
- Formats each chunk as a JSONL record (Pass 1 format above)
- Uploads JSONL to `s3://{bucket}/jobs/{execution_id}/pass1/input.jsonl`
- Returns: `{input_s3_uri, output_s3_uri, total_records}`

### `submit_batch_job.py`
- Input: `{execution_id, pass, model_id, input_s3_uri, output_s3_uri, bucket}`
- Calls `bedrock.create_model_invocation_job()`:
  ```python
  resp = bedrock.create_model_invocation_job(
      jobName=f"steampulse-{pass}-{execution_id[:8]}",
      roleArn=BATCH_ROLE_ARN,
      clientRequestToken=f"{execution_id}-{pass}",
      modelId=model_id,
      inputDataConfig={"s3InputDataConfig": {"s3Uri": input_s3_uri}},
      outputDataConfig={"s3OutputDataConfig": {"s3Uri": output_s3_uri}},
  )
  ```
- Returns: `{job_id: resp["jobArn"]}`

### `check_batch_status.py`
- Input: `{job_id}`
- Calls `bedrock.get_model_invocation_job(jobIdentifier=job_id)`
- Maps Bedrock statuses: `Submitted/InProgress/Stopping` → `"Running"`, `Completed` → `"Completed"`, `Failed/Stopped` → `"Failed"`
- Returns: `{status, message}`

### `prepare_pass2.py`
- Input: `{execution_id, pass1_output_s3_uri, bucket}`
- Reads Pass 1 output JSONL from S3
- Groups records by `appid` (parsed from `recordId`)
- For each game: collects all chunk summaries into one Pass 2 record
- Uploads Pass 2 JSONL to `s3://{bucket}/jobs/{execution_id}/pass2/input.jsonl`
- Returns: `{input_s3_uri, output_s3_uri, total_records}`

### `process_results.py`
- Input: `{pass2_output_s3_uri}`
- Reads Pass 2 output JSONL from S3
- For each record: parses the Sonnet JSON response, computes `sentiment_score` + `hidden_gem_score`
  (reuse the Python scoring functions already in `analyzer.py`)
- Upserts to `reports` table via `ReportRepository`
- Updates `games.report_generated_at` timestamp
- Returns: `{processed: int, failed: int, failed_appids: [int]}`

### `notify_done.py`
- Input: `{results: {processed, failed, failed_appids}}`
- Logs summary via Lambda Powertools logger
- Optionally publishes to SNS topic if configured (env var `NOTIFY_SNS_ARN`)
- Returns: passthrough

---

## CDK Changes

### New Stack: `BatchAnalysisStack`

Add to `infra/stacks/batch_analysis_stack.py`:

```python
# S3 bucket for batch I/O
batch_bucket = s3.Bucket(self, "BatchBucket",
    bucket_name=f"steampulse-batch-{config.env}",
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
    encryption=s3.BucketEncryption.S3_MANAGED,
    enforce_ssl=True,
    lifecycle_rules=[
        s3.LifecycleRule(expiration=Duration.days(7))  # auto-clean old job files
    ],
    removal_policy=cdk.RemovalPolicy.DESTROY,
    auto_delete_objects=True,
)

# IAM role that Bedrock assumes to read/write S3
batch_role = iam.Role(self, "BedrockBatchRole",
    assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
    inline_policies={
        "BatchS3Access": iam.PolicyDocument(statements=[
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"{batch_bucket.bucket_arn}/*"],
            )
        ])
    },
)

# Lambda functions (one per state)
# All share: VPC, DB secret, batch bucket name, batch role ARN, model IDs from SSM

# Step Functions — STANDARD workflow (not EXPRESS, because it can run for hours)
# Type: STANDARD is required for Wait states > 5 min and long-running workflows
```

### IAM for Lambda Execution Role

Each batch Lambda needs:
```python
role.add_to_policy(iam.PolicyStatement(
    actions=[
        "bedrock:CreateModelInvocationJob",
        "bedrock:GetModelInvocationJob",
        "bedrock:ListModelInvocationJobs",
        "bedrock:StopModelInvocationJob",
    ],
    resources=["*"],
))
role.add_to_policy(iam.PolicyStatement(
    actions=["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
    resources=[batch_bucket.bucket_arn, f"{batch_bucket.bucket_arn}/*"],
))
role.add_to_policy(iam.PolicyStatement(
    actions=["iam:PassRole"],
    resources=[batch_role.role_arn],
))
```

### Add EventBridge Trigger (disabled by default)

```python
# Weekly batch re-analysis of top 500 games
events.Rule(self, "WeeklyBatchRule",
    schedule=events.Schedule.cron(hour="3", minute="0", week_day="SUN"),
    enabled=False,  # enable when ready
    targets=[targets.SfnStateMachine(batch_state_machine,
        input=events.RuleTargetInput.from_object({
            "appids": "TOP_500"  # PreparePass1 resolves this to actual appids
        })
    )],
)
```

---

## Real-Time Path: Migrate to Converse API

The existing `analyzer.py` uses `anthropic.AnthropicBedrock()` directly. Migrate to Bedrock
native `boto3` Converse API for the real-time path:

```python
import boto3, json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

def invoke_converse(model_id: str, system: str, user_content: str, max_tokens: int) -> str:
    resp = bedrock.converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.3},
    )
    return resp["output"]["message"]["content"][0]["text"]
```

Benefits:
- Model-agnostic: swap `modelId` env var, zero code changes
- Works with any Bedrock-supported model (Llama, Nova, Mistral, etc.)
- Converse API is AWS's recommended interface going forward

**For prompt caching in Converse API** (real-time path only):
```python
# system with cache point
system=[
    {"text": system_prompt, "cachePoint": {"type": "default"}}
]
```

---

## What NOT to Change

- `analysis/handler.py` and the existing `AnalysisStack` — keep for on-demand single-game analysis
- `CrawlService._trigger_analysis()` — keep for per-game triggers after crawl
- `ReportRepository` — reuse as-is in `process_results.py`
- The scoring functions in `analyzer.py` (`_compute_sentiment_score`, `_compute_hidden_gem_score`) — extract to `utils/scores.py` so both paths can import them

---

## Triggering a Bulk Seed

```python
# Admin one-liner to kick off bulk seed
import boto3, json
sfn = boto3.client("stepfunctions")
sfn.start_execution(
    stateMachineArn="arn:aws:states:...:stateMachine:steampulse-batch-analysis-prod",
    name="seed-2025-01",
    input=json.dumps({"appids": "ALL_ELIGIBLE"})  # PreparePass1 queries DB for 500+ review games
)
```

---

## Testing

- Unit test each Lambda with moto (`mock_s3`, `mock_bedrock`)
- Integration test: create a small JSONL (3 games × 2 chunks), run full state machine in LocalStack or with real Bedrock in staging
- Validate Pass 1 → Pass 2 grouping logic with a pytest fixture containing known chunk outputs

---

## Definition of Done

- [ ] `BatchAnalysisStack` deployed to staging
- [ ] All 5 Lambda functions pass unit tests
- [ ] End-to-end test: 5 games through full batch pipeline, reports appear in DB
- [ ] Real-time path migrated to Converse API (existing tests still pass)
- [ ] `utils/scores.py` extracted and used by both paths
- [ ] EventBridge rule present but `enabled=False`
- [ ] Batch bucket lifecycle rule deletes files after 7 days
