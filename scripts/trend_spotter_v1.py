"""Trend Spotter v1: scan the Steam catalog for tags accelerating before supply piles in."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import anthropic
import psycopg2
import psycopg2.extensions
import psycopg2.extras
from pydantic import BaseModel

REPORTS_DIR = Path("reports/trend_spotter")
MODEL = "claude-opus-4-7"

DEFAULT_TOP = 20
DEFAULT_VOLUME_FLOOR = 10
WINDOW_QUARTERS = 4
COOLING_CAP = 5

WINNER_REVIEW_FLOOR = 500
WINNER_REVIEW_CEIL = 5000
WINNER_POSITIVE_FLOOR = 80

W_HIT_LIFT = 0.35
W_QUALITY = 0.20
W_SUPPLY = 0.20
W_VOLUME = 0.10
W_NON_F2P = 0.15

HIT_LIFT_FULL = 0.10
QUALITY_LIFT_LO = -0.5
QUALITY_LIFT_FULL = 10.0
SUPPLY_LO = -0.20
SUPPLY_PEAK_LO = 0.0
SUPPLY_PEAK_HI = 0.50
SUPPLY_HI = 2.0
VOLUME_RAMP = 60
F2P_HARD_CUT = 70.0
F2P_PARTIAL_CUT = 30.0

DISQUAL_RELEASE_GROWTH_YOY = 2.0
DISQUAL_RELEASE_GROWTH_2YR = 4.0

AAA_DEVELOPERS = {
    "Valve",
    "Riot Games",
    "Activision",
    "Activision Blizzard",
    "Blizzard Entertainment",
    "Electronic Arts",
    "EA",
    "EA Sports",
    "Ubisoft",
    "Ubisoft Montreal",
    "Take-Two Interactive",
    "Rockstar Games",
    "2K",
    "Microsoft",
    "Microsoft Studios",
    "Xbox Game Studios",
    "Sony",
    "Sony Interactive Entertainment",
    "Nintendo",
    "Tencent",
    "Bethesda Softworks",
    "Bethesda Game Studios",
    "Square Enix",
    "Capcom",
    "Bandai Namco Entertainment",
    "Sega",
    "Konami",
    "Warner Bros. Games",
    "Bungie",
}

BATCH_POLL_SECONDS = 30
MAX_TOKENS = 6144

GENRE_FILTER_NONE = ""


class TagWindowStats(BaseModel):
    releases: int
    velocity_50_plus: int
    velocity_10_50: int
    positive_count: int
    mixed_count: int
    negative_count: int
    avg_steam_pct: float
    median_price: float
    free_pct: float


class TagMomentum(BaseModel):
    tag_slug: str
    tag_name: str
    recent: TagWindowStats
    prior: TagWindowStats
    baseline: TagWindowStats
    hit_rate_recent: float
    hit_rate_prior: float
    hit_rate_lift: float
    release_growth_yoy: float
    release_growth_2yr: float
    quality_lift: float
    positive_share_recent: float
    positive_share_lift: float
    suggested_target_appid: int
    suggested_target_name: str


class TagMomentumScore(BaseModel):
    momentum: TagMomentum
    hit_lift_score: float
    quality_lift_score: float
    supply_health: float
    volume_floor_score: float
    non_f2p_score: float
    momentum_score: float
    disqualified: bool
    disqualifier_reasons: list[str]


class TrendSpotterData(BaseModel):
    generated_at: str
    horizon_quarters_per_window: int
    recent_window_start: str
    recent_window_end: str
    genre_filter: str
    volume_floor: int
    candidates_scanned: int
    candidates_disqualified: int
    top_momentum: list[TagMomentumScore]
    cooling: list[TagMomentumScore]


SYSTEM_PROMPT = """\
You are a senior indie game producer scanning a tag-momentum report to
tell the operator which tags are accelerating before the supply piles in.

<inputs>
You receive one TrendSpotterData JSON document. Each entry in top_momentum
and cooling is a TagMomentumScore: a TagMomentum (raw window stats per
tag plus derived deltas) plus five component scores plus a momentum_score.
A tag is identified by tag_slug. Some tags are flagged disqualified with
disqualifier_reasons.

