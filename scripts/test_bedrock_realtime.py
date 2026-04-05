#!/usr/bin/env python3
"""Test Bedrock real-time Converse API — verify credentials and model access.

Sends a simple prompt via the same AnthropicBedrock client the analyzer uses.
No database, no reviews, no reports — just confirms the LLM round-trip works.

Usage:
  python scripts/test_bedrock_realtime.py
  python scripts/test_bedrock_realtime.py --model us.anthropic.claude-haiku-4-5-20251001-v1:0
  python scripts/test_bedrock_realtime.py --region us-west-2
"""

import argparse
import time

import anthropic


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Bedrock real-time Converse API")
    parser.add_argument(
        "--model", default="us.anthropic.claude-sonnet-4-6", help="Bedrock model ID"
    )
    parser.add_argument("--region", default="us-west-2", help="AWS region")
    args = parser.parse_args()

    print(f"Model:  {args.model}")
    print(f"Region: {args.region}")
    print()

    client = anthropic.AnthropicBedrock(aws_region=args.region)

    # Test 1: Simple text response
    print("[1/2] Simple text prompt...")
    t0 = time.monotonic()
    resp = client.messages.create(
        model=args.model,
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with exactly: REALTIME_TEST_OK"}],
    )
    elapsed = round((time.monotonic() - t0) * 1000)
    text = resp.content[0].text.strip()
    print(f"  Response: {text}")
    print(f"  Latency:  {elapsed}ms")
    print(f"  Tokens:   {resp.usage.input_tokens} in / {resp.usage.output_tokens} out")
    print()

    # Test 2: Structured JSON output (mimics the analyzer pattern)
    print("[2/2] Structured JSON prompt...")
    t0 = time.monotonic()
    resp = client.messages.create(
        model=args.model,
        max_tokens=256,
        system="You extract structured data. Return ONLY valid JSON. No prose.",
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the sentiment from this review:\n\n"
                    '"I love the combat but the matchmaking is terrible. 200 hours played."\n\n'
                    'Return JSON: {"topics": [{"name": str, "sentiment": "positive"|"negative", '
                    '"mention_count": int}], "overall": "positive"|"negative"|"mixed"}'
                ),
            }
        ],
    )
    elapsed = round((time.monotonic() - t0) * 1000)
    text = resp.content[0].text.strip()
    print(f"  Response: {text}")
    print(f"  Latency:  {elapsed}ms")
    print(f"  Tokens:   {resp.usage.input_tokens} in / {resp.usage.output_tokens} out")
    print()

    print("All tests passed.")


if __name__ == "__main__":
    main()
