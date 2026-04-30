"""Niche Scout v1: scan the Steam catalog for fertile (genre, modifier-tag) niches."""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
import psycopg2
import psycopg2.extensions
import psycopg2.extras
from pydantic import BaseModel

REPORTS_DIR = Path("reports/niche_scout")
MODEL = "claude-opus-4-7"

NICHE_GAME_FLOOR = 30
TOP_TAG_LIMIT = 10
WINNER_REVIEW_FLOOR = 500
WINNER_POSITIVE_FLOOR = 80
SUGGESTED_REVIEW_LO = 500
SUGGESTED_REVIEW_HI = 5000
RECENT_WINNER_MONTHS = 24
DISQUAL_MIN_PRICE = 2.00
DISQUAL_DEAD_MARKET_MONTHS = 18

QUALITY_LO = 70.0
QUALITY_RAMP_LO = 78.0
QUALITY_RAMP_HI = 88.0
QUALITY_HI = 95.0

INDIE_REV_LO = 200_000.0
INDIE_REV_HI = 5_000_000.0

HALO_REV_TAPER_START = 20_000_000.0
HALO_REV_TAPER_END = 50_000_000.0
HALO_FLOOR = 0.3

DEMAND_FULL_REVIEWS = 1_000_000.0

SATURATION_DECLINE_FLOOR = -0.30
SATURATION_GROWTH_PEAK = 0.10
SATURATION_GROWTH_CEILING = 2.00

GENERIC_TAG_SLUGS = (
    "singleplayer",
    "single-player",
    "multiplayer",
    "multi-player",
    "2d",
    "3d",
    "early-access",
    "free-to-play",
    "nsfw",
    "hentai",
    "mature",
    "sexual-content",
    "nudity",
)

WEIGHT_INDIE_SCOPE = 0.25
WEIGHT_NOT_AAA = 0.15
WEIGHT_QUALITY = 0.15
WEIGHT_LONGTAIL = 0.15
WEIGHT_DEMAND = 0.10
WEIGHT_GROWTH = 0.10
WEIGHT_SATURATION = 0.10

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
}

BATCH_POLL_SECONDS = 30
MAX_TOKENS = 6144


class NicheCandidate(BaseModel):
    genre_slug: str
    modifier_tag_slug: str
    label: str
    game_count: int
    aggregate_reviews_last_12mo: int
    median_positive_pct_500plus: float
    revenue_p25: float
    revenue_p50: float
    revenue_p75: float
    revenue_p90: float
    top2_revenue_share: float
    median_price_usd: float
    free_to_play_pct: float
    releases_last_year: int
    releases_3yr_ago_avg: float
    growth_yoy_3yr_avg: float
    top_winner_developer: str
    top_winner_revenue_usd: float
    is_aaa_dominated: bool
    suggested_target_appid: int
    suggested_target_name: str


class NicheCandidateScore(BaseModel):
    candidate: NicheCandidate
    demand_score: float
    growth_score: float
    saturation_penalty: float
    quality_score: float
    longtail_score: float
    indie_scope_score: float
    not_aaa_score: float
    opportunity_score: float
    disqualified: bool
    disqualifier_reasons: list[str]


class NicheScoutData(BaseModel):
    generated_at: str
    genre_filter: str | None
    candidates_scanned: int
    candidates_disqualified: int
    top_niches: list[NicheCandidateScore]