Window definitions (all at quarter granularity):
- recent: last 4 complete quarters (trailing year)
- prior: the 4 quarters before that (year-before-last)
- baseline: the 4 quarters before that

Per-tag fields (each window carries TagWindowStats):
- releases, velocity_50_plus, velocity_10_50, positive_count,
  mixed_count, negative_count, avg_steam_pct, median_price, free_pct
- hit_rate_recent, hit_rate_prior, hit_rate_lift
  (velocity_50_plus / releases per window; lift is recent minus prior)
- release_growth_yoy, release_growth_2yr (fractions, e.g. 0.50 = +50%)
- quality_lift (avg_steam_pct delta, percentage points)
- positive_share_recent, positive_share_lift
- suggested_target_appid, suggested_target_name (the appid the operator
  feeds Concept Doctor for that tag)

Component scores (each 0-1):
- hit_lift_score, quality_lift_score, supply_health,
  volume_floor_score, non_f2p_score
- supply_health is a trapezoid: peaks at 0% to +50% YoY release growth,
  drops to 0 below -20% and above +200%. Penalises decay AND stampede.

Honest framing: hit_rate is computed from cohort release periods, not
review-arrival periods. So this report measures rising hit-rate while
supply is not yet stampeding. It is the best early-window signal the
matview can produce; it is not a true demand-side momentum signal.
</inputs>

<goal>
Pick the 3 tags an indie operator should investigate this month (the
early-window momentum picks) and the top 2 tags to stop targeting (the
cooling ones). Be willing to recommend zero investigations when the data
is noisy.
</goal>

<grounding_rules>
- Cite tags by tag_slug. Quote stats by name and value
  (e.g. "hit_rate_lift = +0.07"), never paraphrase ("rising sharply").
- Every recommendation must cite at least one TagMomentum field with
  its value. No invented tags. No vibes.
- Distinguish "supply growing too" (likely already noticed by the market)
  from "supply flat, hit rate rising" (the actual early window).
