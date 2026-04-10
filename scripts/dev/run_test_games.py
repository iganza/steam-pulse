#!/usr/bin/env python3
"""Run the three-phase analyzer across all games in doc/test_games.org.

Parses the org-mode table for appids, then runs `run_phase.py` for each
one sequentially. Skips games that already have a report (unless --force).
On failure, logs the error and continues to the next game.

Usage:
    # Run all 50 games through synthesis (chunk + merge cached = fast)
    poetry run python scripts/dev/run_test_games.py

    # Run only chunk phase across all games
    poetry run python scripts/dev/run_test_games.py --phase chunk

    # Force re-run even if a report already exists
    poetry run python scripts/dev/run_test_games.py --force

    # Limit to first N games (useful for smoke testing)
    poetry run python scripts/dev/run_test_games.py --limit 5

    # Start from a specific game number (1-indexed, matches the org table)
    poetry run python scripts/dev/run_test_games.py --start 15
"""

import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
sys.path.insert(0, str(_REPO_ROOT / "src" / "library-layer"))
sys.path.insert(0, str(_REPO_ROOT / "src" / "lambda-functions"))

_ORG_FILE = _REPO_ROOT / "doc" / "test_games.org"
_RUN_PHASE = _REPO_ROOT / "scripts" / "dev" / "run_phase.py"


def _parse_appids(path: Path) -> list[tuple[int, str]]:
    """Extract (appid, game_name) tuples from the org table."""
    results: list[tuple[int, str]] = []
    for line in path.read_text().splitlines():
        # Match table rows: | N | Game Name | AppId | ...
        m = re.match(r"^\|\s*\d+\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|", line)
        if m:
            name = m.group(1).strip()
            appid = int(m.group(2))
            results.append((appid, name))
    return results


def _has_report(appid: int) -> bool:
    from library_layer.repositories.report_repo import ReportRepository
    from library_layer.utils.db import get_conn

    repo = ReportRepository(get_conn)
    return repo.find_by_appid(appid) is not None


def _has_game(appid: int) -> bool:
    from library_layer.repositories.game_repo import GameRepository
    from library_layer.utils.db import get_conn

    repo = GameRepository(get_conn)
    return repo.find_by_appid(appid) is not None


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--phase", default="synthesis", choices=("chunk", "merge", "synthesis"))
    p.add_argument("--force", action="store_true", help="Re-run even if a report exists")
    p.add_argument("--limit", type=int, default=None, help="Process only the first N games")
    p.add_argument("--start", type=int, default=1, help="Start from game number N (1-indexed)")
    p.add_argument("--max-reviews", type=int, default=None)
    args = p.parse_args()

    games = _parse_appids(_ORG_FILE)
    if not games:
        print(f"ERROR: no appids found in {_ORG_FILE}")
        sys.exit(1)

    # Slice by --start (1-indexed) and --limit
    games = games[args.start - 1 :]
    if args.limit is not None:
        games = games[: args.limit]

    print(f"▶ Processing {len(games)} game(s), phase={args.phase}, force={args.force}\n")

    succeeded = 0
    skipped = 0
    failed: list[tuple[int, str, str]] = []

    for i, (appid, name) in enumerate(games, 1):
        print(f"━━━ [{i}/{len(games)}] {name} (appid={appid}) ━━━")

        if not _has_game(appid):
            print("  SKIP — not in local DB. Run import_from_prod.py first.\n")
            skipped += 1
            continue

        if not args.force and args.phase == "synthesis" and _has_report(appid):
            print("  SKIP — report already exists. Use --force to re-run.\n")
            skipped += 1
            continue

        cmd = [
            sys.executable,
            str(_RUN_PHASE),
            "--appid", str(appid),
            "--phase", args.phase,
        ]
        if args.max_reviews is not None:
            cmd += ["--max-reviews", str(args.max_reviews)]

        try:
            subprocess.run(cmd, check=True)
            succeeded += 1
            print()
        except subprocess.CalledProcessError as exc:
            reason = f"exit code {exc.returncode}"
            print(f"  FAILED — {reason}\n")
            failed.append((appid, name, reason))
        except KeyboardInterrupt:
            print(f"\n\nInterrupted at game {i}/{len(games)}.")
            break

    print("━━━ Summary ━━━")
    print(f"  Succeeded: {succeeded}")
    print(f"  Skipped:   {skipped}")
    print(f"  Failed:    {len(failed)}")
    if failed:
        for appid, name, reason in failed:
            print(f"    - {name} ({appid}): {reason}")
    print(f"\nRe-run failed games with: --start N (check game number in {_ORG_FILE})")


if __name__ == "__main__":
    main()