SYSTEM_PROMPT = """\
You are a senior indie game producer who has shipped 4 commercial hits and
2 commercial failures in the past decade. You are scanning a niche-finder
report and recommending where the operator should and should not build.

<inputs>
You receive one NicheScoutData JSON document. Each entry in top_niches is
a NicheCandidateScore: a NicheCandidate (raw stats per niche) plus eight
component scores plus an opportunity_score. A niche is identified by
(genre_slug, modifier_tag_slug). Some niches are flagged disqualified
with disqualifier_reasons. Stat fields:

- game_count, aggregate_reviews_last_12mo
- median_positive_pct_500plus
- revenue_p25 / p50 / p75 / p90 (over winners only)
- top2_revenue_share (revenue concentration; high = winner-takes-all)
- median_price_usd, free_to_play_pct
- releases_last_year, releases_3yr_ago_avg, growth_yoy_3yr_avg
- top_winner_developer, top_winner_revenue_usd, is_aaa_dominated
  (top_winner_revenue_usd above ~$20M means the anchor of this niche
  is a non-indie-scope title; both indie_scope_score and not_aaa_score
  are halo-attenuated when this fires)
- suggested_target_appid, suggested_target_name (the appid the operator
  would feed into Concept Doctor for that niche)

Component scores (each 0-1):
- demand_score, growth_score, saturation_penalty, quality_score,
  longtail_score, indie_scope_score, not_aaa_score
- saturation_penalty is a TENT (not a one-sided penalty): peak 1.0 at
  ~10% YoY growth, drops to 0 at -30% decline AND at +200% explosion.
  Treat low saturation_penalty as "not a healthy growth zone" without
  assuming the direction.
</inputs>

<goal>
Identify the top 3 build-here niches and the top 3 high-score-but-do-not-
build niches. Recommend a specific operator next-action for each. The
build list must be the most accurate top 3, not the top 3 by raw score
if the data tells a different story. Be willing to demote a high-score
niche when something in the underlying stats undermines it.
</goal>

<rules>
- Cite every niche by genre_slug+modifier_tag_slug (e.g.
  rpg+roguelike-deckbuilder), never paraphrase.
- Quote stats by name and value, e.g. "top2_revenue_share = 0.78", not
  "concentrated revenue". Stat names from the inputs section.
- When you recommend AGAINST a high-score niche, the reason MUST cite a
  specific NicheCandidate field with its value. Vibes do not count.
- Surface at least one cross-niche pattern the operator would not see
  by reading the table row by row (e.g. "every niche with
  growth_yoy_3yr_avg > 0.5 also shows top2_revenue_share > 0.6 in this
  scan, suggesting late-stage piling-in").
- For each top_3_build entry, the next-action is exactly: "run Concept
  Doctor on appid <suggested_target_appid> (<suggested_target_name>)".
- No invented data. No filler. No throat-clearing.
- Do not use em-dashes (the long horizontal dash). Use commas, colons,
  or parentheses instead. Hard rule.
</rules>

<output_rubric>
  <section role="verdict" length="1 sentence">
    The single sharpest takeaway from this scan. Defend with one stat.
  </section>
  <section role="top_3_build" length="3 items">
    Each item: niche citation, opportunity_score, the 1-2 stats that
    earned it the slot, the recommended next-action (Concept Doctor
    command on the suggested_target_appid).
  </section>
  <section role="top_3_skip" length="3 items">
    Each item: niche citation, the score that would have made it look
    attractive, the cited stat that undermines it, what the operator
    should do instead (or "skip and revisit in 12 months").
  </section>
  <section role="cross_cutting_observations" length="1-2 paragraphs">
    Patterns visible only across niches. Cite specific
    genre_slug+modifier_tag_slug pairs and stat values.
  </section>
  <section role="cadence" length="1 sentence">
    When should the operator re-run Niche Scout?
  </section>
</output_rubric>

<style>
- Senior-designer-to-senior-designer voice. Blunt. No marketing
  adjectives ("immersive", "engaging", "rich").
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


def _sigmoid(x: float) -> float:
    """Logistic sigmoid; underflow-safe."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def _demand_score(reviews_12mo: int) -> float:
    return _clip(reviews_12mo / DEMAND_FULL_REVIEWS, 0.0, 1.0)


def _growth_score(yoy_3yr: float) -> float:
    return _sigmoid(yoy_3yr)


def _saturation_penalty(growth_yoy: float) -> float:
    """Tent: 0 at -30% decline, peak 1 at +10% growth, 0 at +200% explosion. Penalizes both ends."""
    if growth_yoy <= SATURATION_DECLINE_FLOOR or growth_yoy >= SATURATION_GROWTH_CEILING:
        return 0.0
    if growth_yoy < SATURATION_GROWTH_PEAK:
        return (growth_yoy - SATURATION_DECLINE_FLOOR) / (
            SATURATION_GROWTH_PEAK - SATURATION_DECLINE_FLOOR
        )
    return (SATURATION_GROWTH_CEILING - growth_yoy) / (
        SATURATION_GROWTH_CEILING - SATURATION_GROWTH_PEAK
    )


