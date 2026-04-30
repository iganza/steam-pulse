"""Concept Doctor v1: validate a target concept against its tag-coherent peer cohort."""

from __future__ import annotations

import argparse
import math
import os
import statistics
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

REPORTS_DIR = Path("reports/concept_doctor")
MODEL = "claude-opus-4-7"

DEV_TAG_LIMIT = 20
WEDGE_FINGERPRINT_SIZE = 5
NICHE_TAG_MIN_OVERLAP = 3

PEER_OVERLAP_TOP_N = 20
PEER_TOP_N = 10
PEER_REVIEW_FLOOR = 50
PEER_TAG_RICHNESS_FLOOR = 10
ELIGIBLE_REVIEW_FLOOR = 100
MIN_SHARED_TOP_TAGS = 2
MIN_REVIEWS_FOR_PHASE3 = 500

WINNER_REVIEW_FLOOR = 500
WINNER_POSITIVE_FLOOR = 80
LOSER_REVIEW_FLOOR = 50
LOSER_POSITIVE_CEIL = 60


TABLE_STAKES_WINNER_PCT = 0.80
DIFFERENTIATOR_WINNER_PCT = 0.40
DIFFERENTIATOR_LOSER_CEIL = 0.20
LOSER_WARNING_LOSER_PCT = 0.40
LOSER_WARNING_WINNER_CEIL = 0.10
TAG_DNA_LIST_CAP = 10

RELEASE_VELOCITY_YEARS = 5
SATURATION_GROWING_RATIO = 1.20
SATURATION_DECLINING_RATIO = 0.80

BATCH_POLL_SECONDS = 30
MAX_TOKENS = 6144
EXIT_MISSING_REPORTS = 9


class TagWithVotes(BaseModel):
    name: str
    votes: int


class TargetGame(BaseModel):
    appid: int
    name: str
    slug: str
    review_count: int
    positive_pct: int
    release_date: str | None


class CohortPeer(BaseModel):
    appid: int
    name: str
    review_count: int
    positive_pct: int
    estimated_revenue_usd: float | None
    price_usd: float | None
    release_year: int | None
    review_velocity_lifetime: float | None
    is_free: bool
    cohort: str
    overlap_score: float
    has_game_report: bool


class PeerSignals(BaseModel):
    appid: int
    name: str
    cohort: str
    review_count: int
    one_liner: str
    gameplay_friction: list[str]
    player_wishlist: list[str]
    churn_triggers: list[str]


class TagDNA(BaseModel):
    table_stakes: list[str]
    winning_differentiators: list[str]
    loser_warnings: list[str]


class MarketVitals(BaseModel):
    releases_per_year_last_5: dict[int, int]
    saturation_trend: str
    revenue_p25_winners: float
    revenue_median_winners: float
    revenue_p75_winners: float
    revenue_p90_winners: float
    success_rate_pct: float
    median_price_winners: float
    free_to_play_pct_winners: float
    top_decile_review_velocity: float | None
    niche_median_review_velocity: float | None


class ConceptDoctorData(BaseModel):
    target_appid: int
    target_name: str
    target_top_tags: list[TagWithVotes]
    wedge_fingerprint: list[str]
    peers: list[CohortPeer]
    winners_count: int
    losers_count: int
    peers_with_reports: int
    peers_stats_only: int
    market_vitals: MarketVitals
    tag_dna: TagDNA
    peer_signals: list[PeerSignals]


