#!/usr/bin/env python3
"""Minimal test: submit a tiny Bedrock batch inference job and poll until done.

Verifies that:
1. S3 upload works (JSONL input)
2. Bedrock accepts the job (create_model_invocation_job)
3. The IAM role can be assumed by Bedrock
4. The job completes and output appears in S3

Usage:
  # Auto-discovers the Bedrock role ARN from the deployed SubmitBatchJob Lambda env vars
  python scripts/test_bedrock_batch.py --env staging

  # Or pass the role ARN explicitly
  python scripts/test_bedrock_batch.py --env staging --role-arn arn:aws:iam::123:role/...
"""

import argparse
import json
import sys
import time
from datetime import datetime

import boto3


def _discover_role_arn(env: str, region: str) -> str:
    """Read BEDROCK_BATCH_ROLE_ARN from the deployed SubmitBatchJob Lambda's env vars."""
    lam = boto3.client("lambda", region_name=region)
    # Find the Lambda by listing functions and matching the name pattern
    paginator = lam.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]
            if "SubmitBatchJob" in name and env in name.lower():
                config = lam.get_function_configuration(FunctionName=name)
                env_vars = config.get("Environment", {}).get("Variables", {})
                role_arn = env_vars.get("BEDROCK_BATCH_ROLE_ARN")
                if role_arn:
                    print(f"Discovered role ARN from Lambda {name}")
                    return role_arn
    raise RuntimeError(
        f"Could not find SubmitBatchJob Lambda for env={env}. "
        "Pass --role-arn explicitly."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Bedrock batch inference end-to-end")
    parser.add_argument("--env", choices=["staging", "production"], default="staging")
    parser.add_argument("--model", default="us.anthropic.claude-sonnet-4-6", help="Bedrock model ID")
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    parser.add_argument("--role-arn", help="Bedrock batch role ARN (auto-discovered if omitted)")
    args = parser.parse_args()

    bucket = f"steampulse-batch-{args.env}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = f"test-jobs/{timestamp}"

    if args.role_arn:
        role_arn = args.role_arn
    else:
        try:
            role_arn = _discover_role_arn(args.env, args.region)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"Bucket:    {bucket}")
    print(f"Role ARN:  {role_arn}")
    print(f"Model:     {args.model}")
    print(f"Region:    {args.region}")
    print(f"Prefix:    {prefix}")
    print()

    # Step 1: Upload a tiny JSONL input to S3
    s3 = boto3.client("s3", region_name=args.region)
    input_key = f"{prefix}/input.jsonl"
    output_prefix = f"{prefix}/output/"

    record = {
        "recordId": "test-001",
        "modelInput": {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 64,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: BATCH_TEST_OK",
                }
            ],
        },
    }

    jsonl_body = json.dumps(record)
    s3.put_object(Bucket=bucket, Key=input_key, Body=jsonl_body.encode(), ContentType="application/x-ndjson")
    print(f"[1/4] Uploaded input: s3://{bucket}/{input_key}")

    # Step 2: Submit batch job
    bedrock = boto3.client("bedrock", region_name=args.region)
    input_uri = f"s3://{bucket}/{input_key}"
    output_uri = f"s3://{bucket}/{output_prefix}"
    job_name = f"sp-test-{timestamp}"

    try:
        resp = bedrock.create_model_invocation_job(
            jobName=job_name,
            roleArn=role_arn,
            modelId=args.model,
            inputDataConfig={"s3InputDataConfig": {"s3Uri": input_uri}},
            outputDataConfig={"s3OutputDataConfig": {"s3Uri": output_uri}},
        )
    except Exception as e:
        print(f"[2/4] FAILED to submit job: {e}", file=sys.stderr)
        sys.exit(1)

    job_arn = resp["jobArn"]
    print(f"[2/4] Job submitted: {job_arn}")

    # Step 3: Poll until complete
    print("[3/4] Polling status...", end="", flush=True)
    terminal_states = {"Completed", "Failed", "Expired", "Stopped"}
    status = "Submitted"
    while status not in terminal_states:
        time.sleep(15)
        print(".", end="", flush=True)
        job_info = bedrock.get_model_invocation_job(jobIdentifier=job_arn)
        status = job_info["status"]

    print(f" {status}")

    if status != "Completed":
        print(f"[3/4] Job ended with status: {status}")
        if "message" in job_info:
            print(f"  Message: {job_info['message']}")
        sys.exit(1)

    # Step 4: Read output
    print("[4/4] Reading output from S3...")
    output_objects = s3.list_objects_v2(Bucket=bucket, Prefix=output_prefix)
    if "Contents" not in output_objects:
        print("  No output files found!")
        sys.exit(1)

    for obj in output_objects["Contents"]:
        key = obj["Key"]
        if key.endswith(".jsonl.out"):
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode()
            for line in body.strip().split("\n"):
                parsed = json.loads(line)
                record_id = parsed.get("recordId", "?")
                output = parsed.get("modelOutput", {})
                if "content" in output:
                    text = output["content"][0].get("text", "")
                    print(f"  Record {record_id}: {text}")
                elif "error" in parsed:
                    print(f"  Record {record_id}: ERROR — {parsed['error']}")
                else:
                    print(f"  Record {record_id}: {json.dumps(output)[:200]}")

    # Cleanup
    print()
    print("Cleaning up test files...")
    for obj in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    # Also clean output files
    for obj in output_objects.get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    print("Done.")


if __name__ == "__main__":
    main()