def _quality_score(median_pos_pct: float) -> float:
    """Trapezoid on positive_pct: 0 below 70, ramps to 1 by 78, plateau 78-88, ramps to 0 by 95."""
    if median_pos_pct <= QUALITY_LO or median_pos_pct >= QUALITY_HI:
        return 0.0
    if median_pos_pct < QUALITY_RAMP_LO:
        return (median_pos_pct - QUALITY_LO) / (QUALITY_RAMP_LO - QUALITY_LO)
    if median_pos_pct <= QUALITY_RAMP_HI:
        return 1.0
    return (QUALITY_HI - median_pos_pct) / (QUALITY_HI - QUALITY_RAMP_HI)


def _longtail_score(top2_share: float) -> float:
    return _clip(1.0 - top2_share, 0.0, 1.0)


def _halo_attenuation(top_winner_rev: float) -> float:
    """1.0 below $20M; linear taper to HALO_FLOOR (0.3) at $50M; flat HALO_FLOOR above."""
    if top_winner_rev <= HALO_REV_TAPER_START:
        return 1.0
    if top_winner_rev >= HALO_REV_TAPER_END:
        return HALO_FLOOR
    frac = (top_winner_rev - HALO_REV_TAPER_START) / (
        HALO_REV_TAPER_END - HALO_REV_TAPER_START
    )
    return 1.0 - (1.0 - HALO_FLOOR) * frac


def _indie_scope_score(median_winner_rev: float, top_winner_rev: float) -> float:
    """p50-based score in [200K, 5M] with log-decade taper outside, multiplied by halo attenuation."""
    if median_winner_rev <= 0:
        base = 0.0
    elif INDIE_REV_LO <= median_winner_rev <= INDIE_REV_HI:
        base = 1.0
    else:
        log_rev = math.log10(median_winner_rev)
        if median_winner_rev < INDIE_REV_LO:
            base = max(0.0, 1.0 - (math.log10(INDIE_REV_LO) - log_rev))
        else:
            base = max(0.0, 1.0 - (log_rev - math.log10(INDIE_REV_HI)))
    return base * _halo_attenuation(top_winner_rev)


def _not_aaa_score(top_dev: str, top_winner_rev: float, is_aaa_dominated: bool) -> float:
    """Halo-attenuated proxy: AAA-named top dev OR all-winners-AAA flag forces HALO_FLOOR; else use revenue."""
    if is_aaa_dominated or top_dev in AAA_DEVELOPERS:
        return HALO_FLOOR
    return _halo_attenuation(top_winner_rev)


_SQL_PEER_TOP10 = """
WITH peer_top10 AS (
  SELECT gt.appid, gt.tag_id,
         ROW_NUMBER() OVER (
           PARTITION BY gt.appid
           ORDER BY gt.votes DESC, gt.tag_id ASC
         ) AS rnk
  FROM game_tags gt
  WHERE gt.votes > 0
)
"""