- Surface cross-cutting patterns the operator wouldn't see by reading
  the table row by row (e.g. "every tag with hit_rate_lift > 0.05 also
  carries release_growth_yoy < 0.30 in this scan").
</grounding_rules>

<output_rubric>
  <section role="verdict" length="1 sentence">
    The single sharpest takeaway from the scan. Defend with one stat.
  </section>
  <section role="top_3_investigate" length="3 items">
    Each item: tag_slug citation, the strongest stat value
    (hit_rate_lift, release_growth_yoy, or quality_lift), and a
    specific next-action: a Niche Scout command to confirm fundamentals
    OR a Concept Doctor command on the suggested_target_appid.
  </section>
  <section role="top_2_stop" length="2 items">
    Each item: cooling tag_slug citation, the decaying stat with value,
    and a one-line reason to abandon.
  </section>
  <section role="cross_cutting_observations" length="1-2 paragraphs">
    Patterns visible only across tags. Cite specific tag_slugs and stat
    values.
  </section>
  <section role="cadence" length="1 sentence">
    Re-run Trend Spotter quarterly, after the most recent quarter closes.
  </section>
</output_rubric>

<style>
- Senior-designer-to-senior-designer voice. Blunt. No marketing
  adjectives ("immersive", "engaging", "rich").
- Do not use em-dashes (the long horizontal dash). Use commas, colons,
  or parentheses instead. Hard rule.
- Use proper nouns and appids. No placeholders.
- Output format is markdown.
</style>"""


def open_readonly_conn() -> psycopg2.extensions.connection:
    """Open a read-only connection to prod via STEAMPULSE_PROD_DATABASE_URL."""
    url = os.environ.get("STEAMPULSE_PROD_DATABASE_URL")
    if not url:
        print(
            "ERROR: STEAMPULSE_PROD_DATABASE_URL is not set. "
            "This script reads from production; set the prod connection URL explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.Error as exc:
        print(f"ERROR: failed to connect to prod DB: {exc}", file=sys.stderr)
        sys.exit(2)
    conn.set_session(readonly=True, autocommit=False)
    return conn


def _clip(value: float, lo: float, hi: float) -> float:
    """Clip a scalar into [lo, hi]."""
    return max(lo, min(hi, value))


def _trapezoid(x: float, lo: float, peak_lo: float, peak_hi: float, hi: float) -> float:
    """Trapezoid membership: 0 outside [lo, hi], linear ramps to plateau 1 between peaks."""
    if x <= lo or x >= hi:
        return 0.0
    if x < peak_lo:
        return (x - lo) / (peak_lo - lo)
    if x <= peak_hi:
        return 1.0
    return (hi - x) / (hi - peak_hi)


def _quarter_start(d: date) -> date:
    """Return the first day of the quarter containing d."""
    quarter_first_month = ((d.month - 1) // 3) * 3 + 1
    return date(d.year, quarter_first_month, 1)


def _add_quarters(d: date, n: int) -> date:
    """Shift a quarter-aligned date by n quarters (n may be negative)."""
    total_months = (d.year * 12 + (d.month - 1)) + n * 3
    new_year, new_month_zero = divmod(total_months, 12)
    return date(new_year, new_month_zero + 1, 1)


def compute_windows(today: date) -> tuple[tuple[date, date], tuple[date, date], tuple[date, date]]:
    """Return (recent, prior, baseline) windows as (start_inclusive, end_exclusive) quarter ranges."""
    in_progress_q_start = _quarter_start(today)
    recent_end = in_progress_q_start
    recent_start = _add_quarters(recent_end, -WINDOW_QUARTERS)
    prior_end = recent_start
    prior_start = _add_quarters(prior_end, -WINDOW_QUARTERS)
    baseline_end = prior_start
    baseline_start = _add_quarters(baseline_end, -WINDOW_QUARTERS)
    return (recent_start, recent_end), (prior_start, prior_end), (baseline_start, baseline_end)


def fetch_tag_aggregates(
    conn: psycopg2.extensions.connection,
    recent: tuple[date, date],
    prior: tuple[date, date],
    baseline: tuple[date, date],
    genre_slug: str,
) -> dict[str, dict[str, Any]]:
    """One SQL pass: per-tag, per-window aggregates from mv_trend_by_tag plus tag_name."""
    sql = """
    WITH per_window AS (
      SELECT
        m.tag_slug,
        CASE
          WHEN m.period >= %(recent_start)s AND m.period < %(recent_end)s THEN 'recent'
          WHEN m.period >= %(prior_start)s  AND m.period < %(prior_end)s  THEN 'prior'
          WHEN m.period >= %(baseline_start)s AND m.period < %(baseline_end)s THEN 'baseline'
          ELSE NULL
        END AS bucket,
        m.period,
        m.releases,
        m.velocity_50_plus,
        m.velocity_10_50,
        m.positive_count,
        m.mixed_count,
        m.negative_count,
        m.avg_steam_pct,
        m.median_price,
        m.free_pct
      FROM mv_trend_by_tag m
      WHERE m.game_type = 'game'
        AND m.granularity = 'quarter'
        AND m.period >= %(baseline_start)s
        AND m.period <  %(recent_end)s
    ),
    eligible AS (
      SELECT * FROM per_window WHERE bucket IS NOT NULL
    ),
    aggregated AS (
      SELECT
        e.tag_slug,
        e.bucket,
        SUM(e.releases)::int AS releases,
        SUM(e.velocity_50_plus)::int AS velocity_50_plus,
        SUM(e.velocity_10_50)::int AS velocity_10_50,
        SUM(e.positive_count)::int AS positive_count,
        SUM(e.mixed_count)::int AS mixed_count,
        SUM(e.negative_count)::int AS negative_count,
        COALESCE(
          SUM(e.avg_steam_pct * e.releases)::numeric / NULLIF(SUM(e.releases), 0),
          0
        )::float AS avg_steam_pct,
        COALESCE(
          MAX(e.median_price) FILTER (
            WHERE e.bucket = 'recent'
              AND e.period = (%(recent_end)s::date - INTERVAL '3 months')
          ),
          MAX(e.median_price)
        )::float AS median_price,
        COALESCE(
          SUM(e.free_pct * e.releases)::numeric / NULLIF(SUM(e.releases), 0),
          0
        )::float AS free_pct
      FROM eligible e
      GROUP BY e.tag_slug, e.bucket
    )
    SELECT
      a.tag_slug,
      t.name AS tag_name,
      a.bucket,
      a.releases,
      a.velocity_50_plus,
      a.velocity_10_50,
      a.positive_count,
      a.mixed_count,
      a.negative_count,
      a.avg_steam_pct,
      a.median_price,
      a.free_pct
    FROM aggregated a
    JOIN tags t ON t.slug = a.tag_slug
    WHERE (
      %(genre_slug)s::text = ''
      OR EXISTS (
        SELECT 1
        FROM game_tags gt
        JOIN tags t2 ON t2.id = gt.tag_id AND t2.slug = a.tag_slug
        JOIN game_genres gg ON gg.appid = gt.appid
        JOIN genres gn ON gn.id = gg.genre_id AND gn.slug = %(genre_slug)s
      )
    )
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "recent_start": recent[0],
                "recent_end": recent[1],
                "prior_start": prior[0],
                "prior_end": prior[1],
                "baseline_start": baseline[0],
                "baseline_end": baseline[1],
                "genre_slug": genre_slug,
            },
        )
        rows = cur.fetchall()

    by_tag: dict[str, dict[str, Any]] = {}
    for r in rows:
        slot = by_tag.setdefault(r["tag_slug"], {"tag_name": r["tag_name"], "windows": {}})
        slot["windows"][r["bucket"]] = TagWindowStats(
            releases=int(r["releases"] or 0),
            velocity_50_plus=int(r["velocity_50_plus"] or 0),
            velocity_10_50=int(r["velocity_10_50"] or 0),
            positive_count=int(r["positive_count"] or 0),
            mixed_count=int(r["mixed_count"] or 0),
            negative_count=int(r["negative_count"] or 0),
            avg_steam_pct=round(float(r["avg_steam_pct"] or 0.0), 2),
            median_price=round(float(r["median_price"] or 0.0), 2),
            free_pct=round(float(r["free_pct"] or 0.0), 2),
        )
    return by_tag


