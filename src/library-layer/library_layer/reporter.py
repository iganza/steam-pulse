"""CLI report renderer — Jinja2 HTML and Rich terminal output."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

TEMPLATES_DIR = Path(__file__).parent / "templates"


def render_html_report(result: dict, output_path: str | None = None) -> str:
    """Render the analysis result to a standalone HTML file using the Jinja2 template."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("report.html.j2")
    html = template.render(**result)

    if output_path:
        Path(output_path).write_text(html, encoding="utf-8")

    return html


def print_rich_report(result: dict, console: Console | None = None) -> None:
    """Print a nicely formatted analysis report to the terminal using Rich."""
    if console is None:
        console = Console()

    game_name = result.get("game_name", "Unknown Game")
    sentiment = result.get("overall_sentiment", "Unknown")
    score = result.get("sentiment_score", 0.0)
    total = result.get("total_reviews_analyzed", 0)
    one_liner = result.get("one_liner", "")

    # Determine sentiment color
    score_color = "green" if score >= 0.7 else "yellow" if score >= 0.45 else "red"

    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]{game_name}[/bold cyan]\n"
            f"[{score_color}]{sentiment}[/{score_color}] — score: [{score_color}]{score:.0%}[/{score_color}] "
            f"([dim]{total} reviews analyzed[/dim])\n\n"
            f"[italic]{one_liner}[/italic]",
            title="[bold]SteamPulse Analysis[/bold]",
            border_style="cyan",
        )
    )

    # Top Praises
    praises = result.get("top_praises", [])
    if praises:
        console.print("\n[bold green]Top Praises[/bold green]")
        for p in praises:
            console.print(f"  [green]✓[/green] {p}")

    # Top Complaints
    complaints = result.get("top_complaints", [])
    if complaints:
        console.print("\n[bold red]Top Complaints[/bold red]")
        for c in complaints:
            console.print(f"  [red]✗[/red] {c}")

    # Feature Requests
    requests = result.get("feature_requests", [])
    if requests:
        console.print("\n[bold blue]Feature Requests[/bold blue]")
        for r in requests:
            console.print(f"  [blue]→[/blue] {r}")

    # Dev Action Items
    items = result.get("dev_action_items", [])
    if items:
        console.print("\n[bold yellow]Developer Action Items[/bold yellow]")
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("No.", style="dim", width=4)
        table.add_column("Action")
        for i, item in enumerate(items, 1):
            table.add_row(str(i), item)
        console.print(table)

    # Refund Risk
    risks = result.get("refund_risk_signals", [])
    if risks:
        console.print("\n[bold magenta]Refund Risk Signals[/bold magenta]")
        for r in risks:
            console.print(f"  [magenta]⚠[/magenta] {r}")

    # Competitive Mentions
    competitors = result.get("competitive_mentions", [])
    if competitors:
        console.print(f"\n[dim]Competitive mentions: {', '.join(competitors)}[/dim]")

    console.print()