def fetch_niche_stats(
    conn: psycopg2.extensions.connection, genre_filter: str | None
) -> list[dict[str, Any]]:
    """Single batched SQL: return one row per (genre_slug, tag_slug) niche with >= 30 games."""
    sql = (
        _SQL_PEER_TOP10
        + """
, niche_games AS (
  SELECT gn.slug AS genre_slug, t.slug AS tag_slug, g.appid,
         g.name, g.developer, g.review_count, g.positive_pct,
         g.estimated_revenue_usd, g.price_usd, g.is_free,
         g.release_date, g.review_velocity_lifetime,
         (g.review_count >= %(winner_reviews)s
          AND g.positive_pct >= %(winner_positive)s) AS is_winner
  FROM peer_top10 pt
  JOIN tags t ON t.id = pt.tag_id
  JOIN game_genres gg ON gg.appid = pt.appid
  JOIN genres gn ON gn.id = gg.genre_id
  JOIN games g ON g.appid = pt.appid
  WHERE pt.rnk <= %(top_n)s
    AND g.coming_soon = FALSE
    AND (%(genre_filter)s::text IS NULL OR gn.slug = %(genre_filter)s)
    AND NOT EXISTS (SELECT 1 FROM genres g2 WHERE g2.slug = t.slug)
    AND t.slug != ALL(%(generic_tags)s::text[])
),
ranked_winners AS (
  SELECT genre_slug, tag_slug, appid, name, developer,
         estimated_revenue_usd, review_count,
         ROW_NUMBER() OVER (
           PARTITION BY genre_slug, tag_slug
           ORDER BY review_count DESC, appid ASC
         ) AS rnk_by_rc,
         ROW_NUMBER() OVER (
           PARTITION BY genre_slug, tag_slug
           ORDER BY estimated_revenue_usd DESC NULLS LAST, appid ASC
         ) AS rnk_by_rev
  FROM niche_games
  WHERE is_winner
),
pair_winner_meta AS (
  SELECT genre_slug, tag_slug,
         MAX(name)      FILTER (WHERE rnk_by_rc = 1) AS top_winner_name,
         MAX(developer) FILTER (WHERE rnk_by_rc = 1) AS top_winner_developer,
         MAX(appid)     FILTER (WHERE rnk_by_rc = 1) AS top_winner_appid,
         MAX(estimated_revenue_usd) FILTER (WHERE rnk_by_rev = 1)::float
           AS top_winner_revenue_usd,
         COALESCE(
           SUM(estimated_revenue_usd) FILTER (WHERE rnk_by_rev <= 2)
             / NULLIF(SUM(estimated_revenue_usd), 0),
           0
         )::float AS top2_revenue_share,
         COALESCE(bool_and(developer = ANY(%(aaa)s::text[])), false) AS all_winners_aaa
  FROM ranked_winners
  GROUP BY genre_slug, tag_slug
)
SELECT
  ng.genre_slug,
  ng.tag_slug,
  COUNT(*)::int AS game_count,
  COUNT(*) FILTER (WHERE ng.is_winner)::int AS winner_count,
  COALESCE(SUM(LEAST(
    COALESCE(ng.review_count, 0)::numeric,
    COALESCE(
      ng.review_velocity_lifetime,
      CASE
        WHEN ng.release_date IS NULL OR ng.review_count IS NULL OR ng.review_count = 0 THEN 0
        ELSE ng.review_count::numeric
             / GREATEST((CURRENT_DATE - ng.release_date)::int, 1)
      END
    ) * 365
  ))::bigint, 0) AS aggregate_reviews_last_12mo,
  COUNT(*) FILTER (WHERE ng.release_date >= now() - interval '12 months')::int
    AS releases_last_year,
  (COUNT(*) FILTER (
    WHERE ng.release_date >= now() - interval '4 years'
      AND ng.release_date <  now() - interval '1 year'
  )::float / 3.0) AS releases_3yr_ago_avg,
  COUNT(*) FILTER (WHERE ng.release_date >= now() - (%(dead_months)s || ' months')::interval)::int
    AS releases_recent_window,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY ng.positive_pct)
    FILTER (WHERE ng.review_count >= %(winner_reviews)s)::float
    AS median_positive_pct_500plus,
  percentile_cont(0.25) WITHIN GROUP (ORDER BY ng.estimated_revenue_usd)
    FILTER (WHERE ng.is_winner AND ng.estimated_revenue_usd IS NOT NULL)::float
    AS revenue_p25,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY ng.estimated_revenue_usd)
    FILTER (WHERE ng.is_winner AND ng.estimated_revenue_usd IS NOT NULL)::float
    AS revenue_p50,
  percentile_cont(0.75) WITHIN GROUP (ORDER BY ng.estimated_revenue_usd)
    FILTER (WHERE ng.is_winner AND ng.estimated_revenue_usd IS NOT NULL)::float
    AS revenue_p75,
  percentile_cont(0.90) WITHIN GROUP (ORDER BY ng.estimated_revenue_usd)
    FILTER (WHERE ng.is_winner AND ng.estimated_revenue_usd IS NOT NULL)::float
    AS revenue_p90,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY ng.price_usd)
    FILTER (WHERE NOT ng.is_free AND ng.price_usd IS NOT NULL)::float
    AS median_price_usd,
  (COUNT(*) FILTER (WHERE ng.is_free)::float
    / NULLIF(COUNT(*), 0))::float AS free_to_play_pct,
  pwm.top_winner_name,
  pwm.top_winner_developer,
  pwm.top_winner_appid,
  COALESCE(pwm.top_winner_revenue_usd, 0)::float AS top_winner_revenue_usd,
  COALESCE(pwm.top2_revenue_share, 0)::float AS top2_revenue_share,
  COALESCE(pwm.all_winners_aaa, false) AS all_winners_aaa
FROM niche_games ng
LEFT JOIN pair_winner_meta pwm
  ON pwm.genre_slug = ng.genre_slug AND pwm.tag_slug = ng.tag_slug
GROUP BY ng.genre_slug, ng.tag_slug,
         pwm.top_winner_name, pwm.top_winner_developer,
         pwm.top_winner_appid, pwm.top_winner_revenue_usd,
         pwm.top2_revenue_share, pwm.all_winners_aaa
HAVING COUNT(*) >= %(floor)s
ORDER BY ng.genre_slug, ng.tag_slug
"""
    )
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "top_n": TOP_TAG_LIMIT,
                "winner_reviews": WINNER_REVIEW_FLOOR,
                "winner_positive": WINNER_POSITIVE_FLOOR,
                "floor": NICHE_GAME_FLOOR,
                "genre_filter": genre_filter,
                "dead_months": DISQUAL_DEAD_MARKET_MONTHS,
                "aaa": sorted(AAA_DEVELOPERS),
                "generic_tags": list(GENERIC_TAG_SLUGS),
            },
        )
        return [dict(r) for r in cur.fetchall()]