SYSTEM_PROMPT = """\
You are a senior indie game producer who has shipped 4 commercial hits and
2 commercial failures in the past decade.

<inputs>
You receive one ConceptDoctorData JSON document containing:
- target_appid, target_name, target_top_tags, wedge_fingerprint
- peers (the cohort split into winners / mid / losers; each row has
  cohort, review_count, positive_pct, estimated_revenue_usd, price_usd,
  release_year, has_game_report)
- market_vitals (revenue bands p25/p50/p75/p90 over winners, success
  rate, saturation trend, demand signal, pricing)
- tag_dna (table_stakes, winning_differentiators, loser_warnings)
- peer_signals: one entry per peer with a Phase-3 GameReport, carrying
  cohort, one_liner, and three flat list[str] fields (gameplay_friction,
  player_wishlist, churn_triggers). NOT pre-clustered. Each list item
  is the verbatim word of real player reviewers about that one game.
- peers_stats_only: peers below the report-eligibility floor; they
  contributed tag/revenue/velocity but no friction/wishlist signal.
</inputs>

<goal>
Produce a verdict for whether the operator should build something like
target_name. Be willing to say NO when the data warrants it.
</goal>

<signal_clustering_rules>
- A theme is significant only at >=3 peer mentions. Paraphrasing across
  peers is OK; cluster by topic (e.g. "build homogenization after hour
  ~40" matches "deck feels samey late game").
- Winner friction = themes mentioned by >=3 winners.
- Wishlist gaps = themes mentioned by >=3 peers across any cohort
  AND not delivered by any winner.
- Loser-specific friction = themes mentioned by >=3 losers AND not
  mentioned by any winner.
- Cite by peer count and appids in parentheses, e.g. "5 winners flag
  late-game homogenization (appid 1330460, 1486920, 296490, 280220,
  1291010)". Quote verbatim only when the source string is short
  enough to be readable inline.
- Do not cite a theme below the 3-peer threshold. Do not invent.
</signal_clustering_rules>

<output_rubric>
  <section role="verdict" length="1 sentence">
    GO, CONDITIONAL GO, or NO. Defend with 1-2 strongest facts from
    tag_dna or market_vitals.
  </section>
  <section role="revenue_band" length="1 sentence">
    "If you execute at the p50 of this niche, you make $X. p75: $Y.
    p90: $Z." Cite market_vitals.revenue_*_winners and success rate.
  </section>
  <section role="must_haves" length="5-8 items">
    Table-stakes features. Each item one line; cite a clustered theme
    (peer count + appids) OR a tag_dna.table_stakes /
    tag_dna.winning_differentiators row.
  </section>
  <section role="differentiation" length="4-6 items">
    Cover BOTH categories. Aim for at least one of each.
    (a) Tag-stack positioning gaps: combinations the target's tag
        profile carries that no winner in the cohort has shipped
        tightly. Reason from target_top_tags, tag_dna, and per-peer
        one_liners ("Becastled owns medieval city-building; Warpips
        owns modern autobattler; the medieval + autobattler + cards
        crossover is open"). Concept-positioning wedges, not features.
    (b) Wishlist-feature gaps: themes >=3 peers' player_wishlist
        arrays request that no winner has fully delivered.
    Cite specific peer appids or one_liners as evidence.
  </section>
  <section role="pitfalls" length="2-4 items">
    Loser-specific friction or tag_dna.loser_warnings. Each cited.
  </section>
  <section role="brutal_honesty" length="1 paragraph">
    State that this analysis says nothing about *the operator's*
    execution capacity. Quantify: of N peers, M shipped at sub-50%
    positive and K sit in the 60-67% "soft fail" band. Name the gap
    between data sufficiency and execution sufficiency.
  </section>
  <section role="cadence" length="1 sentence">
    Re-run Concept Doctor when the vertical slice is playable, and
    again at the 3-month-from-launch mark.
  </section>
</output_rubric>

<style>
- No invented features. No filler. No throat-clearing. Be blunt.
- Do not use em-dashes (the long horizontal dash). Use commas, colons,
  or parentheses instead. Hard rule.
- No corporate voice. No marketing adjectives ("immersive", "engaging",
  "rich"). Write like a senior designer talking to another senior
  designer over coffee.
- Use proper nouns and appids, not placeholders.
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


def fetch_target_game(conn: psycopg2.extensions.connection, appid: int) -> TargetGame:
    """Pull the target game's row from games."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT appid, name, slug, review_count, positive_pct, release_date "
            "FROM games WHERE appid = %s",
            (appid,),
        )
        row = cur.fetchone()
    if not row:
        print(f"ERROR: appid {appid} not found in games table.", file=sys.stderr)
        sys.exit(3)
    rd = row["release_date"]
    return TargetGame(
        appid=int(row["appid"]),
        name=row["name"],
        slug=row["slug"],
        review_count=int(row["review_count"] or 0),
        positive_pct=int(row["positive_pct"] or 0),
        release_date=rd.isoformat() if rd else None,
    )


def fetch_target_tags(
    conn: psycopg2.extensions.connection, appid: int, limit: int
) -> list[TagWithVotes]:
    """Pull the target's top-N tags by votes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT t.name, gt.votes FROM game_tags gt "
            "JOIN tags t ON t.id = gt.tag_id "
            "WHERE gt.appid = %s "
            "ORDER BY gt.votes DESC, t.name ASC "
            "LIMIT %s",
            (appid, limit),
        )
        rows = cur.fetchall()
    if not rows:
        print(
            f"ERROR: no tags found for appid {appid}. "
            "The target needs tag data to compute a peer cohort.",
            file=sys.stderr,
        )
        sys.exit(4)
    return [TagWithVotes(name=r["name"], votes=int(r["votes"])) for r in rows]


def fetch_target_top_tag_ids(
    conn: psycopg2.extensions.connection, appid: int, limit: int
) -> list[int]:
    """Pull the target's top-N tag ids; tiebreak on name ASC to match fetch_target_tags."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT t.id AS tag_id FROM game_tags gt "
            "JOIN tags t ON t.id = gt.tag_id "
            "WHERE gt.appid = %s "
            "ORDER BY gt.votes DESC, t.name ASC "
            "LIMIT %s",
            (appid, limit),
        )
        rows = cur.fetchall()
    return [int(r["tag_id"]) for r in rows]


