#!/usr/bin/env python3
"""Auto-fill a SteamPulse genre deep-dive report from mv_genre_synthesis.

Pulls the existing LLM-synthesized genre data from the production Postgres and writes a partially-filled
.org file matching pdf_template_genre_deepdive_v2.org. Optionally generates matplotlib charts and
embeds them at the right sections.

Sections sourced from synthesis are pre-filled and marked `# [auto-filled — review]`.
Sections needing human authoring are marked `# [TODO: ...]`.

Requires the SSM tunnel to prod (scripts/dev/db-tunnel.sh --stage prod) running at localhost:5433.
For chart generation, requires `pip install matplotlib`.

Usage:
    python fill_report.py roguelike-deckbuilder
    python fill_report.py roguelike-deckbuilder --out state_of_roguelike_deckbuilder.org
    python fill_report.py roguelike-deckbuilder --no-charts
    python fill_report.py --list                     # list available genres
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from textwrap import shorten

PEM_PATH = Path.home() / "dev/git/saas/steam-pulse/global-bundle.pem"
CONN = (
    f"host=localhost port=5433 dbname=production_steampulse user=postgres "
    f"sslmode=verify-ca sslrootcert={PEM_PATH}"
)

# Visual identity for charts. Single accent + neutrals — no rainbow palette.
ACCENT = "#1F3A68"        # deep navy
ACCENT_LIGHT = "#5E7CB8"
ACCENT_MUTED = "#A8B5CC"
NEUTRAL = "#3D3D3D"
GRID = "#E5E5E5"
EFFORT_COLOR = {"low": "#4A8B4A", "medium": "#D49B3F", "high": "#B85450"}


# ---------------------------------------------------------------------------- #
# DB helpers
# ---------------------------------------------------------------------------- #

def psql(sql: str) -> str:
    """Run a SQL query via psql; return trimmed stdout. Exits on error."""
    proc = subprocess.run(
        ["psql", CONN, "-t", "-A", "-c", sql],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"psql failed:\n{proc.stderr}")
    return proc.stdout.strip()


def list_genres() -> None:
    rows = psql(
        "SELECT slug || E'\t' || display_name || E'\t' || input_count "
        "FROM mv_genre_synthesis ORDER BY input_count DESC"
    )
    if not rows:
        print("No genres found.")
        return
    print(f"{'slug':<30} {'display_name':<30} input_count")
    print("-" * 75)
    for line in rows.splitlines():
        slug, name, count = line.split("\t")
        print(f"{slug:<30} {name:<30} {count}")


def fetch_synthesis(slug: str) -> dict:
    sql = (
        "SELECT row_to_json(t) FROM ("
        "  SELECT slug, display_name, input_appids, input_count, prompt_version, "
        "         synthesis, narrative_summary, avg_positive_pct, median_review_count, "
        "         to_char(computed_at, 'YYYY-MM-DD') AS computed_at, "
        "         editorial_intro, churn_interpretation "
        f"  FROM mv_genre_synthesis WHERE slug = '{slug}'"
        ") t"
    )
    raw = psql(sql)
    if not raw:
        sys.exit(f"No synthesis row for slug '{slug}'. Try --list to see available.")
    return json.loads(raw)


def fetch_game_lookup(appids: list[int]) -> dict[int, dict]:
    """Resolve appid → name + review_count + positive_pct + price_usd + release_date."""
    if not appids:
        return {}
    appid_csv = ",".join(str(a) for a in appids)
    sql = (
        "SELECT COALESCE(json_agg(json_build_object("
        "  'appid', appid, 'name', name, 'review_count', review_count, "
        "  'positive_pct', positive_pct, "
        "  'price_usd', price_usd, "
        "  'release_date', to_char(release_date, 'YYYY-MM-DD')"
        f")), '[]') FROM games WHERE appid IN ({appid_csv})"
    )
    raw = psql(sql)
    games = json.loads(raw) if raw else []
    return {g["appid"]: g for g in games}


# ---------------------------------------------------------------------------- #
# Chart generation
# ---------------------------------------------------------------------------- #

def setup_chart_style() -> None:
    """Apply a clean professional matplotlib style. Call once before plotting."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import rcParams
    rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": NEUTRAL,
        "axes.labelcolor": NEUTRAL,
        "xtick.color": NEUTRAL,
        "ytick.color": NEUTRAL,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linestyle": "-",
        "grid.linewidth": 0.5,
        "figure.facecolor": "white",
        "figure.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.2,
    })


