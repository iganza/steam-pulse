"""CLI entry point for SteamPulse."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="steampulse",
        description="SteamPulse — AI-powered Steam review analytics",
    )
    parser.add_argument("--appid", type=int, required=True, help="Steam App ID to analyze")
    parser.add_argument(
        "--max-reviews",
        type=int,
        default=500,
        help="Maximum number of reviews to fetch (default: 500)",
    )
    parser.add_argument(
        "--all-reviews",
        action="store_true",
        help="Fetch all available reviews (overrides --max-reviews)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output HTML file path (default: {game_name}_steampulse.html)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch reviews only, skip LLM analysis",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print raw JSON to stdout instead of HTML",
    )
    return parser


async def _run(args: argparse.Namespace, console: Console) -> None:
    from steampulse.fetcher import fetch_app_metadata, fetch_reviews
    from steampulse.analyzer import analyze_reviews
    from steampulse.reporter import render_html_report, print_rich_report

    appid = args.appid

    console.print(f"[cyan]Fetching metadata for App ID {appid}...[/cyan]")
    try:
        meta = await fetch_app_metadata(appid)
    except RuntimeError as e:
        console.print(f"[red]Error fetching metadata: {e}[/red]")
        sys.exit(1)

    if meta is None:
        console.print(f"[red]App ID {appid} not found on Steam.[/red]")
        sys.exit(1)

    game_name = meta["name"]
    console.print(f"[green]Found:[/green] {game_name}")

    max_reviews = None if args.all_reviews else args.max_reviews
    fetch_label = "all" if max_reviews is None else str(max_reviews)
    console.print(f"[cyan]Fetching {fetch_label} reviews...[/cyan]")
    try:
        reviews = await fetch_reviews(appid, max_reviews=max_reviews)
    except RuntimeError as e:
        console.print(f"[red]Error fetching reviews: {e}[/red]")
        sys.exit(1)

    console.print(f"[green]Fetched {len(reviews)} reviews.[/green]")

    if args.dry_run:
        dry_path = f"{appid}_reviews.json"
        Path(dry_path).write_text(json.dumps(reviews, indent=2), encoding="utf-8")
        console.print(f"[yellow]Dry run complete. Reviews saved to {dry_path}[/yellow]")
        return

    if not reviews:
        console.print("[red]No English reviews found.[/red]")
        sys.exit(1)

    console.print("[cyan]Running LLM analysis (this may take 30-60s)...[/cyan]")
    try:
        result = await analyze_reviews(reviews, game_name, appid=appid)
    except Exception as e:
        console.print(f"[red]Analysis failed: {e}[/red]")
        sys.exit(1)

    result["header_image"] = meta.get("header_image", "")

    if args.output_json:
        print(json.dumps(result, indent=2))
        return

    print_rich_report(result, console=console)

    output_path = args.output or f"{game_name.replace(' ', '_')}_steampulse.html"
    render_html_report(result, output_path=output_path)
    console.print(f"\n[bold green]HTML report saved to:[/bold green] {output_path}")


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    console = Console()

    if not os.getenv("ANTHROPIC_API_KEY") and not args.dry_run:
        console.print(
            "[red]ANTHROPIC_API_KEY is not set. "
            "Add it to .env or export it before running.[/red]"
        )
        sys.exit(1)

    asyncio.run(_run(args, console))


if __name__ == "__main__":
    main()