def pick_suggested_target(
    conn: psycopg2.extensions.connection, genre_slug: str, tag_slug: str
) -> tuple[int, str]:
    """Pick a representative recent winner; fall back to oldest available winner."""
    sql_recent = (
        _SQL_PEER_TOP10
        + """
SELECT g.appid, g.name
FROM peer_top10 pt
JOIN tags t ON t.id = pt.tag_id AND t.slug = %(tag_slug)s
JOIN game_genres gg ON gg.appid = pt.appid
JOIN genres gn ON gn.id = gg.genre_id AND gn.slug = %(genre_slug)s
JOIN games g ON g.appid = pt.appid
WHERE pt.rnk <= %(top_n)s
  AND g.coming_soon = FALSE
  AND g.positive_pct >= %(winner_positive)s
  AND g.review_count BETWEEN %(rc_lo)s AND %(rc_hi)s
  AND g.release_date >= now() - (%(months)s || ' months')::interval
ORDER BY g.release_date DESC NULLS LAST, g.appid ASC
LIMIT 1
"""
    )
    sql_fallback = (
        _SQL_PEER_TOP10
        + """
SELECT g.appid, g.name
FROM peer_top10 pt
JOIN tags t ON t.id = pt.tag_id AND t.slug = %(tag_slug)s
JOIN game_genres gg ON gg.appid = pt.appid
JOIN genres gn ON gn.id = gg.genre_id AND gn.slug = %(genre_slug)s
JOIN games g ON g.appid = pt.appid
WHERE pt.rnk <= %(top_n)s
  AND g.coming_soon = FALSE
  AND g.review_count >= %(winner_reviews)s
  AND g.positive_pct >= %(winner_positive)s
ORDER BY g.release_date ASC NULLS LAST, g.appid ASC
LIMIT 1
"""
    )
    with conn.cursor() as cur:
        cur.execute(
            sql_recent,
            {
                "genre_slug": genre_slug,
                "tag_slug": tag_slug,
                "top_n": TOP_TAG_LIMIT,
                "winner_positive": WINNER_POSITIVE_FLOOR,
                "rc_lo": SUGGESTED_REVIEW_LO,
                "rc_hi": SUGGESTED_REVIEW_HI,
                "months": RECENT_WINNER_MONTHS,
            },
        )
        row = cur.fetchone()
        if row:
            return int(row["appid"]), row["name"]
        cur.execute(
            sql_fallback,
            {
                "genre_slug": genre_slug,
                "tag_slug": tag_slug,
                "top_n": TOP_TAG_LIMIT,
                "winner_reviews": WINNER_REVIEW_FLOOR,
                "winner_positive": WINNER_POSITIVE_FLOOR,
            },
        )
        row = cur.fetchone()
        if row:
            return int(row["appid"]), row["name"]
    return 0, ""


