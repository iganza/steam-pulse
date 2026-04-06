#!/usr/bin/env python3
"""SteamPulse Admin TUI — launch the Textual admin interface.

Usage:
  poetry run python scripts/tui.py                    # local DB (DATABASE_URL from .env)
  poetry run python scripts/tui.py --env staging      # staging DB via tunnel + AWS ops
  poetry run python scripts/tui.py --env production   # production DB via tunnel + AWS ops
"""

import argparse
import os
import signal
import sys
import threading

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "library-layer"))
sys.path.insert(0, os.path.join(REPO_ROOT, "src", "lambda-functions"))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

# Watchdog: when the main thread signals quit, wait 2s then SIGKILL.
# This handles the case where boto3 C-level socket calls block os._exit.
_quit_event = threading.Event()


def _watchdog() -> None:
    _quit_event.wait()
    # Give Textual 2 seconds to shut down gracefully
    _quit_event.wait(timeout=2)
    os.kill(os.getpid(), signal.SIGKILL)


_watchdog_thread = threading.Thread(target=_watchdog, daemon=True)
_watchdog_thread.start()

signal.signal(signal.SIGINT, lambda *_: (_quit_event.set(), os._exit(0)))
signal.signal(signal.SIGTERM, lambda *_: (_quit_event.set(), os._exit(0)))


def main() -> None:
    parser = argparse.ArgumentParser(description="SteamPulse Admin TUI")
    parser.add_argument(
        "--env",
        choices=["staging", "production"],
        default=None,
        help="Connect to a deployed environment (requires SSH tunnel)",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    if args.env:
        env_file = os.path.join(REPO_ROOT, f".env.{args.env}")
        if os.path.exists(env_file):
            load_dotenv(env_file)
    else:
        load_dotenv(os.path.join(REPO_ROOT, ".env"))

    from tui.app import SteamPulseAdmin

    app = SteamPulseAdmin(env=args.env)
    app.run()

    # Trigger watchdog and force exit
    _quit_event.set()
    os._exit(0)


if __name__ == "__main__":
    main()