def _empty_window() -> TagWindowStats:
    """Zero-valued window stats placeholder when a tag had no rows in that window."""
    return TagWindowStats(
        releases=0,
        velocity_50_plus=0,
        velocity_10_50=0,
        positive_count=0,
        mixed_count=0,
        negative_count=0,
        avg_steam_pct=0.0,
        median_price=0.0,
        free_pct=0.0,
    )


def derive_momentum(
    tag_slug: str, tag_name: str, windows: dict[str, TagWindowStats]
) -> TagMomentum:
    """Compute deltas; suggested_target fields filled in later by pick_target_appid."""
    recent = windows.get("recent") or _empty_window()
    prior = windows.get("prior") or _empty_window()
    baseline = windows.get("baseline") or _empty_window()

    hit_rate_recent = recent.velocity_50_plus / recent.releases if recent.releases > 0 else 0.0
    hit_rate_prior = prior.velocity_50_plus / prior.releases if prior.releases > 0 else 0.0
    hit_rate_lift = hit_rate_recent - hit_rate_prior

    release_growth_yoy = (recent.releases - prior.releases) / max(prior.releases, 1)
    release_growth_2yr = (recent.releases - baseline.releases) / max(baseline.releases, 1)

    quality_lift = recent.avg_steam_pct - prior.avg_steam_pct

    positive_share_recent = recent.positive_count / max(recent.releases, 1)
    positive_share_prior = prior.positive_count / max(prior.releases, 1)
    positive_share_lift = positive_share_recent - positive_share_prior

    return TagMomentum(
        tag_slug=tag_slug,
        tag_name=tag_name,
        recent=recent,
        prior=prior,
        baseline=baseline,
        hit_rate_recent=round(hit_rate_recent, 4),
        hit_rate_prior=round(hit_rate_prior, 4),
        hit_rate_lift=round(hit_rate_lift, 4),
        release_growth_yoy=round(release_growth_yoy, 4),
        release_growth_2yr=round(release_growth_2yr, 4),
        quality_lift=round(quality_lift, 2),
        positive_share_recent=round(positive_share_recent, 4),
        positive_share_lift=round(positive_share_lift, 4),
        suggested_target_appid=0,
        suggested_target_name="",
    )