def _save(fig, out_path: Path) -> None:
    """Save figure as both PDF (vector for LaTeX) and PNG (for HTML/preview)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path.with_suffix(".pdf"))
    fig.savefig(out_path.with_suffix(".png"), dpi=150)
    import matplotlib.pyplot as plt
    plt.close(fig)


def chart_releases_per_year(games: list[dict], out: Path) -> bool:
    """Releases per year over the last 5 years for the genre's tracked games."""
    import matplotlib.pyplot as plt
    years: Counter = Counter()
    for g in games:
        rd = g.get("release_date")
        if not rd:
            continue
        try:
            y = int(rd[:4])
            if 1990 <= y <= date.today().year:
                years[y] += 1
        except ValueError:
            continue
    if not years:
        return False
    cur = date.today().year
    yrs = list(range(cur - 6, cur + 1))
    counts = [years.get(y, 0) for y in yrs]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(yrs, counts, color=ACCENT, linewidth=2, marker="o", markersize=6)
    ax.fill_between(yrs, counts, color=ACCENT_MUTED, alpha=0.3)
    ax.set_xlabel("Release year")
    ax.set_ylabel("Number of games released")
    ax.set_title("New releases per year in this genre", loc="left")
    ax.set_xticks(yrs)
    _save(fig, out)
    return True


def chart_price_distribution(games: list[dict], out: Path) -> bool:
    """Histogram of launch prices in USD."""
    import matplotlib.pyplot as plt
    prices = [float(g["price_usd"]) for g in games if g.get("price_usd") is not None]
    prices = [p for p in prices if 0 <= p <= 80]  # filter outliers
    if len(prices) < 5:
        return False
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(prices, bins=20, color=ACCENT, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Price (USD)")
    ax.set_ylabel("Number of games")
    ax.set_title("Launch price distribution across the genre", loc="left")
    median_price = sorted(prices)[len(prices) // 2]
    ax.axvline(median_price, color=NEUTRAL, linestyle="--", linewidth=1)
    ax.text(median_price, ax.get_ylim()[1] * 0.95, f"  median ${median_price:.2f}",
            color=NEUTRAL, fontsize=9, va="top")
    _save(fig, out)
    return True


def chart_friction_counts(friction_points: list[dict], out: Path) -> bool:
    """Horizontal bar chart of friction clusters by mention count."""
    import matplotlib.pyplot as plt
    if not friction_points:
        return False
    fps = sorted(friction_points, key=lambda x: x["mention_count"])  # ascending for h-bar
    titles = [shorten(fp["title"], width=70, placeholder="…") for fp in fps]
    counts = [fp["mention_count"] for fp in fps]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.45 * len(fps) + 1)))
    bars = ax.barh(titles, counts, color=ACCENT)
    ax.set_xlabel("Number of games mentioning this friction")
    ax.set_title("Friction clusters by mention count", loc="left")
    ax.bar_label(bars, padding=4, fontsize=9, color=NEUTRAL)
    ax.set_xlim(0, max(counts) * 1.12)
    _save(fig, out)
    return True


def chart_wishlist_counts(wishlist_items: list[dict], out: Path) -> bool:
    """Horizontal bar chart of wishlist signals by mention count."""
    import matplotlib.pyplot as plt
    if not wishlist_items:
        return False
    wis = sorted(wishlist_items, key=lambda x: x["mention_count"])
    titles = [shorten(wi["title"], width=70, placeholder="…") for wi in wis]
    counts = [wi["mention_count"] for wi in wis]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.45 * len(wis) + 1)))
    bars = ax.barh(titles, counts, color=ACCENT_LIGHT)
    ax.set_xlabel("Number of games mentioning this wishlist signal")
    ax.set_title("Wishlist signals by mention count", loc="left")
    ax.bar_label(bars, padding=4, fontsize=9, color=NEUTRAL)
    ax.set_xlim(0, max(counts) * 1.12)
    _save(fig, out)
    return True


