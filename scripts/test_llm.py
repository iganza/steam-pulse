#!/usr/bin/env python3
"""Quick smoke test to verify Anthropic API connectivity and model access."""

import os
import sys

from dotenv import load_dotenv
load_dotenv()

import anthropic

HAIKU_MODEL = os.getenv("HAIKU_MODEL", "claude-3-5-haiku-20241022")
SONNET_MODEL = os.getenv("SONNET_MODEL", "claude-3-5-sonnet-20241022")


def test_model(client: anthropic.Anthropic, model: str) -> bool:
    print(f"Testing {model}... ", end="", flush=True)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=32,
            messages=[{"role": "user", "content": "Reply with just: ok"}],
        )
        print(f"✓  ({response.content[0].text.strip()})")
        return True
    except Exception as e:
        print(f"✗  {e}")
        return False


if __name__ == "__main__":
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    results = [
        test_model(client, HAIKU_MODEL),
        test_model(client, SONNET_MODEL),
    ]

    sys.exit(0 if all(results) else 1)
