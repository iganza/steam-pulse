#!/usr/bin/env python3
"""Trigger a SteamPulse batch analysis orchestrator execution.

Usage:
  # Analyze specific appids
  python scripts/trigger_batch_analysis.py --env staging --appids 440 730 570

  # Limit concurrency for testing
  python scripts/trigger_batch_analysis.py --env staging --appids 440 730 --concurrency 2

  # Dry run — print what would be sent without starting execution
  python scripts/trigger_batch_analysis.py --env staging --appids 440 --dry-run
"""

import argparse
import json
import sys
from datetime import datetime

import boto3


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger SteamPulse batch analysis")
    parser.add_argument("--env", choices=["staging", "production"], default="staging")
    parser.add_argument("--appids", type=int, nargs="+", required=True, help="Appids to analyze")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=20,
        help="Max concurrent per-game executions (default: 20)",
    )
    parser.add_argument(
        "--start-at",
        choices=["chunk", "merge"],
        default="chunk",
        help="Phase to start at. 'merge' skips chunk phase — the "
             "per-game machine reads cached chunks from chunk_summaries "
             "and begins at PrepareMerge. Use when chunks are already "
             "persisted (e.g. a prior run failed on one chunk). Default: chunk.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print intent without executing")
    args = parser.parse_args()

    # Resolve orchestrator state machine ARN from SSM
    ssm = boto3.client("ssm")
    param_name = f"/steampulse/{args.env}/batch/orchestrator-sfn-arn"
    try:
        sfn_arn = ssm.get_parameter(Name=param_name)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        print(
            f"ERROR: SSM parameter {param_name} not found. Is BatchAnalysisStack deployed?",
            file=sys.stderr,
        )
        sys.exit(1)

    payload = {
        "appids": args.appids,
        "max_concurrency": args.concurrency,
        "start_at": args.start_at,
    }
    execution_input = json.dumps(payload)
    execution_name = f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    if args.dry_run:
        print("DRY RUN — would start execution:")
        print(f"  State machine: {sfn_arn}")
        print(f"  Name:          {execution_name}")
        print(f"  Input:         {execution_input}")
        return

    sfn = boto3.client("stepfunctions")
    resp = sfn.start_execution(
        stateMachineArn=sfn_arn,
        name=execution_name,
        input=execution_input,
    )

    print(f"Started execution: {resp['executionArn']}")
    print(f"Name: {execution_name}")
    print(f"Appids: {args.appids}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Start at: {args.start_at}")


if __name__ == "__main__":
    main()