def pick_cohort(
    conn: psycopg2.extensions.connection, appid: int, peers: int
) -> list[dict[str, Any]]:
    """Select peers by IDF-weighted cosine similarity, loosened review floor, no positive floor."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH eligible_games AS (
              SELECT appid FROM games WHERE review_count >= %(eligible_floor)s
            ),
            n_eligible AS (
              SELECT COUNT(*)::float AS n FROM eligible_games
            ),
            tag_idf AS (
              SELECT gt.tag_id,
                     GREATEST(
                       0.0,
                       LN(
                         (SELECT n FROM n_eligible) /
                         NULLIF(COUNT(DISTINCT gt.appid)::float, 0)
                       )
                     ) AS idf
              FROM game_tags gt
              JOIN eligible_games eg ON eg.appid = gt.appid
              GROUP BY gt.tag_id
            ),
            dev_ranked AS (
              SELECT tag_id, votes,
                     ROW_NUMBER() OVER (ORDER BY votes DESC, tag_id ASC) AS rnk,
                     SUM(votes) OVER () AS total_votes
              FROM game_tags
              WHERE appid = %(appid)s
            ),
            dev_top AS (
              SELECT d.tag_id,
                     d.votes::float / NULLIF(d.total_votes, 0) AS weight,
                     COALESCE(ti.idf, 0.0) AS idf
              FROM dev_ranked d
              LEFT JOIN tag_idf ti ON ti.tag_id = d.tag_id
              WHERE d.rnk <= %(top_n)s
            ),
            peer_richness AS (
              SELECT appid, COUNT(*) AS tag_count
              FROM game_tags
              WHERE votes > 0
              GROUP BY appid
            ),
            candidate_peers AS (
              SELECT g.appid
              FROM games g
              JOIN peer_richness pr ON pr.appid = g.appid
              WHERE g.appid != %(appid)s
                AND g.review_count >= %(review_floor)s
                AND pr.tag_count >= %(richness_floor)s
            ),
            peer_ranked AS (
              SELECT gt.appid, gt.tag_id, gt.votes,
                     ROW_NUMBER() OVER (
                       PARTITION BY gt.appid
                       ORDER BY gt.votes DESC, gt.tag_id ASC
                     ) AS rnk,
                     SUM(gt.votes) OVER (PARTITION BY gt.appid) AS total_votes
              FROM game_tags gt
              JOIN candidate_peers cp ON cp.appid = gt.appid
            ),
            peer_top AS (
              SELECT appid, tag_id,
                     votes::float / NULLIF(total_votes, 0) AS weight
              FROM peer_ranked
              WHERE rnk <= %(top_n)s
            )
            SELECT g.appid, g.name, g.review_count, g.positive_pct,
                   g.estimated_revenue_usd, g.price_usd, g.is_free,
                   EXTRACT(YEAR FROM g.release_date)::int AS release_year,
                   g.review_velocity_lifetime,
                   SUM(pt.weight * dt.weight * dt.idf * dt.idf) AS overlap_score,
                   COUNT(*) AS shared_top_tag_count
            FROM peer_top pt
            JOIN dev_top dt ON dt.tag_id = pt.tag_id
            JOIN games g ON g.appid = pt.appid
            GROUP BY g.appid, g.name, g.review_count, g.positive_pct,
                     g.estimated_revenue_usd, g.price_usd, g.is_free,
                     g.release_date, g.review_velocity_lifetime
            HAVING COUNT(*) >= %(min_shared)s
            ORDER BY overlap_score DESC, g.appid ASC
            LIMIT %(peers)s
            """,
            {
                "appid": appid,
                "top_n": PEER_OVERLAP_TOP_N,
                "review_floor": PEER_REVIEW_FLOOR,
                "eligible_floor": ELIGIBLE_REVIEW_FLOOR,
                "richness_floor": PEER_TAG_RICHNESS_FLOOR,
                "min_shared": MIN_SHARED_TOP_TAGS,
                "peers": peers,
            },
        )
        return [dict(r) for r in cur.fetchall()]


def partition_cohort(
    rows: list[dict[str, Any]], reports_by_appid: dict[int, dict[str, Any]]
) -> list[CohortPeer]:
    """Label each peer as winner / mid / loser by review_count and positive_pct."""
    peers: list[CohortPeer] = []
    for r in rows:
        review_count = int(r["review_count"] or 0)
        positive_pct = int(r["positive_pct"] or 0)
        if review_count >= WINNER_REVIEW_FLOOR and positive_pct >= WINNER_POSITIVE_FLOOR:
            cohort = "winner"
        elif review_count >= LOSER_REVIEW_FLOOR and positive_pct < LOSER_POSITIVE_CEIL:
            cohort = "loser"
        else:
            cohort = "mid"
        rev = r.get("estimated_revenue_usd")
        price = r.get("price_usd")
        velocity = r.get("review_velocity_lifetime")
        peers.append(
            CohortPeer(
                appid=int(r["appid"]),
                name=r["name"],
                review_count=review_count,
                positive_pct=positive_pct,
                estimated_revenue_usd=float(rev) if rev is not None else None,
                price_usd=float(price) if price is not None else None,
                release_year=int(r["release_year"]) if r.get("release_year") is not None else None,
                review_velocity_lifetime=float(velocity) if velocity is not None else None,
                is_free=bool(r.get("is_free") or False),
                cohort=cohort,
                overlap_score=round(float(r.get("overlap_score") or 0.0), 6),
                has_game_report=int(r["appid"]) in reports_by_appid,
            )
        )
    return peers