def score_momentum(momentum: TagMomentum, volume_floor: int) -> TagMomentumScore:
    """Component scores plus hard disqualifiers; momentum_score forced to 0 when disqualified."""
    hit_lift_score = _clip(momentum.hit_rate_lift / HIT_LIFT_FULL, 0.0, 1.0)
    quality_lift_raw = _clip(momentum.quality_lift / QUALITY_LIFT_FULL, QUALITY_LIFT_LO, 1.0)
    quality_lift_for_composite = _clip(quality_lift_raw, 0.0, 1.0)
    supply_health = _trapezoid(
        momentum.release_growth_yoy, SUPPLY_LO, SUPPLY_PEAK_LO, SUPPLY_PEAK_HI, SUPPLY_HI
    )
    volume_floor_score = (
        1.0 if momentum.recent.releases >= VOLUME_RAMP else momentum.recent.releases / VOLUME_RAMP
    )
    if momentum.recent.free_pct >= F2P_HARD_CUT:
        non_f2p_score = 0.0
    elif momentum.recent.free_pct >= F2P_PARTIAL_CUT:
        non_f2p_score = 0.5
    else:
        non_f2p_score = 1.0

    raw = (
        W_HIT_LIFT * hit_lift_score
        + W_QUALITY * quality_lift_for_composite
        + W_SUPPLY * supply_health
        + W_VOLUME * volume_floor_score
        + W_NON_F2P * non_f2p_score
    )

    reasons: list[str] = []
    if momentum.recent.releases < volume_floor:
        reasons.append(f"below_volume_floor (releases_recent={momentum.recent.releases})")
    if momentum.release_growth_yoy > DISQUAL_RELEASE_GROWTH_YOY:
        reasons.append(
            f"saturation_stampede_yoy (release_growth_yoy={momentum.release_growth_yoy:+.2f})"
        )
    if momentum.release_growth_2yr > DISQUAL_RELEASE_GROWTH_2YR:
        reasons.append(
            f"saturation_stampede_2yr (release_growth_2yr={momentum.release_growth_2yr:+.2f})"
        )
    if momentum.recent.velocity_50_plus == 0 and momentum.recent.velocity_10_50 == 0:
        reasons.append("no_breakouts (velocity_50_plus=0 and velocity_10_50=0 in recent window)")
    if momentum.recent.free_pct >= F2P_HARD_CUT:
        reasons.append(f"f2p_dominated (free_pct_recent={momentum.recent.free_pct:.1f})")
    if momentum.prior.releases == 0 and momentum.baseline.releases == 0:
        reasons.append("insufficient_history (no releases in prior or baseline window)")

    disqualified = bool(reasons)
    final = 0.0 if disqualified else _clip(raw, 0.0, 1.0)

    return TagMomentumScore(
        momentum=momentum,
        hit_lift_score=round(hit_lift_score, 4),
        quality_lift_score=round(quality_lift_raw, 4),
        supply_health=round(supply_health, 4),
        volume_floor_score=round(volume_floor_score, 4),
        non_f2p_score=round(non_f2p_score, 4),
        momentum_score=round(final, 4),
        disqualified=disqualified,
        disqualifier_reasons=reasons,
    )