def build_candidate(
    row: dict[str, Any], suggested: tuple[int, str]
) -> NicheCandidate:
    """Map a stats row + suggested target into a NicheCandidate."""
    last_yr = int(row["releases_last_year"] or 0)
    prior_avg = float(row["releases_3yr_ago_avg"] or 0.0)
    growth = (last_yr - prior_avg) / max(prior_avg, 1.0)
    top_dev = row.get("top_winner_developer") or ""
    is_aaa = bool(row.get("all_winners_aaa"))
    return NicheCandidate(
        genre_slug=row["genre_slug"],
        modifier_tag_slug=row["tag_slug"],
        label=f"{row['genre_slug']}+{row['tag_slug']}",
        game_count=int(row["game_count"]),
        aggregate_reviews_last_12mo=int(row["aggregate_reviews_last_12mo"] or 0),
        median_positive_pct_500plus=round(float(row["median_positive_pct_500plus"] or 0.0), 2),
        revenue_p25=round(float(row["revenue_p25"] or 0.0), 2),
        revenue_p50=round(float(row["revenue_p50"] or 0.0), 2),
        revenue_p75=round(float(row["revenue_p75"] or 0.0), 2),
        revenue_p90=round(float(row["revenue_p90"] or 0.0), 2),
        top2_revenue_share=round(float(row["top2_revenue_share"] or 0.0), 4),
        median_price_usd=round(float(row["median_price_usd"] or 0.0), 2),
        free_to_play_pct=round(float(row["free_to_play_pct"] or 0.0), 4),
        releases_last_year=last_yr,
        releases_3yr_ago_avg=round(prior_avg, 2),
        growth_yoy_3yr_avg=round(growth, 4),
        top_winner_developer=top_dev,
        top_winner_revenue_usd=round(float(row.get("top_winner_revenue_usd") or 0.0), 2),
        is_aaa_dominated=is_aaa,
        suggested_target_appid=suggested[0],
        suggested_target_name=suggested[1],
    )


def score_candidate(candidate: NicheCandidate, releases_recent_window: int) -> NicheCandidateScore:
    """Pure scoring + disqualifier check. opportunity_score forced to 0 when disqualified."""
    demand = _demand_score(candidate.aggregate_reviews_last_12mo)
    growth = _growth_score(candidate.growth_yoy_3yr_avg)
    saturation = _saturation_penalty(candidate.growth_yoy_3yr_avg)
    quality = _quality_score(candidate.median_positive_pct_500plus)
    longtail = _longtail_score(candidate.top2_revenue_share)
    indie = _indie_scope_score(candidate.revenue_p50, candidate.top_winner_revenue_usd)
    not_aaa = _not_aaa_score(
        candidate.top_winner_developer,
        candidate.top_winner_revenue_usd,
        candidate.is_aaa_dominated,
    )

    raw_score = (
        WEIGHT_QUALITY * quality
        + WEIGHT_LONGTAIL * longtail
        + WEIGHT_DEMAND * demand
        + WEIGHT_GROWTH * growth
        + WEIGHT_SATURATION * saturation
        + WEIGHT_INDIE_SCOPE * indie
        + WEIGHT_NOT_AAA * not_aaa
    )

    reasons: list[str] = []
    if candidate.game_count < NICHE_GAME_FLOOR:
        reasons.append(f"below_floor (game_count={candidate.game_count})")
    if candidate.is_aaa_dominated:
        reasons.append(f"aaa_dominated (top_winner_developer={candidate.top_winner_developer})")
    if candidate.median_price_usd > 0 and candidate.median_price_usd < DISQUAL_MIN_PRICE:
        reasons.append(f"f2p_dominated (median_price_usd={candidate.median_price_usd:.2f})")
    if releases_recent_window <= 0:
        reasons.append(f"dead_market (0 releases in last {DISQUAL_DEAD_MARKET_MONTHS} months)")

    disqualified = bool(reasons)
    final_score = 0.0 if disqualified else _clip(raw_score, 0.0, 1.0)

    return NicheCandidateScore(
        candidate=candidate,
        demand_score=round(demand, 4),
        growth_score=round(growth, 4),
        saturation_penalty=round(saturation, 4),
        quality_score=round(quality, 4),
        longtail_score=round(longtail, 4),
        indie_scope_score=round(indie, 4),
        not_aaa_score=round(not_aaa, 4),
        opportunity_score=round(final_score, 4),
        disqualified=disqualified,
        disqualifier_reasons=reasons,
    )