def preflight_reports_coverage(
    conn: psycopg2.extensions.connection, peer_appids: list[int]
) -> list[dict[str, Any]]:
    """Return peers >= MIN_REVIEWS_FOR_PHASE3 that lack a report (the actionable bail list)."""
    if not peer_appids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.appid, g.name, g.review_count
            FROM games g
            LEFT JOIN reports r ON r.appid = g.appid
            WHERE g.appid = ANY(%s)
              AND r.appid IS NULL
              AND g.review_count >= %s
            ORDER BY g.review_count DESC NULLS LAST
            """,
            (peer_appids, MIN_REVIEWS_FOR_PHASE3),
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_game_reports(
    conn: psycopg2.extensions.connection, peer_appids: list[int]
) -> dict[int, dict[str, Any]]:
    """Pull report_json + analyzer metadata for the cohort. Keyed by appid."""
    if not peer_appids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT appid, report_json, reviews_analyzed, analysis_version "
            "FROM reports WHERE appid = ANY(%s)",
            (peer_appids,),
        )
        rows = cur.fetchall()
    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        out[int(r["appid"])] = {
            "report": r["report_json"] or {},
            "reviews_analyzed": int(r["reviews_analyzed"] or 0),
            "analysis_version": r["analysis_version"] or "",
        }
    return out


def fetch_peer_top_tags(
    conn: psycopg2.extensions.connection, peer_appids: list[int]
) -> dict[int, list[TagWithVotes]]:
    """Return each peer's top-10 tags by votes, keyed by appid."""
    if not peer_appids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT gt.appid, t.name, gt.votes,
                   ROW_NUMBER() OVER (
                     PARTITION BY gt.appid
                     ORDER BY gt.votes DESC, t.name ASC
                   ) AS rnk
            FROM game_tags gt
            JOIN tags t ON t.id = gt.tag_id
            WHERE gt.appid = ANY(%s) AND gt.votes > 0
            """,
            (peer_appids,),
        )
        rows = cur.fetchall()
    by_peer: dict[int, list[TagWithVotes]] = {}
    for r in rows:
        if int(r["rnk"]) > PEER_TOP_N:
            continue
        by_peer.setdefault(int(r["appid"]), []).append(
            TagWithVotes(name=r["name"], votes=int(r["votes"]))
        )
    for tags in by_peer.values():
        tags.sort(key=lambda t: (-t.votes, t.name))
    return by_peer


def fetch_market_vitals(
    conn: psycopg2.extensions.connection,
    wedge_tag_ids: list[int],
    peers: list[CohortPeer],
) -> MarketVitals:
    """Compute the five market-vitals signals; SQL for niche-wide stats, Python for cohort stats."""
    releases_per_year, niche_total, niche_winners, niche_median_velocity = (
        _fetch_niche_stats(conn, wedge_tag_ids)
    )
    saturation_trend = _saturation_trend(releases_per_year)
    success_rate_pct = (niche_winners / niche_total * 100.0) if niche_total > 0 else 0.0

    winners = [p for p in peers if p.cohort == "winner"]

    winner_revenues = sorted(
        float(p.estimated_revenue_usd) for p in winners if p.estimated_revenue_usd is not None
    )
    p25, p50, p75, p90 = _quartile_bands(winner_revenues)

    winner_prices = [
        float(p.price_usd) for p in winners if p.price_usd is not None and not p.is_free
    ]
    median_price_winners = statistics.median(winner_prices) if winner_prices else 0.0
    free_to_play_pct_winners = (
        (sum(1 for p in winners if p.is_free) / len(winners) * 100.0) if winners else 0.0
    )

    top_decile_velocity = _top_decile_velocity(winners)

    return MarketVitals(
        releases_per_year_last_5=releases_per_year,
        saturation_trend=saturation_trend,
        revenue_p25_winners=p25,
        revenue_median_winners=p50,
        revenue_p75_winners=p75,
        revenue_p90_winners=p90,
        success_rate_pct=round(success_rate_pct, 2),
        median_price_winners=round(float(median_price_winners), 2),
        free_to_play_pct_winners=round(free_to_play_pct_winners, 2),
        top_decile_review_velocity=(
            round(top_decile_velocity, 4) if top_decile_velocity is not None else None
        ),
        niche_median_review_velocity=(
            round(niche_median_velocity, 4) if niche_median_velocity is not None else None
        ),
    )


def _fetch_niche_stats(
    conn: psycopg2.extensions.connection, wedge_tag_ids: list[int]
) -> tuple[dict[int, int], int, int, float | None]:
    """Run the niche CTE three ways: per-year release counts, totals, and median velocity."""
    if not wedge_tag_ids:
        return {}, 0, 0, None
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH wedge_ids AS (
              SELECT UNNEST(%(wedge)s::int[]) AS tag_id
            ),
            peer_top10 AS (
              SELECT gt.appid, gt.tag_id,
                     ROW_NUMBER() OVER (
                       PARTITION BY gt.appid
                       ORDER BY gt.votes DESC, gt.tag_id ASC
                     ) AS rnk
              FROM game_tags gt
              WHERE gt.votes > 0
            ),
            niche_games AS (
              SELECT pt.appid
              FROM peer_top10 pt
              JOIN wedge_ids w ON w.tag_id = pt.tag_id
              WHERE pt.rnk <= %(top_n)s
              GROUP BY pt.appid
              HAVING COUNT(*) >= %(min_overlap)s
            )
            SELECT EXTRACT(YEAR FROM g.release_date)::int AS yr, COUNT(*)::int AS n
            FROM games g
            JOIN niche_games ng ON ng.appid = g.appid
            WHERE g.release_date IS NOT NULL
              AND g.coming_soon = FALSE
              AND g.release_date >= (NOW() - (%(years)s || ' years')::interval)
            GROUP BY yr
            ORDER BY yr
            """,
            {
                "wedge": wedge_tag_ids,
                "top_n": PEER_TOP_N,
                "min_overlap": NICHE_TAG_MIN_OVERLAP,
                "years": RELEASE_VELOCITY_YEARS,
            },
        )
        per_year_rows = cur.fetchall()

        cur.execute(
            """
            WITH wedge_ids AS (
              SELECT UNNEST(%(wedge)s::int[]) AS tag_id
            ),
            peer_top10 AS (
              SELECT gt.appid, gt.tag_id,
                     ROW_NUMBER() OVER (
                       PARTITION BY gt.appid
                       ORDER BY gt.votes DESC, gt.tag_id ASC
                     ) AS rnk
              FROM game_tags gt
              WHERE gt.votes > 0
            ),
            niche_games AS (
              SELECT pt.appid
              FROM peer_top10 pt
              JOIN wedge_ids w ON w.tag_id = pt.tag_id
              WHERE pt.rnk <= %(top_n)s
              GROUP BY pt.appid
              HAVING COUNT(*) >= %(min_overlap)s
            )
            SELECT
              COUNT(*)::int AS niche_total,
              COUNT(*) FILTER (WHERE g.review_count >= %(winner_floor)s)::int AS niche_winners,
              percentile_cont(0.5) WITHIN GROUP (
                ORDER BY g.review_velocity_lifetime
              ) FILTER (WHERE g.review_velocity_lifetime IS NOT NULL)::float AS niche_median_velocity
            FROM games g
            JOIN niche_games ng ON ng.appid = g.appid
            """,
            {
                "wedge": wedge_tag_ids,
                "top_n": PEER_TOP_N,
                "min_overlap": NICHE_TAG_MIN_OVERLAP,
                "winner_floor": WINNER_REVIEW_FLOOR,
            },
        )
        scalar_row = cur.fetchone() or {}

    releases_per_year: dict[int, int] = {int(r["yr"]): int(r["n"]) for r in per_year_rows}
    raw_velocity = scalar_row.get("niche_median_velocity")
    return (
        releases_per_year,
        int(scalar_row.get("niche_total") or 0),
        int(scalar_row.get("niche_winners") or 0),
        float(raw_velocity) if raw_velocity is not None else None,
    )