def chart_dev_priorities(dev_priorities: list[dict], out: Path) -> bool:
    """Horizontal bar chart of dev priorities by mention count, colored by effort tier."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    if not dev_priorities:
        return False
    dps = sorted(dev_priorities, key=lambda x: x["frequency"])  # ascending for h-bar
    titles = [shorten(dp["action"], width=70, placeholder="…") for dp in dps]
    counts = [dp["frequency"] for dp in dps]
    colors = [EFFORT_COLOR.get(dp.get("effort", "medium"), ACCENT) for dp in dps]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.5 * len(dps) + 1.2)))
    bars = ax.barh(titles, counts, color=colors)
    ax.set_xlabel("Number of games where this priority surfaces")
    ax.set_title("Ranked dev priorities — mention count, colored by implementation effort", loc="left")
    ax.bar_label(bars, padding=4, fontsize=9, color=NEUTRAL)
    ax.set_xlim(0, max(counts) * 1.12)
    legend_elems = [
        Patch(facecolor=EFFORT_COLOR["low"], label="Low effort"),
        Patch(facecolor=EFFORT_COLOR["medium"], label="Medium effort"),
        Patch(facecolor=EFFORT_COLOR["high"], label="High effort"),
    ]
    ax.legend(handles=legend_elems, loc="lower right", frameon=False, fontsize=9)
    _save(fig, out)
    return True


def chart_positive_pct_distribution(games: list[dict], out: Path) -> bool:
    """Histogram of positive_pct across the genre dataset (methodology section)."""
    import matplotlib.pyplot as plt
    pcts = [g["positive_pct"] for g in games if g.get("positive_pct") is not None]
    if len(pcts) < 5:
        return False
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(pcts, bins=20, range=(0, 100), color=ACCENT, edgecolor="white", linewidth=0.5)
    ax.set_xlabel("Positive review percentage")
    ax.set_ylabel("Number of games")
    ax.set_title("Positive-review percentage distribution across analyzed games", loc="left")
    ax.set_xlim(0, 100)
    _save(fig, out)
    return True


def chart_top_games_by_reviews(games: list[dict], out: Path, n: int = 10) -> bool:
    """Horizontal bar chart of top N games by review count (genre stars)."""
    import matplotlib.pyplot as plt
    ranked = sorted(
        [g for g in games if g.get("review_count")],
        key=lambda g: g["review_count"], reverse=True,
    )[:n]
    if not ranked:
        return False
    ranked.reverse()  # ascending for h-bar bottom-up
    names = [shorten(g["name"], width=40, placeholder="…") for g in ranked]
    counts = [g["review_count"] for g in ranked]
    fig, ax = plt.subplots(figsize=(8, max(3.5, 0.4 * n + 1)))
    bars = ax.barh(names, counts, color=ACCENT)
    ax.set_xlabel("Total review count")
    ax.set_title(f"Top {n} games in this genre by review count", loc="left")
    ax.bar_label(bars, padding=4, fontsize=9, color=NEUTRAL,
                 fmt=lambda v: f"{int(v):,}")
    ax.set_xlim(0, max(counts) * 1.18)
    _save(fig, out)
    return True


def generate_charts(syn: dict, lookup: dict, charts_dir: Path,
                    rel_charts_path: str, computed_at: str) -> dict[str, dict]:
    """Generate all charts.

    `charts_dir`        — filesystem path where chart files are written.
    `rel_charts_path`   — path used in org file embeds (relative to the .org file).

    Returns a dict keyed by chart_id with metadata for embedding.
    """
    setup_chart_style()
    games = list(lookup.values())
    s = syn["synthesis"]
    out: dict[str, dict] = {}

    def maybe(chart_id: str, fname: str, ok: bool, caption: str, source: str) -> None:
        if ok:
            out[chart_id] = {
                "path": f"{rel_charts_path}/{fname}",
                "caption": caption,
                "source": source,
            }

    maybe("releases_per_year", "releases_per_year",
          chart_releases_per_year(games, charts_dir / "releases_per_year"),
          f"New releases per year in the {syn['display_name']} genre.",
          f"Source: SteamPulse, release_date for {syn['input_count']} games, {computed_at}.")

    maybe("price_distribution", "price_distribution",
          chart_price_distribution(games, charts_dir / "price_distribution"),
          f"Launch price distribution across {syn['display_name']} games.",
          f"Source: SteamPulse, current Steam price for {syn['input_count']} games, {computed_at}.")

    maybe("friction_counts", "friction_counts",
          chart_friction_counts(s.get("friction_points", []), charts_dir / "friction_counts"),
          f"Friction clusters in {syn['display_name']} by cross-game mention count.",
          f"Source: SteamPulse synthesis of {syn['input_count']} games' reviews, {computed_at}.")

    maybe("wishlist_counts", "wishlist_counts",
          chart_wishlist_counts(s.get("wishlist_items", []), charts_dir / "wishlist_counts"),
          f"Wishlist signals in {syn['display_name']} by cross-game mention count.",
          f"Source: SteamPulse synthesis of {syn['input_count']} games' reviews, {computed_at}.")

    maybe("dev_priorities", "dev_priorities",
          chart_dev_priorities(s.get("dev_priorities", []), charts_dir / "dev_priorities"),
          f"Ranked dev priorities for {syn['display_name']} — implementation effort vs cross-game demand.",
          f"Source: SteamPulse synthesis of {syn['input_count']} games' dev_priorities, {computed_at}.")

    maybe("positive_pct_distribution", "positive_pct_distribution",
          chart_positive_pct_distribution(games, charts_dir / "positive_pct_distribution"),
          f"Distribution of Steam positive-review percentages across the {syn['input_count']} games analyzed.",
          f"Source: SteamPulse, Steam review_score data, {computed_at}.")

    maybe("top_games_by_reviews", "top_games_by_reviews",
          chart_top_games_by_reviews(games, charts_dir / "top_games_by_reviews"),
          f"Top 10 games in {syn['display_name']} by total Steam review count.",
          f"Source: SteamPulse, Steam review_count data, {computed_at}.")

    return out


# ---------------------------------------------------------------------------- #
# Rendering helpers
# ---------------------------------------------------------------------------- #

def game_name(appid: int, lookup: dict[int, dict]) -> str:
    g = lookup.get(appid)
    return g["name"] if g else f"(appid {appid})"


def quote_block(text: str, source_appid: int, lookup: dict[int, dict]) -> str:
    name = game_name(source_appid, lookup)
    return (
        "#+begin_quote\n"
        f"/{text}/\n\n"
        f"— quoted from /{name}/\n"
        "#+end_quote"
    )


def figure_block(chart: dict, name: str) -> str:
    """Render an org figure block (#+CAPTION + #+ATTR_LATEX + image link)."""
    return (
        f"#+CAPTION: {chart['caption']}\n"
        f"#+CAPTION: {chart['source']}\n"
        f"#+ATTR_LATEX: :width 0.9\\textwidth :placement [H]\n"
        f"#+NAME: fig:{name}\n"
        f"[[file:{chart['path']}.pdf]]\n"
    )


def render_friction(idx: int, fp: dict, lookup: dict[int, dict]) -> str:
    return (
        f"*** {fp['title']}\n"
        f"{fp['description']}\n\n"
        f"Mentioned in {fp['mention_count']} games in the dataset.\n\n"
        f"{quote_block(fp['representative_quote'], fp['source_appid'], lookup)}\n\n"
        f"# [TODO: add 2 more verbatim quotes from other games; name 1-2 games that solved this; "
        f"name 1-2 games that haven't; one-line actionable takeaway for builders]\n"
    )


def render_wishlist(idx: int, wi: dict, lookup: dict[int, dict]) -> str:
    return (
        f"*** {wi['title']}\n"
        f"{wi['description']}\n\n"
        f"Mentioned in {wi['mention_count']} games in the dataset.\n\n"
        f"{quote_block(wi['representative_quote'], wi['source_appid'], lookup)}\n\n"
        f"# [TODO: which games partially deliver this and how; why no one has fully delivered "
        f"(technical/cost/business model); estimated demand size]\n"
    )


def render_priority(idx: int, dp: dict, lookup: dict[int, dict]) -> str:
    return (
        f"*** {idx}. {dp['action']}\n"
        f"*Effort:* {dp['effort']} | *Mentioned by:* {dp['frequency']} games\n\n"
        f"{dp['why_it_matters']}\n\n"
        f"# [TODO: cite the specific friction/wishlist cluster this addresses; "
        f"name 1-2 games that did this well, with one quote]\n"
    )


def render_benchmark(b: dict) -> str:
    return (
        f"** {b['name']} (appid {b['appid']})\n"
        f"{b['why_benchmark']}\n\n"
        f"# [TODO: full 1-page profile — dev, publisher, launch year, price, est units/revenue, "
        f"review %, standout strength + quote, standout weakness + quote, design move to learn]\n"
    )


def render_games_table(appids: list[int], lookup: dict[int, dict]) -> str:
    rows = []
    for appid in appids:
        g = lookup.get(appid, {"appid": appid, "name": f"(appid {appid})",
                               "review_count": None, "positive_pct": None})
        rows.append(g)
    rows.sort(key=lambda r: (r.get("review_count") or 0), reverse=True)
    lines = ["| Appid | Name | Reviews | Positive % |", "|-------+------+---------+------------|"]
    for r in rows:
        rc = r["review_count"] if r["review_count"] is not None else "—"
        pp = f"{r['positive_pct']}%" if r["positive_pct"] is not None else "—"
        lines.append(f"| {r['appid']} | {r['name']} | {rc} | {pp} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------- #
# Main template assembly
# ---------------------------------------------------------------------------- #

def render_report(syn: dict, lookup: dict[int, dict], charts: dict[str, dict]) -> str:
    s = syn["synthesis"]
    display = syn["display_name"]
    fps = s.get("friction_points", [])[:8]
    wis = s.get("wishlist_items", [])[:6]
    dps = s.get("dev_priorities", [])[:10]
    benchmarks = s.get("benchmark_games", [])
    churn = s.get("churn_insight", {})
    narrative = s.get("narrative_summary", "")

    out: list[str] = []
    e = out.append

    def fig(chart_id: str, name: str) -> None:
        if chart_id in charts:
            e(figure_block(charts[chart_id], name))

    # ----- front matter -------------------------------------------------- #
    e(f"#+TITLE: STATE OF {display.upper()} — A SteamPulse Deep Dive")
    e("#+SUBTITLE: # [TODO: write a one-line subtitle naming the genre's central tension]")
    e("#+AUTHOR: [Your name], SteamPulse Research")
    e("#+DATE: [Month Year]")
    e("#+OPTIONS: toc:nil num:nil ^:nil")
    e("#+LATEX_CLASS: report")
    e("#+LATEX_CLASS_OPTIONS: [11pt,letterpaper]")
    e("#+LATEX_HEADER: \\usepackage[margin=1in]{geometry}")
    e("#+LATEX_HEADER: \\usepackage{titling}")
    e("#+LATEX_HEADER: \\usepackage{fancyhdr}")
    e("#+LATEX_HEADER: \\usepackage{tcolorbox}")
    e("#+LATEX_HEADER: \\usepackage{float}")
    e("#+LATEX_HEADER: \\pagestyle{fancy}")
    e(f"#+LATEX_HEADER: \\fancyfoot[C]{{\\thepage \\quad | \\quad SteamPulse — State of {display} "
      f"— v1.0 — Confidential}}")
    e("")
    e(f"# Auto-filled from mv_genre_synthesis on {syn['computed_at']}. "
      f"Source: prompt_version={syn['prompt_version']}, input_count={syn['input_count']}.")
    e("# Export to PDF: C-c C-e l p")
    e("")

    # ----- At a Glance --------------------------------------------------- #
    e("* At a Glance")
    e("# [auto-filled — review and polish]")
    e("")
    e("*At a Glance*")
    e("")
    if fps:
        top_fp = fps[0]
        e(f"1. The #1 friction across the genre — *{top_fp['title']}* — was mentioned in "
          f"{top_fp['mention_count']} of the {syn['input_count']} games analyzed.")
    if wis:
        top_wi = wis[0]
        e(f"2. The most-requested feature in player wishlists — *{top_wi['title']}* — appears in "
          f"{top_wi['mention_count']} games' reviews.")
    if churn:
        hour = churn.get("typical_dropout_hour", 0)
        e(f"3. Median player churn occurs at hour *{hour:g}*. Primary reason: "
          f"{churn.get('primary_reason', '').split('.')[0]}.")
    if benchmarks:
        names = ", ".join(b["name"] for b in benchmarks[:3])
        e(f"4. The benchmark games that anchor this niche: *{names}*.")
    if dps:
        top_dp = dps[0]
        e(f"5. The single highest-impact design move per the dev-priorities ranking: "
          f"*{top_dp['action']}* (mentioned by {top_dp['frequency']} games, effort: {top_dp['effort']}).")
    e(f"6. Dataset: {syn['input_count']} games analyzed; average positive review % is "
      f"{float(syn['avg_positive_pct']):.0f}%; median review count {syn['median_review_count']}.")
    e("7. # [TODO: write a 7th headline finding, or trim to 6]")
    e("")

    # ----- How to read --------------------------------------------------- #
    e("* How to read this report")
    e("# [auto-filled — narrative_summary from synthesis. Polish phrasing as needed.]")
    e("")
    e(narrative)
    e("")
    if syn.get("editorial_intro"):
        e("# [editorial_intro from operator curation:]")
        e(syn["editorial_intro"])
        e("")
    e("# [TODO: add the orientation paragraph — Section 1 maps the market; Section 2 maps the players; "
      "Section 3 is the heart (friction + wishlist + promise gap, all quote-grounded); Section 4 is the "
      "playbook with ranked priorities; appendix has methodology + games included + glossary.]")
    e("")
    e("# [TODO: insert the methodology snapshot — 4-5 sentences on source, time window, total reviews, "
      "synthesis method.]")
    e("")

    # ----- Section 1 — Market ------------------------------------------- #
    e("* SECTION 1 — THE MARKET")
    e("")
    e("** At a Glance — The Market")
    e("# [TODO: 4 bullets summarizing market size, growth, pricing, recent dynamics]")
    e("")
    e("** Market size and growth")
    e("# [auto-filled chart below — add prose context, total games tagged, revenue estimates]")
    e("")
    fig("releases_per_year", "releases-per-year")
    e("# [TODO: add prose framing the chart — what the trend means, comparison to adjacent genres, "
      "estimated total revenue (Boxleiter or similar), median + top-decile + top-percentile per game]")
    e("")
    e("** Pricing and discounting")
    e("# [auto-filled chart below — add prose context, discounting cadence, F2P presence]")
    e("")
    fig("price_distribution", "price-distribution")
    e("# [TODO: median first-discount delay + depth, F2P presence, monetization patterns]")
    e("")
    e("** Recent wins and recent losses")
    e("# [TODO: 3 biggest hits + 3 most expensive failures of last 12 months. For each: title, what "
      "worked or didn't, one quote, one outcome number]")
    e("")
    e("** Implications for The Market")
    e("# [TODO: 3-4 sentences. For builders: go/no-go on entering. For publishers: what to greenlight. "
      "For investors: where the upside sits.]")
    e("")

    # ----- Section 2 — Players ------------------------------------------ #
    e("* SECTION 2 — THE PLAYERS")
    e("")
    e("** At a Glance — The Players")
    e("# [TODO: 4 bullets on who plays, churn timing, audience overlap]")
    e("")
    e("** Who plays this genre")
    e("# [TODO: not in genre synthesis — inferred from review behavior: average reviewer playtime at "
      "review point, playtime distribution (short-stop vs deep-engagement curves), revealed preferences "
      "from review language]")
    e("")
    e("** The churn wall")
    e("# [auto-filled from churn_insight — expand with histogram + multiple reasons]")
    e("")
    if churn:
        hour = churn.get("typical_dropout_hour", 0)
        reason = churn.get("primary_reason", "")
        quote = churn.get("representative_quote", "")
        src = churn.get("source_appid")
        e(f"Median player drop-off in this genre occurs at hour *{hour:g}*.")
        e("")
        e("The primary reason cited across the dataset:")
        e("")
        e(reason)
        e("")
        if quote and src is not None:
            e(quote_block(quote, src, lookup))
            e("")
    if syn.get("churn_interpretation"):
        e("# [churn_interpretation from operator curation:]")
        e(syn["churn_interpretation"])
        e("")
    e("# [TODO: add drop-off-hour histogram chart (needs raw playtime data, not in synthesis). "
      "Add 3-5 reasons cited in churn-window reviews, each with a verbatim quote. "
      "Compare top-performers' churn vs genre median.]")
    e("")
    e("** Audience overlap")
    e("# [TODO: not in genre synthesis — pull from audience overlap matview: top 10 audience-overlap "
      "genres; one paragraph per top-3 overlap with marketing implication; specific games that "
      "successfully cross-marketed]")
    e("")
    e("** Implications for The Players")
    e("# [TODO: 3-4 prescriptive sentences]")
    e("")

    # ----- Section 3 — Friction & Opportunity --------------------------- #
    e("* SECTION 3 — THE FRICTION & THE OPPORTUNITY")
    e("")
    e("** At a Glance — Friction & Opportunity")
    e("# [auto-filled — top friction + wishlist titles. Polish to flowing bullets.]")
    e("")
    for fp in fps[:2]:
        e(f"- *Friction:* {fp['title']} ({fp['mention_count']} games)")
    for wi in wis[:2]:
        e(f"- *Wishlist:* {wi['title']} ({wi['mention_count']} games)")
    e("")
    e("** Friction clusters")
    e(f"# [auto-filled — top {len(fps)} friction clusters from synthesis. Each needs: 2 more quotes, "
      f"games-that-solved, games-that-haven't, takeaway. Trim to 5-8 if needed.]")
    e("")
    fig("friction_counts", "friction-counts")
    for i, fp in enumerate(fps, start=1):
        e(render_friction(i, fp, lookup))
    e("** Wishlist signals")
    e(f"# [auto-filled — top {len(wis)} wishlist signals from synthesis. Each needs: which games "
      f"partially deliver, why nobody has fully delivered, demand-size estimate.]")
    e("")
    fig("wishlist_counts", "wishlist-counts")
    for i, wi in enumerate(wis, start=1):
        e(render_wishlist(i, wi, lookup))
    e("** The promise gap")
    e("# [TODO: not in genre synthesis — derive from store-page text vs review themes. The 3-5 most "
      "common 'I expected X, got Y' themes; quote pairs (store copy + contradicting review); "
      "marketing implications.]")
    e("")
    e("** Implications for Friction & Opportunity")
    e("# [TODO: 4-5 prescriptive sentences pointing to Section 4 — the most important Implications "
      "section in the report.]")
    e("")

    # ----- Section 4 — Playbook ----------------------------------------- #
    e("* SECTION 4 — THE PLAYBOOK")
    e("")
    e("** At a Glance — The Playbook")
    e("# [auto-filled from top dev priorities]")
    e("")
    for dp in dps[:4]:
        e(f"- {dp['action']}")
    e("")
    e("** Ranked priorities for builders")
    e(f"# [auto-filled — {len(dps)} dev priorities from synthesis. Each needs: cite the friction or "
      f"wishlist cluster that motivates it; name 1-2 games that did this well with one quote.]")
    e("")
    fig("dev_priorities", "dev-priorities")
    for i, dp in enumerate(dps, start=1):
        e(render_priority(i, dp, lookup))
    e("** Opportunity map")
    e("# [TODO: 2x2 chart — wishlist demand (mention counts from Section 3) on X axis, current market "
      "supply (count of top-50 games delivering each wish) on Y axis. Annotate top 3 opportunities in "
      "the high-demand low-supply quadrant. Supply data needs human estimation per wishlist signal.]")
    e("")
    e("** What to avoid")
    e("# [auto-filled (partial) — inverse of top friction clusters. Add specific game examples + quotes.]")
    e("")
    e("The most common mistakes builders make in this genre — each is the inverse of a friction "
      "cluster from Section 3:")
    e("")
    for i, fp in enumerate(fps[:5], start=1):
        e(f"{i}. *Don't ship {fp['title'].lower()}* — see Section 3 for the full pattern. "
          f"# [TODO: add a specific game that fell into this trap, with one quote.]")
    e("")
    e("** Implications for The Playbook")
    e("# [TODO: closing prescriptive paragraph for the report's main body.]")
    e("")

    # ----- Appendix A — Benchmarks -------------------------------------- #
    e("* APPENDIX A — Benchmark game profiles")
    e(f"# [auto-filled — {len(benchmarks)} benchmark games from synthesis. Each needs: full 1-page "
      f"profile with dev, publisher, launch, price, est units/revenue, review %, strength + quote, "
      f"weakness + quote, design move to learn.]")
    e("")
    fig("top_games_by_reviews", "top-games-by-reviews")
    for b in benchmarks:
        e(render_benchmark(b))

    # ----- Appendix B — Methodology ------------------------------------- #
    e("* APPENDIX B — Methodology")
    e("# [auto-filled — verify and customize]")
    e("")
    e(f"This report synthesizes player-stated signal from *{syn['input_count']} games* tagged "
      f"\"{display}\" on Steam, analyzed via the SteamPulse 3-phase LLM pipeline ("
      f"prompt_version={syn['prompt_version']}). Synthesis computed: {syn['computed_at']}.")
    e("")
    e("*Coverage:*")
    e(f"- Games included: {syn['input_count']} (full list in Appendix C)")
    e(f"- Average positive-review percentage across the dataset: {float(syn['avg_positive_pct']):.0f}%")
    e(f"- Median review count per included game: {syn['median_review_count']}")
    e("")
    fig("positive_pct_distribution", "positive-pct-distribution")
    e("# [TODO: full methodology — inclusion criteria (specific tag rules), review sample size + "
      "language filter, exclusions (non-English, pre-release, refund-window), explicit limitations "
      "(vocal-minority bias, refund-window distortion, free-weekend skew). Confidence framing: this "
      "is a synthesis of player-stated preferences, not behavioral telemetry — we report what "
      "players say, with the quotes to back it up.]")
    e("")

    # ----- Appendix C — Games included ---------------------------------- #
    e("* APPENDIX C — Games included in this analysis")
    e("# [auto-filled from input_appids joined to games table]")
    e("")
    e(render_games_table(syn["input_appids"], lookup))
    e("")

    # ----- Appendix D — Glossary ---------------------------------------- #
    e("* APPENDIX D — Glossary")
    e("# [TODO: define SteamPulse-distinctive framing words — *churn wall*, *promise gap*, "
      "*friction cluster*, *wishlist signal*, *opportunity map*. Brand them deliberately.]")
    e("")

    # ----- About -------------------------------------------------------- #
    e("* About SteamPulse")
    e("")
    e("** What this report is")
    e("# [TODO: 1 paragraph — boilerplate, reuse across reports. SteamPulse turns the unstructured "
      "voice of millions of Steam reviews into structured, decision-ready intelligence. Every claim "
      "is grounded in quoted player evidence.]")
    e("")
    e("** Commission custom research")
    e("# [TODO: 1 paragraph + contact line. Pitch the $5K-$25K commissioned tier. Confident, brief.]")
    e("")
    e("** Other reports in this series")
    e("# [TODO: 3-4 line catalog with prices.]")
    e("")
    e("** Newsletter")
    e("# [TODO: 1 line + signup link.]")
    e("")

    return "\n".join(out)


# ---------------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------------- #

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("slug", nargs="?", help="Genre slug (e.g. roguelike-deckbuilder)")
    p.add_argument("--out", help="Output .org path "
                                 "(default: reports/state_of_<slug>/state_of_<slug>.org)")
    p.add_argument("--list", action="store_true", help="List available genres and exit")
    p.add_argument("--no-charts", action="store_true",
                   help="Skip matplotlib chart generation (faster, no matplotlib needed)")
    p.add_argument("--charts-dir", help="Directory for chart files "
                                        "(default: <out_dir>/charts/)")
    args = p.parse_args()

    if args.list:
        list_genres()
        return
    if not args.slug:
        p.print_help()
        sys.exit(1)

    print(f"Fetching synthesis for '{args.slug}'...", file=sys.stderr)
    syn = fetch_synthesis(args.slug)
    print(f"  display_name : {syn['display_name']}", file=sys.stderr)
    print(f"  input_count  : {syn['input_count']}", file=sys.stderr)
    print(f"  computed_at  : {syn['computed_at']}", file=sys.stderr)

    print(f"Fetching {len(syn['input_appids'])} game records...", file=sys.stderr)
    lookup = fetch_game_lookup(syn["input_appids"])
    print(f"  resolved {len(lookup)}/{len(syn['input_appids'])} games", file=sys.stderr)

    report_name = f"state_of_{args.slug.replace('-', '_')}"
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path("reports") / report_name / f"{report_name}.org"
    report_dir = out_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)

    charts_dir = Path(args.charts_dir) if args.charts_dir else report_dir / "charts"
    rel = os.path.relpath(charts_dir, report_dir)
    rel_charts_path = rel if rel.startswith((".", "/")) else f"./{rel}"

    charts: dict[str, dict] = {}
    if not args.no_charts:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            sys.exit("matplotlib not installed. Either run `pip install matplotlib` or pass --no-charts.")
        print(f"Generating charts → {charts_dir}/", file=sys.stderr)
        charts = generate_charts(syn, lookup, charts_dir, rel_charts_path, syn["computed_at"])
        for cid in charts:
            print(f"  ✓ {cid}", file=sys.stderr)

    content = render_report(syn, lookup, charts)
    out_path.write_text(content)

    s = syn["synthesis"]
    print(f"\nWrote {out_path}", file=sys.stderr)
    print(f"  friction clusters auto-filled : {min(8, len(s.get('friction_points', [])))}", file=sys.stderr)
    print(f"  wishlist signals auto-filled  : {min(6, len(s.get('wishlist_items', [])))}", file=sys.stderr)
    print(f"  dev priorities auto-filled    : {min(10, len(s.get('dev_priorities', [])))}", file=sys.stderr)
    print(f"  benchmark games auto-filled   : {len(s.get('benchmark_games', []))}", file=sys.stderr)
    print(f"  charts embedded               : {len(charts)}", file=sys.stderr)
    print(f"\nGrep '# [TODO' to see sections still needing human authoring.", file=sys.stderr)


if __name__ == "__main__":
    main()