def pick_target_appid(
    conn: psycopg2.extensions.connection,
    tag_slug: str,
    recent_start: date,
    recent_end: date,
) -> tuple[int, str]:
    """Pick a representative recent winner; fall back to highest review velocity in window."""
    sql_winner = """
    SELECT g.appid, g.name
    FROM games g
    JOIN game_tags gt ON gt.appid = g.appid
    JOIN tags t ON t.id = gt.tag_id AND t.slug = %(tag_slug)s
    WHERE g.coming_soon = FALSE
      AND g.type = 'game'
      AND g.release_date >= %(recent_start)s
      AND g.release_date <  %(recent_end)s
      AND g.review_count BETWEEN %(rc_floor)s AND %(rc_ceil)s
      AND g.positive_pct >= %(pos_floor)s
      AND COALESCE(g.developer, '') != ALL(%(aaa)s::text[])
      AND COALESCE(g.publisher, '') != ALL(%(aaa)s::text[])
    ORDER BY g.release_date DESC NULLS LAST, g.appid ASC
    LIMIT 1
    """
    sql_fallback = """
    SELECT g.appid, g.name
    FROM games g
    JOIN game_tags gt ON gt.appid = g.appid
    JOIN tags t ON t.id = gt.tag_id AND t.slug = %(tag_slug)s
    WHERE g.coming_soon = FALSE
      AND g.type = 'game'
      AND g.release_date >= %(recent_start)s
      AND g.release_date <  %(recent_end)s
      AND g.review_count > 0
      AND g.review_count <= %(rc_ceil)s
      AND COALESCE(g.developer, '') != ALL(%(aaa)s::text[])
      AND COALESCE(g.publisher, '') != ALL(%(aaa)s::text[])
    ORDER BY COALESCE(
               g.review_velocity_lifetime,
               g.review_count::float / NULLIF(GREATEST(CURRENT_DATE - g.release_date, 1), 0)
             ) DESC NULLS LAST,
             g.appid ASC
    LIMIT 1
    """
    params = {
        "tag_slug": tag_slug,
        "recent_start": recent_start,
        "recent_end": recent_end,
        "rc_floor": WINNER_REVIEW_FLOOR,
        "rc_ceil": WINNER_REVIEW_CEIL,
        "pos_floor": WINNER_POSITIVE_FLOOR,
        "aaa": sorted(AAA_DEVELOPERS),
    }
    with conn.cursor() as cur:
        cur.execute(sql_winner, params)
        row = cur.fetchone()
        if row:
            return int(row["appid"]), row["name"]
        cur.execute(sql_fallback, params)
        row = cur.fetchone()
        if row:
            return int(row["appid"]), row["name"]
    return 0, ""