def _saturation_trend(releases_per_year: dict[int, int]) -> str:
    """Compare avg of last 2 years vs first 3 years to label growing/stable/declining."""
    if not releases_per_year:
        return "stable"
    years_sorted = sorted(releases_per_year.keys())
    if len(years_sorted) < 4:
        return "stable"
    first3 = [releases_per_year[y] for y in years_sorted[:3]]
    last2 = [releases_per_year[y] for y in years_sorted[-2:]]
    avg_first = sum(first3) / len(first3) if first3 else 0.0
    avg_last = sum(last2) / len(last2) if last2 else 0.0
    if avg_first <= 0:
        return "growing" if avg_last > 0 else "stable"
    ratio = avg_last / avg_first
    if ratio > SATURATION_GROWING_RATIO:
        return "growing"
    if ratio < SATURATION_DECLINING_RATIO:
        return "declining"
    return "stable"


def _quartile_bands(values_sorted: list[float]) -> tuple[float, float, float, float]:
    """Return (p25, p50, p75, p90). Falls back to 0.0 when sample size is insufficient."""
    if len(values_sorted) < 2:
        return 0.0, 0.0, 0.0, 0.0
    n = len(values_sorted)

    def pct(p: float) -> float:
        if n == 1:
            return values_sorted[0]
        rank = p * (n - 1)
        lo = int(math.floor(rank))
        hi = int(math.ceil(rank))
        if lo == hi:
            return values_sorted[lo]
        frac = rank - lo
        return values_sorted[lo] + (values_sorted[hi] - values_sorted[lo]) * frac

    return (
        round(pct(0.25), 2),
        round(pct(0.50), 2),
        round(pct(0.75), 2),
        round(pct(0.90), 2),
    )


def _top_decile_velocity(winners: list[CohortPeer]) -> float | None:
    """Median review_velocity_lifetime over the top decile of winners; None if no data."""
    velocities = sorted(
        (float(p.review_velocity_lifetime) for p in winners if p.review_velocity_lifetime is not None),
        reverse=True,
    )
    if not velocities:
        return None
    decile_size = max(1, math.ceil(len(velocities) * 0.1))
    return float(statistics.median(velocities[:decile_size]))