def render_report(
    data: NicheScoutData, generated_at: datetime, verdict_markdown: str
) -> str:
    """Render the full markdown report. Verdict (when present) appears first."""
    lines: list[str] = []
    lines.append(
        f"# Niche Scout (Generated {generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')} against prod)"
    )
    lines.append("")
    if verdict_markdown:
        lines.append("## Verdict & Top Recommendations")
        lines.append("")
        lines.append(verdict_markdown.strip())
        lines.append("")

    lines.append("## Scan Summary")
    lines.append("")
    lines.append(f"- Genre filter: {data.genre_filter or '(none, all genres)'}")
    lines.append(f"- Candidates scanned: {data.candidates_scanned}")
    lines.append(f"- Candidates disqualified: {data.candidates_disqualified}")
    lines.append(f"- Top niches reported: {len(data.top_niches)}")
    lines.append("")

    lines.append("## Top Niches")
    lines.append("")
    lines.append(
        "| # | Niche | Score | Games | Pos % (500+) | Rev p50 | Growth YoY | Saturation | Suggested appid |"
    )
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, ns in enumerate(data.top_niches, start=1):
        c = ns.candidate
        rev = f"${c.revenue_p50:,.0f}" if c.revenue_p50 > 0 else "n/a"
        pos = f"{c.median_positive_pct_500plus:.1f}" if c.median_positive_pct_500plus > 0 else "n/a"
        suggested = c.suggested_target_appid if c.suggested_target_appid > 0 else "n/a"
        lines.append(
            f"| {i} | {c.label} | {ns.opportunity_score:.3f} | {c.game_count} | "
            f"{pos} | {rev} | {c.growth_yoy_3yr_avg:+.2f} | "
            f"{ns.saturation_penalty:.2f} | {suggested} |"
        )
    lines.append("")

    lines.append("## Per-Niche Detail")
    lines.append("")
    for ns in data.top_niches:
        c = ns.candidate
        summary = f"{c.label} (opportunity_score {ns.opportunity_score:.3f})"
        lines.append(f"<details><summary>{summary}</summary>")
        lines.append("")
        if ns.disqualified:
            lines.append(f"**Disqualified**: {', '.join(ns.disqualifier_reasons)}")
            lines.append("")
        lines.append(f"- game_count: {c.game_count}")
        lines.append(f"- aggregate_reviews_last_12mo: {c.aggregate_reviews_last_12mo:,}")
        lines.append(f"- median_positive_pct_500plus: {c.median_positive_pct_500plus:.2f}")
        lines.append(
            f"- revenue: p25 ${c.revenue_p25:,.0f} / p50 ${c.revenue_p50:,.0f} / "
            f"p75 ${c.revenue_p75:,.0f} / p90 ${c.revenue_p90:,.0f}"
        )
        lines.append(f"- top2_revenue_share: {c.top2_revenue_share:.3f}")
        lines.append(
            f"- median_price_usd: ${c.median_price_usd:.2f}; F2P pct: {c.free_to_play_pct:.3f}"
        )
        lines.append(
            f"- releases_last_year: {c.releases_last_year}; "
            f"releases_3yr_ago_avg: {c.releases_3yr_ago_avg:.2f}; "
            f"growth_yoy_3yr_avg: {c.growth_yoy_3yr_avg:+.3f}"
        )
        rev_top = (
            f"${c.top_winner_revenue_usd:,.0f}"
            if c.top_winner_revenue_usd > 0
            else "n/a"
        )
        lines.append(
            f"- top_winner_developer: {c.top_winner_developer or '(unknown)'} "
            f"(top_winner_revenue_usd: {rev_top}); "
            f"is_aaa_dominated: {c.is_aaa_dominated}"
        )
        lines.append("")
        lines.append("**Score breakdown**")
        lines.append(f"- quality_score: {ns.quality_score:.3f}")
        lines.append(f"- longtail_score: {ns.longtail_score:.3f}")
        lines.append(f"- demand_score: {ns.demand_score:.3f}")
        lines.append(f"- growth_score: {ns.growth_score:.3f}")
        lines.append(f"- saturation_penalty: {ns.saturation_penalty:.3f}")
        lines.append(f"- indie_scope_score: {ns.indie_scope_score:.3f}")
        lines.append(f"- not_aaa_score: {ns.not_aaa_score:.3f}")
        lines.append("")
        if c.suggested_target_appid > 0:
            lines.append(
                f"**Concept Doctor handoff**: "
                f"`poetry run python scripts/concept_doctor_v1.py --target-appid "
                f"{c.suggested_target_appid}` "
                f"({c.suggested_target_name})"
            )
        else:
            lines.append("**Concept Doctor handoff**: no qualifying winner found.")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def submit_batch_and_wait(api_key: str, data: NicheScoutData) -> str:
    """Submit a single-request Anthropic batch with the verdict prompt; return the markdown body."""
    client = anthropic.Anthropic(api_key=api_key)
    payload = data.model_dump_json(indent=2)
    user_text = f"{payload}\n\nProduce the verdict."
    requests = [
        {
            "custom_id": "niche_scout_v1",
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
        if entry.custom_id != "niche_scout_v1":
            continue
        if entry.result.type != "succeeded":
            print(f"ERROR: batch result type was {entry.result.type}", file=sys.stderr)
            sys.exit(6)
        for block in entry.result.message.content:
            if getattr(block, "type", None) == "text":
                return block.text
        print("ERROR: no text content in batch result", file=sys.stderr)
        sys.exit(7)

    print("ERROR: batch result for custom_id niche_scout_v1 not found", file=sys.stderr)
    sys.exit(8)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Niche Scout v1: scan the catalog for fertile (genre, modifier-tag) niches."
        )
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Cap the result list (default 20).",
    )
    parser.add_argument(
        "--genre",
        type=str,
        default=None,
        help="Constrain the scan to a single genre slug (e.g. rpg).",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Skip the LLM verdict and emit the data report only.",
    )
    args = parser.parse_args()

    generated_at = datetime.now(UTC)
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")

    conn = open_readonly_conn()
    try:
        rows = fetch_niche_stats(conn, args.genre)
        if not rows:
            print(
                "ERROR: no niches met the >= 30 game floor for the requested filter.",
                file=sys.stderr,
            )
            sys.exit(4)

        scored: list[NicheCandidateScore] = []
        for r in rows:
            top_appid = int(r["top_winner_appid"] or 0)
            top_name = r.get("top_winner_name") or ""
            suggested_seed = (top_appid, top_name)
            candidate = build_candidate(r, suggested_seed)
            scored.append(score_candidate(candidate, int(r["releases_recent_window"] or 0)))

        scored.sort(key=lambda s: (-s.opportunity_score, s.candidate.label))
        top_n = scored[: args.top]

        for ns in top_n:
            appid, name = pick_suggested_target(
                conn, ns.candidate.genre_slug, ns.candidate.modifier_tag_slug
            )
            if appid:
                ns.candidate.suggested_target_appid = appid
                ns.candidate.suggested_target_name = name
    finally:
        conn.close()

    candidates_disqualified = sum(1 for s in scored if s.disqualified)

    data = NicheScoutData(
        generated_at=generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        genre_filter=args.genre,
        candidates_scanned=len(scored),
        candidates_disqualified=candidates_disqualified,
        top_niches=top_n,
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