def render_report(
    data: TrendSpotterData, generated_at: datetime, verdict_markdown: str
) -> str:
    """Render the full markdown report."""
    lines: list[str] = []
    lines.append(
        f"# Trend Spotter (Generated {generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')} against prod)"
    )
    lines.append("")

    if verdict_markdown:
        lines.append("## Verdict & Momentum Picks")
        lines.append("")
        lines.append(verdict_markdown.strip())
        lines.append("")

    lines.append("## Scan Summary")
    lines.append("")
    lines.append(
        f"- Window: 4 quarters per band; recent {data.recent_window_start} to "
        f"{data.recent_window_end} (exclusive)"
    )
    lines.append(f"- Genre filter: {data.genre_filter or '(none, all tags)'}")
    lines.append(f"- Volume floor: {data.volume_floor} releases in recent window")
    lines.append(f"- Candidates scanned: {data.candidates_scanned}")
    lines.append(f"- Candidates disqualified: {data.candidates_disqualified}")
    lines.append(f"- Top tags reported: {len(data.top_momentum)}")
    lines.append(f"- Cooling tags reported: {len(data.cooling)}")
    lines.append("")

    lines.append("## Top Trending Tags")
    lines.append("")
    lines.append(
        "| # | Tag | Score | Releases (recent) | Hit rate (recent) | Hit lift | "
        "Release YoY | Quality lift | Suggested appid |"
    )
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, ts in enumerate(data.top_momentum, start=1):
        m = ts.momentum
        suggested = m.suggested_target_appid if m.suggested_target_appid > 0 else "n/a"
        lines.append(
            f"| {i} | {m.tag_slug} | {ts.momentum_score:.3f} | {m.recent.releases} | "
            f"{m.hit_rate_recent:.3f} | {m.hit_rate_lift:+.3f} | "
            f"{m.release_growth_yoy:+.2f} | {m.quality_lift:+.1f} | {suggested} |"
        )
    lines.append("")

    lines.append("## Cooling Tags")
    lines.append("")
    if not data.cooling:
        lines.append("_No qualified tags landed in the cooling band._")
        lines.append("")
    else:
        lines.append("| Tag | Score | Hit lift | Release YoY | Reason |")
        lines.append("|---|---:|---:|---:|---|")
        for ts in data.cooling:
            m = ts.momentum
            reason_bits: list[str] = []
            if m.hit_rate_lift < 0:
                reason_bits.append(f"hit_rate_lift {m.hit_rate_lift:+.3f}")
            if m.quality_lift < 0:
                reason_bits.append(f"quality_lift {m.quality_lift:+.1f}")
            if m.release_growth_yoy < 0:
                reason_bits.append(f"release_growth_yoy {m.release_growth_yoy:+.2f}")
            reason = "; ".join(reason_bits) or "low momentum_score"
            lines.append(
                f"| {m.tag_slug} | {ts.momentum_score:.3f} | {m.hit_rate_lift:+.3f} | "
                f"{m.release_growth_yoy:+.2f} | {reason} |"
            )
        lines.append("")

    lines.append("## Per-Tag Detail")
    lines.append("")
    for ts in data.top_momentum:
        m = ts.momentum
        summary = f"{m.tag_slug} (momentum_score {ts.momentum_score:.3f})"
        lines.append(f"<details><summary>{summary}</summary>")
        lines.append("")
        if ts.disqualified:
            lines.append(f"**Disqualified**: {', '.join(ts.disqualifier_reasons)}")
            lines.append("")
        lines.append(f"- tag_name: {m.tag_name}")
        lines.append(
            f"- hit_rate_recent: {m.hit_rate_recent:.3f}, "
            f"hit_rate_prior: {m.hit_rate_prior:.3f}, "
            f"hit_rate_lift: {m.hit_rate_lift:+.3f}"
        )
        lines.append(
            f"- release_growth_yoy: {m.release_growth_yoy:+.3f}; "
            f"release_growth_2yr: {m.release_growth_2yr:+.3f}"
        )
        lines.append(f"- quality_lift (avg_steam_pct): {m.quality_lift:+.2f}")
        lines.append(
            f"- positive_share_recent: {m.positive_share_recent:.3f}; "
            f"positive_share_lift: {m.positive_share_lift:+.3f}"
        )
        lines.append("")
        lines.append("**Window stats**")
        for label, w in [("recent", m.recent), ("prior", m.prior), ("baseline", m.baseline)]:
            lines.append(
                f"- {label}: releases={w.releases}, velocity_50_plus={w.velocity_50_plus}, "
                f"velocity_10_50={w.velocity_10_50}, positive_count={w.positive_count}, "
                f"avg_steam_pct={w.avg_steam_pct:.2f}, median_price=${w.median_price:.2f}, "
                f"free_pct={w.free_pct:.1f}"
            )
        lines.append("")
        lines.append("**Score breakdown**")
        lines.append(f"- hit_lift_score: {ts.hit_lift_score:.3f}")
        lines.append(f"- quality_lift_score: {ts.quality_lift_score:.3f}")
        lines.append(f"- supply_health: {ts.supply_health:.3f}")
        lines.append(f"- volume_floor_score: {ts.volume_floor_score:.3f}")
        lines.append(f"- non_f2p_score: {ts.non_f2p_score:.3f}")
        lines.append("")
        if m.suggested_target_appid > 0:
            lines.append(
                f"**Concept Doctor handoff**: "
                f"`poetry run python scripts/concept_doctor_v1.py --target-appid "
                f"{m.suggested_target_appid}` ({m.suggested_target_name})"
            )
        else:
            lines.append("**Concept Doctor handoff**: no qualifying winner found.")
        lines.append(
            f"**Niche Scout handoff**: "
            f"`poetry run python scripts/niche_scout_v1.py --data-only` "
            f"(filter the result for tags carrying {m.tag_slug})"
        )
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def submit_batch_and_wait(api_key: str, data: TrendSpotterData) -> str:
    """Submit a single-request Anthropic batch with the verdict prompt; return the markdown body."""
    client = anthropic.Anthropic(api_key=api_key)
    payload = data.model_dump_json(indent=2)
    user_text = f"{payload}\n\nProduce the verdict."
    requests = [
        {
            "custom_id": "trend_spotter_v1",
            "params": {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_text}],
            },
        }
    ]

    batch = client.messages.batches.create(requests=requests)
    batch_id = batch.id
    print(
        f"Submitted Anthropic batch {batch_id}; polling every {BATCH_POLL_SECONDS}s.",
        flush=True,
    )

    started = time.monotonic()
    while True:
        time.sleep(BATCH_POLL_SECONDS)
        info = client.messages.batches.retrieve(batch_id)
        elapsed = int(time.monotonic() - started)
        print(
            f"  batch {batch_id}: status={info.processing_status} (elapsed {elapsed}s)",
            flush=True,
        )
        if info.processing_status == "ended":
            break
        if info.processing_status in ("canceling", "canceled", "expired"):
            print(
                f"ERROR: batch ended in terminal state {info.processing_status}",
                file=sys.stderr,
            )
            sys.exit(5)

    for entry in client.messages.batches.results(batch_id):
        if entry.custom_id != "trend_spotter_v1":
            continue
        if entry.result.type != "succeeded":
            print(f"ERROR: batch result type was {entry.result.type}", file=sys.stderr)
            sys.exit(6)
        for block in entry.result.message.content:
            if getattr(block, "type", None) == "text":
                return block.text
        print("ERROR: no text content in batch result", file=sys.stderr)
        sys.exit(7)

    print("ERROR: batch result for custom_id trend_spotter_v1 not found", file=sys.stderr)
    sys.exit(8)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Trend Spotter v1: scan the catalog for tags accelerating before supply piles in."
        )
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"Cap the result list (default {DEFAULT_TOP}).",
    )
    parser.add_argument(
        "--genre",
        type=str,
        default=GENRE_FILTER_NONE,
        help="Restrict to tags carried by at least one game in this genre slug (e.g. rpg).",
    )
    parser.add_argument(
        "--volume-floor",
        type=int,
        default=DEFAULT_VOLUME_FLOOR,
        help=f"Minimum releases in recent window for a tag to qualify (default {DEFAULT_VOLUME_FLOOR}).",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Skip the LLM verdict and emit the data report only.",
    )
    args = parser.parse_args()

    generated_at = datetime.now(UTC)
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")

    recent, prior, baseline = compute_windows(generated_at.date())

    conn = open_readonly_conn()
    try:
        by_tag = fetch_tag_aggregates(conn, recent, prior, baseline, args.genre)
        if not by_tag:
            print(
                "ERROR: no tags returned from mv_trend_by_tag for the requested filter. "
                "Confirm the matview is populated and the genre slug exists.",
                file=sys.stderr,
            )
            sys.exit(4)

        scored: list[TagMomentumScore] = []
        for tag_slug, slot in by_tag.items():
            momentum = derive_momentum(tag_slug, slot["tag_name"], slot["windows"])
            scored.append(score_momentum(momentum, args.volume_floor))

        scored.sort(key=lambda s: (-s.momentum_score, s.momentum.tag_slug))
        top_n = scored[: args.top]

        for ts in top_n:
            appid, name = pick_target_appid(
                conn, ts.momentum.tag_slug, recent[0], recent[1]
            )
            if appid:
                ts.momentum.suggested_target_appid = appid
                ts.momentum.suggested_target_name = name
    finally:
        conn.close()

    candidates_disqualified = sum(1 for s in scored if s.disqualified)

    decaying = [
        s for s in scored
        if not s.disqualified
        and s.momentum_score > 0
        and s.momentum.hit_rate_lift < 0
    ]
    cooling_sorted = sorted(
        decaying, key=lambda s: (s.momentum.hit_rate_lift, s.momentum.tag_slug)
    )
    cooling = cooling_sorted[:COOLING_CAP]

    data = TrendSpotterData(
        generated_at=generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        horizon_quarters_per_window=WINDOW_QUARTERS,
        recent_window_start=recent[0].isoformat(),
        recent_window_end=recent[1].isoformat(),
        genre_filter=args.genre,
        volume_floor=args.volume_floor,
        candidates_scanned=len(scored),
        candidates_disqualified=candidates_disqualified,
        top_momentum=top_n,
        cooling=cooling,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data_path = REPORTS_DIR / f"{timestamp}_data.json"
    data_path.write_text(data.model_dump_json(indent=2) + "\n")

    verdict_markdown = ""
    if not args.data_only:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ERROR: ANTHROPIC_API_KEY not set (use --data-only to skip the verdict).",
                file=sys.stderr,
            )
            sys.exit(2)
        verdict_markdown = submit_batch_and_wait(api_key, data).strip()

    report = render_report(data, generated_at, verdict_markdown)
    md_path = REPORTS_DIR / f"{timestamp}.md"
    md_path.write_text(report)

    print(report)
    print(f"\nWrote report to {md_path}")
    print(f"Wrote data to   {data_path}")


if __name__ == "__main__":
    main()