def compute_tag_dna(
    peer_top_tags_by_appid: dict[int, list[TagWithVotes]], peers: list[CohortPeer]
) -> TagDNA:
    """Compare per-tag presence in winner top-10 vs loser top-10 to label DNA."""
    winners = [p.appid for p in peers if p.cohort == "winner"]
    losers = [p.appid for p in peers if p.cohort == "loser"]
    n_w = len(winners) or 1
    n_l = len(losers) or 1

    winner_tags: dict[str, int] = {}
    loser_tags: dict[str, int] = {}
    for appid in winners:
        for t in peer_top_tags_by_appid.get(appid, []):
            winner_tags[t.name] = winner_tags.get(t.name, 0) + 1
    for appid in losers:
        for t in peer_top_tags_by_appid.get(appid, []):
            loser_tags[t.name] = loser_tags.get(t.name, 0) + 1

    all_tags = set(winner_tags) | set(loser_tags)
    table_stakes: list[tuple[str, float]] = []
    differentiators: list[tuple[str, float, float]] = []
    loser_warnings: list[tuple[str, float, float]] = []
    for tag in all_tags:
        wp = winner_tags.get(tag, 0) / n_w
        lp = loser_tags.get(tag, 0) / n_l
        if wp >= TABLE_STAKES_WINNER_PCT:
            table_stakes.append((tag, wp))
        if wp >= DIFFERENTIATOR_WINNER_PCT and lp <= DIFFERENTIATOR_LOSER_CEIL:
            differentiators.append((tag, wp, lp))
        if lp >= LOSER_WARNING_LOSER_PCT and wp <= LOSER_WARNING_WINNER_CEIL:
            loser_warnings.append((tag, wp, lp))

    table_stakes.sort(key=lambda x: (-x[1], x[0]))
    differentiators.sort(key=lambda x: (-(x[1] - x[2]), x[0]))
    loser_warnings.sort(key=lambda x: (-(x[2] - x[1]), x[0]))

    return TagDNA(
        table_stakes=[t for t, _ in table_stakes[:TAG_DNA_LIST_CAP]],
        winning_differentiators=[t for t, _, _ in differentiators[:TAG_DNA_LIST_CAP]],
        loser_warnings=[t for t, _, _ in loser_warnings[:TAG_DNA_LIST_CAP]],
    )


def gather_peer_signals(
    reports_by_appid: dict[int, dict[str, Any]], peers: list[CohortPeer]
) -> list[PeerSignals]:
    """One PeerSignals per peer with a Phase-3 report. Clustering happens in the verdict LLM."""
    cohort_by_appid = {p.appid: p.cohort for p in peers}
    name_by_appid = {p.appid: p.name for p in peers}
    rc_by_appid = {p.appid: p.review_count for p in peers}
    out: list[PeerSignals] = []
    for appid, payload in reports_by_appid.items():
        cohort = cohort_by_appid.get(appid)
        if cohort is None:
            continue
        report = payload.get("report") or {}
        out.append(
            PeerSignals(
                appid=appid,
                name=name_by_appid.get(appid, ""),
                cohort=cohort,
                review_count=rc_by_appid.get(appid, 0),
                one_liner=str(report.get("one_liner") or ""),
                gameplay_friction=[
                    s for s in (report.get("gameplay_friction") or []) if isinstance(s, str)
                ],
                player_wishlist=[
                    s for s in (report.get("player_wishlist") or []) if isinstance(s, str)
                ],
                churn_triggers=[
                    s for s in (report.get("churn_triggers") or []) if isinstance(s, str)
                ],
            )
        )
    out.sort(key=lambda s: (s.cohort != "winner", s.cohort != "mid", -s.review_count))
    return out


