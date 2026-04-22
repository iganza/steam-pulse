#!/usr/bin/env python3
"""Trigger a SteamPulse Phase-4 cross-genre synthesis run.

Starts a single execution of the genre-synthesis orchestrator Step
Functions state machine, fanning out over one execution per slug via
DistributedMap (max_concurrency=2). Each per-slug execution submits one
Anthropic message batch and, on completion, upserts ``mv_genre_synthesis``.

The service short-circuits on ``input_hash`` cache hits — the per-slug
SFN returns ``skip=True`` at Prepare and bypasses Wait/Check/Collect.
Bump --prompt-version to force a re-synthesis when neither the prompt
nor the GameReport set has changed.

Usage:
  # Synthesize one genre against staging
  python scripts/trigger_genre_synthesis.py --env staging --slugs roguelike-deckbuilder

  # Multiple slugs, production
  python scripts/trigger_genre_synthesis.py --env production \\
      --slugs roguelike-deckbuilder deckbuilding

  # Force a re-synthesis (bust the input_hash cache)
  python scripts/trigger_genre_synthesis.py --env production \\
      --slugs roguelike-deckbuilder --prompt-version v1-rerun

  # Dry run
  python scripts/trigger_genre_synthesis.py --env staging \\
      --slugs roguelike-deckbuilder --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import boto3

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "library-layer"))

from library_layer.config import SteamPulseConfig  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger SteamPulse Phase-4 genre synthesis")
    parser.add_argument("--env", choices=["staging", "production"], default="staging")
    parser.add_argument(
        "--slugs",
        nargs="+",
        required=True,
        metavar="slug",
        help="Genre slug(s) to synthesize (e.g. roguelike-deckbuilder)",
    )
    parser.add_argument(
        "--prompt-version",
        default=None,
        metavar="V",
        help="Override GENRE_SYNTHESIS_PROMPT_VERSION (bump to bust input_hash cache)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print intent without publishing")
    args = parser.parse_args()

    config = SteamPulseConfig.for_environment(args.env)
    prompt_version = args.prompt_version or config.GENRE_SYNTHESIS_PROMPT_VERSION

    if not config.GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME:
        print(
            f"ERROR: GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME not set for env={args.env}",
            file=sys.stderr,
        )
        sys.exit(1)

    payload = {"slugs": list(args.slugs), "prompt_version": prompt_version}

    print(f"Env:            {args.env}")
    print(f"Prompt version: {prompt_version}")
    print(f"Slug(s):        {', '.join(args.slugs)}")

    if args.dry_run:
        print("DRY RUN — would start orchestrator with:")
        print(f"  {json.dumps(payload)}")
        return

    ssm = boto3.client("ssm")
    try:
        sfn_arn = ssm.get_parameter(
            Name=config.GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME
        )["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        print(
            f"ERROR: SSM parameter {config.GENRE_SYNTHESIS_ORCHESTRATOR_SFN_PARAM_NAME} "
            "not found. Is BatchAnalysisStack deployed?",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Orchestrator:   {sfn_arn}")

    sfn = boto3.client("stepfunctions")
    resp = sfn.start_execution(stateMachineArn=sfn_arn, input=json.dumps(payload))
    execution_arn = resp["executionArn"]
    region = sfn_arn.split(":")[3]
    console_url = (
        f"https://{region}.console.aws.amazon.com/states/home"
        f"?region={region}#/executions/details/{execution_arn}"
    )
    print("Execution started")
    print(f"  ARN:     {execution_arn}")
    print(f"  Console: {console_url}")


if __name__ == "__main__":
    main()
