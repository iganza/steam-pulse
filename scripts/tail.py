#!/usr/bin/env python3
"""tail.py — tail SteamPulse Lambda log streams.

Resolves log groups dynamically (CDK generates random suffixes) and tails
one or more streams simultaneously with colour-coded prefixes.

Usage:
  python scripts/tail.py crawler
  python scripts/tail.py spoke
  python scripts/tail.py ingest
  python scripts/tail.py crawler ingest spoke          # multiple at once
  python scripts/tail.py all                           # crawler + spoke + ingest
  python scripts/tail.py api
  python scripts/tail.py analysis

Options:
  --env staging|production   default: staging
  --since 5m|1h|2h|1d       how far back to start  default: 5m
  --region us-west-2         AWS region             default: us-west-2
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading

import boto3

# ── Colour palette ───────────────────────────────────────────────────────────

_COLOURS = {
    "crawler":  "\033[36m",   # cyan
    "spoke":    "\033[33m",   # yellow
    "ingest":   "\033[32m",   # green
    "api":      "\033[35m",   # magenta
    "analysis": "\033[34m",   # blue
}
_RESET = "\033[0m"
_RED   = "\033[31m"

# ── Log group discovery ──────────────────────────────────────────────────────
# Each key maps to a substring that uniquely identifies the log group.
# The CDK stack name follows the pattern SteamPulse-{Env}-{Suffix}{hash}.

# Each key maps to the suffix after /steampulse/{env}/ in the log group name.
_SUFFIXES: dict[str, str] = {
    "crawler":  "crawler",
    "ingest":   "ingest",
    "spoke":    "spoke",
    "api":      "api",
    "analysis": "analysis",
}

_ALIASES = {
    "all": ["crawler", "spoke", "ingest"],
}


def _resolve_log_groups(name: str, env: str, region: str) -> list[tuple[str, str]]:
    """Return [(label, log_group_name)] for the given stream name."""
    logs = boto3.client("logs", region_name=region)

    prefix = f"/steampulse/{env}/{_SUFFIXES[name]}"
    groups: list[str] = []
    paginator = logs.get_paginator("describe_log_groups")
    for page in paginator.paginate(logGroupNamePrefix=prefix):
        groups.extend(g["logGroupName"] for g in page["logGroups"])

    if not groups:
        print(f"{_RED}No log groups found for '{name}' in {env}/{region}{_RESET}", file=sys.stderr)
        return []

    if name == "spoke" and len(groups) > 1:
        return [(f"spoke({_spoke_region(g)})", g) for g in sorted(groups)]

    return [(name, groups[0])]


def _spoke_region(group_name: str) -> str:
    """Extract region from a spoke log group name."""
    # New format: /steampulse/{env}/spoke/{region}
    if group_name.startswith("/steampulse/"):
        return group_name.rsplit("/", 1)[-1]
    # Legacy format: SteamPulse-Staging-Spoke-us-west-2-SpokeLogs...
    parts = group_name.split("-")
    try:
        idx = parts.index("Spoke")
        return "-".join(parts[idx + 1 : idx + 4])
    except (ValueError, IndexError):
        return "?"


# ── Tailing ──────────────────────────────────────────────────────────────────


def _tail_stream(label: str, group: str, since: str, region: str, colour: str) -> None:
    """Run `aws logs tail` in a subprocess and prefix each line."""
    cmd = [
        "aws", "logs", "tail", group,
        "--follow",
        "--format", "short",
        "--since", since,
        "--region", region,
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        print(f"{_RED}aws CLI not found — install it and configure credentials{_RESET}", file=sys.stderr)
        return

    prefix = f"{colour}[{label}]{_RESET} "
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(prefix + line)
        sys.stdout.flush()


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    p = argparse.ArgumentParser(description="Tail SteamPulse Lambda log streams")
    p.add_argument(
        "streams",
        nargs="+",
        choices=[*_PREFIXES, *_ALIASES],
        metavar="STREAM",
        help=f"one or more of: {', '.join([*_PREFIXES, *_ALIASES])}",
    )
    p.add_argument("--env", default="staging", choices=["staging", "production"])
    p.add_argument("--since", default="5m", metavar="DURATION",
                   help="how far back to start, e.g. 5m 1h 2h 1d (default: 5m)")
    p.add_argument("--region", default="us-west-2")
    args = p.parse_args()

    # Expand aliases
    names: list[str] = []
    for s in args.streams:
        names.extend(_ALIASES.get(s, [s]))
    names = list(dict.fromkeys(names))  # deduplicate, preserve order

    # Resolve log groups
    targets: list[tuple[str, str]] = []
    for name in names:
        targets.extend(_resolve_log_groups(name, args.env, args.region))

    if not targets:
        sys.exit(1)

    print(f"Tailing {len(targets)} stream(s) — Ctrl-C to stop\n", file=sys.stderr)
    for label, group in targets:
        print(f"  {_COLOURS.get(label.split('(')[0], '')}[{label}]{_RESET}  {group}", file=sys.stderr)
    print(file=sys.stderr)

    threads = [
        threading.Thread(
            target=_tail_stream,
            args=(label, group, args.since, args.region, _COLOURS.get(label.split("(")[0], "")),
            daemon=True,
        )
        for label, group in targets
    ]

    for t in threads:
        t.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)


if __name__ == "__main__":
    main()