def render_report(
    target: TargetGame,
    data: ConceptDoctorData,
    generated_at: datetime,
    verdict_markdown: str | None,
) -> str:
    """Render the full markdown report. Verdict (when present) appears first."""
    lines: list[str] = []
    lines.append(f'# Concept Doctor for "{data.target_name}" (appid {data.target_appid})')
    lines.append("")
    lines.append(f"Generated {generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')} against prod")
    lines.append("")
    lines.append(f"- Target reviews: {target.review_count}, positive: {target.positive_pct}%")
    if target.release_date:
        lines.append(f"- Target release date: {target.release_date}")
    lines.append("")

    if verdict_markdown:
        lines.append("## Verdict & Reality Check")
        lines.append("")
        lines.append(verdict_markdown.strip())
        lines.append("")

    n_total = len(data.peers)
    n_mid = n_total - data.winners_count - data.losers_count
    lines.append("## The Niche")
    lines.append("")
    lines.append(f"- Wedge fingerprint: {', '.join(data.wedge_fingerprint) or '(none)'}")
    lines.append(
        f"- Peer cohort: {n_total} total, {data.winners_count} winners / "
        f"{n_mid} mid / {data.losers_count} losers"
    )
    lines.append(f"- Peers with Phase-3 reports: {data.peers_with_reports}/{n_total}")
    if data.peers_stats_only:
        lines.append(
            f"- Stats-only peers: {data.peers_stats_only} "
            f"(review count below {MIN_REVIEWS_FOR_PHASE3}; tag/revenue/velocity counted, "
            "no friction/wishlist signal)"
        )
    lines.append("")

    mv = data.market_vitals
    lines.append("## Market Vitals")
    lines.append("")
    if mv.releases_per_year_last_5:
        years = sorted(mv.releases_per_year_last_5.keys())
        header = "| " + " | ".join(str(y) for y in years) + " |"
        sep = "|" + "|".join(["---:"] * len(years)) + "|"
        row = "| " + " | ".join(str(mv.releases_per_year_last_5[y]) for y in years) + " |"
        lines.append("Niche releases per year (>=3 of wedge tags in top 10):")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        lines.append(row)
        lines.append("")
    lines.append(f"- Saturation trend: {mv.saturation_trend}")
    lines.append(
        f"- Winner revenue band: p25 ${mv.revenue_p25_winners:,.0f} / "
        f"median ${mv.revenue_median_winners:,.0f} / "
        f"p75 ${mv.revenue_p75_winners:,.0f} / "
        f"p90 ${mv.revenue_p90_winners:,.0f}"
    )
    lines.append(f"- Niche success rate (>=500 reviews): {mv.success_rate_pct:.1f}%")
    if mv.top_decile_review_velocity is None and mv.niche_median_review_velocity is None:
        lines.append(
            "- Demand signal: not available (review_velocity_lifetime not populated for this cohort)"
        )
    else:
        td = (
            f"{mv.top_decile_review_velocity:.2f}"
            if mv.top_decile_review_velocity is not None
            else "n/a"
        )
        nm = (
            f"{mv.niche_median_review_velocity:.2f}"
            if mv.niche_median_review_velocity is not None
            else "n/a"
        )
        lines.append(f"- Demand signal: top-decile Winner velocity {td} vs niche median {nm}")
    lines.append(
        f"- Pricing: median Winner price ${mv.median_price_winners:.2f}; "
        f"{mv.free_to_play_pct_winners:.1f}% F2P among Winners"
    )
    lines.append("")

    lines.append("## Table-Stakes Tags")
    lines.append("")
    if not data.tag_dna.table_stakes:
        lines.append("_No tag carried by >=80% of Winners._")
    else:
        for t in data.tag_dna.table_stakes:
            lines.append(f"- {t}")
    lines.append("")

    lines.append("## Winning Differentiators")
    lines.append("")
    if not data.tag_dna.winning_differentiators:
        lines.append("_No differentiator tags found above thresholds._")
    else:
        for t in data.tag_dna.winning_differentiators:
            lines.append(f"- {t}")
    lines.append("")

    lines.append("## Loser Warning Signs")
    lines.append("")
    if not data.tag_dna.loser_warnings:
        lines.append("_No loser-warning tags found above thresholds._")
    else:
        for t in data.tag_dna.loser_warnings:
            lines.append(f"- {t}")
    lines.append("")

    lines.append("## Per-Peer Friction / Wishlist / Churn Signals")
    lines.append("")
    if not data.peer_signals:
        lines.append("_No peer reports available._")
        lines.append("")
    else:
        lines.append(
            "_Raw per-peer signals from each peer's GameReport. Clustering across peers "
            "(>=3 peers per theme) is done by the verdict LLM, not pre-aggregated._"
        )
        lines.append("")
        for s in data.peer_signals:
            summary = (
                f"{s.name} (appid {s.appid}) - {s.cohort}, {s.review_count} reviews"
            )
            lines.append(f"<details><summary>{summary}</summary>")
            lines.append("")
            if s.one_liner:
                lines.append(f"_{s.one_liner}_")
                lines.append("")
            if s.gameplay_friction:
                lines.append("**Gameplay friction**")
                for item in s.gameplay_friction:
                    lines.append(f"- {item}")
                lines.append("")
            if s.player_wishlist:
                lines.append("**Player wishlist**")
                for item in s.player_wishlist:
                    lines.append(f"- {item}")
                lines.append("")
            if s.churn_triggers:
                lines.append("**Churn triggers**")
                for item in s.churn_triggers:
                    lines.append(f"- {item}")
                lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.append("## Peer Cohort")
    lines.append("")
    lines.append(
        "| Peer | Reviews | Pos % | Cohort | Revenue | Price | Year | Sim | Has Report |"
    )
    lines.append("|---|---:|---:|---|---:|---:|---:|---:|:---:|")
    for p in data.peers:
        rev = f"${p.estimated_revenue_usd:,.0f}" if p.estimated_revenue_usd is not None else "n/a"
        price = "free" if p.is_free else (f"${p.price_usd:.2f}" if p.price_usd is not None else "n/a")
        year = str(p.release_year) if p.release_year is not None else "n/a"
        rep = "yes" if p.has_game_report else "no"
        lines.append(
            f"| {p.name} (appid {p.appid}) | {p.review_count} | {p.positive_pct} | "
            f"{p.cohort} | {rev} | {price} | {year} | {p.overlap_score:.4f} | {rep} |"
        )
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def submit_batch_and_wait(api_key: str, data: ConceptDoctorData) -> str:
    """Submit a single-request Anthropic batch with the verdict prompt; return the markdown body."""
    client = anthropic.Anthropic(api_key=api_key)
    payload = data.model_dump_json(indent=2)
    user_text = f"{payload}\n\nProduce the verdict."
    requests = [
        {
            "custom_id": "concept_doctor_v1",
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
        if entry.custom_id != "concept_doctor_v1":
            continue
        if entry.result.type != "succeeded":
            print(f"ERROR: batch result type was {entry.result.type}", file=sys.stderr)
            sys.exit(6)
        for block in entry.result.message.content:
            if getattr(block, "type", None) == "text":
                return block.text
        print("ERROR: no text content in batch result", file=sys.stderr)
        sys.exit(7)

    print("ERROR: batch result for custom_id concept_doctor_v1 not found", file=sys.stderr)
    sys.exit(8)


def _print_missing_peers_and_exit(missing: list[dict[str, Any]], total_peers: int) -> None:
    """Render the bail block for missing Phase-3 reports and exit non-zero. No file writes."""
    print(
        f"Concept Doctor needs Phase-3 reports for {len(missing)} of {total_peers} peers "
        f"(only listing peers with >= {MIN_REVIEWS_FOR_PHASE3} reviews; smaller peers "
        f"will never produce a report and are kept stats-only). "
        f"Run Phase 1-3 on the appids below, then re-run.",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    print("appid       reviews  name", file=sys.stderr)
    for r in missing:
        appid = int(r["appid"])
        rc = int(r["review_count"] or 0)
        name = r["name"]
        print(f"{appid:<11}{rc:>7}  {name}", file=sys.stderr)
    sys.exit(EXIT_MISSING_REPORTS)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Concept Doctor v1: validate a target concept against its tag-coherent peer cohort."
        )
    )
    parser.add_argument(
        "--target-appid",
        type=int,
        required=True,
        help="Steam appid of the target peer game (the concept to validate against).",
    )
    parser.add_argument("--peers", type=int, default=30, help="Peer set cap (default 30).")
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
        target = fetch_target_game(conn, args.target_appid)
        target_tags = fetch_target_tags(conn, args.target_appid, DEV_TAG_LIMIT)
        wedge_tag_ids = fetch_target_top_tag_ids(
            conn, args.target_appid, WEDGE_FINGERPRINT_SIZE
        )
        cohort_rows = pick_cohort(conn, args.target_appid, args.peers)
        if not cohort_rows:
            print(
                "ERROR: no peers met the loosened cohort thresholds. "
                "Confirm the target has tags and the catalog has neighbors.",
                file=sys.stderr,
            )
            sys.exit(4)
        peer_appids = [int(r["appid"]) for r in cohort_rows]

        missing = preflight_reports_coverage(conn, peer_appids)
        if missing:
            _print_missing_peers_and_exit(missing, len(peer_appids))

        reports_by_appid = fetch_game_reports(conn, peer_appids)
        peers = partition_cohort(cohort_rows, reports_by_appid)
        peer_top_tags = fetch_peer_top_tags(conn, peer_appids)
        market_vitals = fetch_market_vitals(conn, wedge_tag_ids, peers)
    finally:
        conn.close()

    tag_dna = compute_tag_dna(peer_top_tags, peers)
    peer_signals = gather_peer_signals(reports_by_appid, peers)

    wedge_fingerprint = [t.name for t in target_tags[:WEDGE_FINGERPRINT_SIZE]]
    winners_count = sum(1 for p in peers if p.cohort == "winner")
    losers_count = sum(1 for p in peers if p.cohort == "loser")
    peers_with_reports = sum(1 for p in peers if p.has_game_report)
    peers_stats_only = sum(1 for p in peers if not p.has_game_report)

    data = ConceptDoctorData(
        target_appid=target.appid,
        target_name=target.name,
        target_top_tags=target_tags,
        wedge_fingerprint=wedge_fingerprint,
        peers=peers,
        winners_count=winners_count,
        losers_count=losers_count,
        peers_with_reports=peers_with_reports,
        peers_stats_only=peers_stats_only,
        market_vitals=market_vitals,
        tag_dna=tag_dna,
        peer_signals=peer_signals,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data_path = REPORTS_DIR / f"{args.target_appid}_{timestamp}_data.json"
    data_path.write_text(data.model_dump_json(indent=2) + "\n")

    verdict_markdown: str | None = None
    if not args.data_only:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ERROR: ANTHROPIC_API_KEY not set (use --data-only to skip the verdict).",
                file=sys.stderr,
            )
            sys.exit(2)
        verdict_markdown = submit_batch_and_wait(api_key, data).strip()

    report = render_report(target, data, generated_at, verdict_markdown)
    md_path = REPORTS_DIR / f"{args.target_appid}_{timestamp}.md"
    md_path.write_text(report)

    print(report)
    print(f"\nWrote report to {md_path}")
    print(f"Wrote data to   {data_path}")


if __name__ == "__main__":
    main()
