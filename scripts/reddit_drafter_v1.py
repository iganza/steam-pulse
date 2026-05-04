"""Reddit Drafter v2: deterministic skeleton from a Phase 3 GameReport.

No LLM call. Pull report_json from prod, render a Reddit markdown draft,
attach the review pool as an appendix the operator picks quotes from.
"""

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extensions
import psycopg2.extras
from pydantic import BaseModel

REPORTS_DIR = Path("reports/reddit_drafts")

EXIT_BAD_ENV = 2
EXIT_NO_REPORT = 3


class ReviewSnippet(BaseModel):
    review_id: int
    voted_up: bool
    votes_helpful: int
    votes_funny: int
    playtime_hours: int
    body: str


class SourceBundle(BaseModel):
    appid: int
    game_name: str
    total_reviews_analyzed: int
    review_date_range_start: str
    review_date_range_end: str
    pipeline_version: str
    report_created_at: str
    review_count_total: int
    positive_pct: int
    genres: list[str]
    report_json: dict[str, Any]
    review_pool: list[ReviewSnippet]


class Finding(BaseModel):
    claim: str
    evidence: str


class RedditDrafterData(BaseModel):
    generated_at: str
    source: SourceBundle
    titles: list[str]
    tldr: str
    findings: list[Finding]


def open_readonly_conn() -> psycopg2.extensions.connection:
    """Open a read-only connection to prod via STEAMPULSE_PROD_DATABASE_URL."""
    url = os.environ.get("STEAMPULSE_PROD_DATABASE_URL")
    if not url:
        print(
            "ERROR: STEAMPULSE_PROD_DATABASE_URL is not set. "
            "This script reads from production; set the prod connection URL explicitly.",
            file=sys.stderr,
        )
        sys.exit(EXIT_BAD_ENV)
    try:
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    except psycopg2.Error as exc:
        print(f"ERROR: failed to connect to prod DB: {exc}", file=sys.stderr)
        sys.exit(EXIT_BAD_ENV)
    conn.set_session(readonly=True, autocommit=False)
    return conn


SOURCE_QUERY = """
SELECT
  r.report_json,
  r.analysis_version,
  r.created_at,
  g.name           AS game_name,
  g.appid,
  g.review_count,
  g.positive_pct,
  COALESCE(
    (SELECT array_agg(gn.slug ORDER BY gn.slug)
       FROM game_genres gg
       JOIN genres gn ON gn.id = gg.genre_id
      WHERE gg.appid = g.appid),
    ARRAY[]::text[]
  ) AS genres
FROM reports r
JOIN games g ON g.appid = r.appid
WHERE r.appid = %s
"""

REVIEW_POOL_QUERY = """
WITH top_helpful AS (
  SELECT id, voted_up, votes_helpful, votes_funny, playtime_hours, body
  FROM reviews
  WHERE appid = %s AND language = 'english' AND COALESCE(body, '') <> ''
  ORDER BY votes_helpful DESC NULLS LAST
  LIMIT 40
),
top_funny AS (
  SELECT id, voted_up, votes_helpful, votes_funny, playtime_hours, body
  FROM reviews
  WHERE appid = %s AND language = 'english' AND COALESCE(body, '') <> ''
  ORDER BY votes_funny DESC NULLS LAST
  LIMIT 15
)
SELECT id, voted_up, votes_helpful, votes_funny, playtime_hours, body
FROM (
  SELECT * FROM top_helpful
  UNION
  SELECT * FROM top_funny
) combined
ORDER BY votes_helpful DESC NULLS LAST, votes_funny DESC NULLS LAST
"""

REVIEW_BODY_MAX_CHARS = 1200


def load_review_pool(
    conn: psycopg2.extensions.connection, appid: int
) -> list[ReviewSnippet]:
    """Pull a curated pool of top reviews so the operator can cite verbatim."""
    with conn.cursor() as cur:
        cur.execute(REVIEW_POOL_QUERY, (appid, appid))
        rows = cur.fetchall()
    pool: list[ReviewSnippet] = []
    for r in rows:
        body = (r["body"] or "").strip()
        if not body:
            continue
        if len(body) > REVIEW_BODY_MAX_CHARS:
            body = body[:REVIEW_BODY_MAX_CHARS]
        pool.append(
            ReviewSnippet(
                review_id=int(r["id"]),
                voted_up=bool(r["voted_up"]),
                votes_helpful=int(r["votes_helpful"] or 0),
                votes_funny=int(r["votes_funny"] or 0),
                playtime_hours=int(r["playtime_hours"] or 0),
                body=body,
            )
        )
    return pool


def load_source_bundle(
    conn: psycopg2.extensions.connection, appid: int
) -> SourceBundle:
    """Pull the GameReport row, joined games metadata, and review citation pool."""
    with conn.cursor() as cur:
        cur.execute(SOURCE_QUERY, (appid,))
        row = cur.fetchone()
    if not row:
        print(
            f"No Phase 3 report for appid {appid}. Run analysis first.",
            file=sys.stderr,
        )
        sys.exit(EXIT_NO_REPORT)

    report_json = row["report_json"] or {}
    if isinstance(report_json, str):
        report_json = json.loads(report_json)

    review_pool = load_review_pool(conn, appid)

    return SourceBundle(
        appid=int(row["appid"]),
        game_name=row["game_name"] or "",
        total_reviews_analyzed=int(report_json.get("total_reviews_analyzed") or 0),
        review_date_range_start=str(report_json.get("review_date_range_start") or ""),
        review_date_range_end=str(report_json.get("review_date_range_end") or ""),
        pipeline_version=str(row["analysis_version"] or ""),
        report_created_at=row["created_at"].isoformat() if row["created_at"] else "",
        review_count_total=int(row["review_count"] or 0),
        positive_pct=int(row["positive_pct"] or 0),
        genres=list(row["genres"] or []),
        report_json=report_json,
        review_pool=review_pool,
    )


MENTION_COUNT_RE = re.compile(
    r"(\d+)\+?\s*(?:explicit\s+)?(?:mention|request)", re.IGNORECASE
)


def _extract_mention_count(text: str) -> int:
    """Pull the largest mention/request count out of a why_it_matters string."""
    if not text:
        return 0
    matches = MENTION_COUNT_RE.findall(text)
    return max((int(m) for m in matches), default=0)


def _rank_dev_priorities(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Sort dev_priorities by parsed mention count, descending."""
    priorities = report.get("dev_priorities") or []
    return sorted(
        priorities,
        key=lambda p: _extract_mention_count(p.get("why_it_matters", "")),
        reverse=True,
    )


def _first_sentence(text: str) -> str:
    """Return the first sentence of a string, stripped of trailing punctuation."""
    if not text:
        return ""
    parts = re.split(r"[.!?](?:\s|$)", text, maxsplit=1)
    return parts[0].strip() if parts else text.strip()


def _strip_trailing_period(text: str) -> str:
    s = (text or "").strip()
    while s.endswith("."):
        s = s[:-1]
    return s


def _sanitize(text: str) -> str:
    """Strip dashes that read as AI tells: em-dash to comma, en-dash to hyphen."""
    s = text or ""
    s = s.replace(" \u2014 ", ", ").replace("\u2014", ", ")
    s = s.replace(" \u2013 ", "-").replace("\u2013", "-")
    return s


def _pick_titles(bundle: SourceBundle) -> list[str]:
    """Three ranked title candidates for the operator to choose from."""
    report = bundle.report_json
    n = bundle.total_reviews_analyzed
    name = bundle.game_name
    pos = bundle.positive_pct
    ranked = _rank_dev_priorities(report)
    titles: list[str] = []

    if ranked:
        why = ranked[0].get("why_it_matters") or ""
        first = _first_sentence(why)
        if first:
            titles.append(f"I analyzed {n:,} reviews of {name}: {first}.")

    sp = report.get("store_page_alignment") or {}
    promises_broken = sp.get("promises_broken") or []
    if promises_broken:
        titles.append(
            f"{name} ({pos}% positive): {_strip_trailing_period(promises_broken[0])}"
        )

    hidden = sp.get("hidden_strengths") or []
    if hidden:
        titles.append(
            f"What {name} is hiding from its own store page: "
            f"{_strip_trailing_period(hidden[0])}"
        )

    friction = report.get("gameplay_friction") or []
    fallback_idx = 0
    while len(titles) < 3 and fallback_idx < len(friction):
        titles.append(
            f"After {n:,} reviews of {name}, the loudest complaint: "
            f"{_strip_trailing_period(friction[fallback_idx])}"
        )
        fallback_idx += 1

    while len(titles) < 3:
        titles.append(f"What {n:,} reviews of {name} actually say")

    return titles[:3]


def _build_tldr(bundle: SourceBundle) -> str:
    """One-paragraph TLDR stitched from one_liner, top why_it_matters, audience note."""
    report = bundle.report_json
    parts: list[str] = []
    parts.append(
        f"{bundle.total_reviews_analyzed:,} reviews of {bundle.game_name} "
        f"({bundle.positive_pct}% positive)"
    )
    one_liner = report.get("one_liner")
    if one_liner:
        parts.append(_strip_trailing_period(one_liner))
    ranked = _rank_dev_priorities(report)
    if ranked and ranked[0].get("why_it_matters"):
        parts.append(_strip_trailing_period(ranked[0]["why_it_matters"]))
    sp = report.get("store_page_alignment") or {}
    note = sp.get("audience_match_note")
    if note:
        parts.append(_strip_trailing_period(note))
    return ". ".join(parts) + "."


def _pick_findings(bundle: SourceBundle) -> list[Finding]:
    """Five fixed-slot findings drawn from report_json."""
    report = bundle.report_json
    ranked = _rank_dev_priorities(report)
    sp = report.get("store_page_alignment") or {}
    findings: list[Finding] = []

    if ranked:
        action = _strip_trailing_period(ranked[0].get("action", ""))
        evidence = (ranked[0].get("why_it_matters") or "").strip()
        if action:
            findings.append(Finding(claim=action, evidence=evidence))

    strengths = report.get("design_strengths") or []
    if strengths:
        findings.append(Finding(claim=_strip_trailing_period(strengths[0]), evidence=""))

    second_priority = ranked[1] if len(ranked) > 1 else None
    second_evidence = (
        (second_priority.get("why_it_matters") or "").strip()
        if second_priority
        else ""
    )
    promises_broken = sp.get("promises_broken") or []
    friction = report.get("gameplay_friction") or []
    if promises_broken:
        findings.append(
            Finding(
                claim=_strip_trailing_period(promises_broken[0]),
                evidence=second_evidence,
            )
        )
    elif friction:
        findings.append(
            Finding(
                claim=_strip_trailing_period(friction[0]),
                evidence=second_evidence,
            )
        )

    hidden = sp.get("hidden_strengths") or []
    if hidden:
        findings.append(
            Finding(
                claim=f"The store page is hiding a real strength: {_strip_trailing_period(hidden[0])}",
                evidence="",
            )
        )
    elif len(strengths) > 1:
        findings.append(Finding(claim=_strip_trailing_period(strengths[1]), evidence=""))

    churn = report.get("churn_triggers") or []
    wishlist = report.get("player_wishlist") or []
    content_signals = (report.get("content_depth") or {}).get("signals") or []
    extra_evidence = content_signals[0].strip() if content_signals else ""
    if churn:
        findings.append(
            Finding(claim=_strip_trailing_period(churn[0]), evidence=extra_evidence)
        )
    elif wishlist:
        findings.append(
            Finding(
                claim=f"The most-requested addition: {_strip_trailing_period(wishlist[0])}",
                evidence=extra_evidence,
            )
        )

    return findings


LIMITATIONS_PARAGRAPH = (
    "A few honest limits: English-language reviews only, post-launch only "
    "(no pre-release wishlist signal), Steam-only (no console / Epic / GOG), "
    "and Steam reviewers self-select toward the engaged minority, not the "
    "silent majority."
)

CTA_LINE = "Happy to run this on your game, drop the appid. DM me if you want the methodology."


def render_markdown(data: RedditDrafterData) -> str:
    """Render the full draft skeleton plus the review pool appendix."""
    src = data.source
    lines: list[str] = []

    lines.append(f"# Reddit Draft: {src.game_name} (appid {src.appid})")
    lines.append("")
    lines.append(f"- Generated at: {data.generated_at}")
    lines.append(
        f"- Source report: pipeline_version={src.pipeline_version}, "
        f"created_at={src.report_created_at}"
    )
    lines.append(
        f"- Reviews analyzed: {src.total_reviews_analyzed:,} "
        f"(Steam total all languages: {src.review_count_total:,}, "
        f"positive {src.positive_pct}%)"
    )
    lines.append(
        f"- Review date range: {src.review_date_range_start} to "
        f"{src.review_date_range_end}"
    )
    lines.append("")

    lines.append("## Candidate titles")
    lines.append("")
    for i, t in enumerate(data.titles, 1):
        lines.append(f"{i}. {_sanitize(t)}")
    lines.append("")

    lines.append("## TLDR")
    lines.append("")
    lines.append(_sanitize(data.tldr))
    lines.append("")

    lines.append("## Post body")
    lines.append("")
    lines.append(
        "[Personal hook: 1-2 sentences in your voice. Why you ran this, "
        "current project, a confession.]"
    )
    lines.append("")
    lines.append(
        f"I pulled {src.total_reviews_analyzed:,} English Steam reviews of "
        f"**{src.game_name}** through a small tool I built. The game sits at "
        f"{src.positive_pct}% positive. Reviews span "
        f"{src.review_date_range_start} to {src.review_date_range_end}."
    )
    lines.append("")
    lines.append("Some findings I found most interesting:")
    lines.append("")

    for i, f in enumerate(data.findings, 1):
        claim = _sanitize(_strip_trailing_period(f.claim))
        lines.append(f"**{i}. {claim}.**")
        lines.append("")
        if f.evidence:
            lines.append(_sanitize(f.evidence))
            lines.append("")
        lines.append(
            "> [Pick a verbatim quote from the review pool below that supports "
            "this finding. Trim middle text to `[...]` if needed; do not "
            "paraphrase.]"
        )
        lines.append(">")
        lines.append("> *N helpful, M funny (Xh playtime, recommended)*")
        lines.append("")

    lines.append(LIMITATIONS_PARAGRAPH)
    lines.append("")
    lines.append(CTA_LINE)
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Review pool (operator picks quotes from here)")
    lines.append("")
    lines.append(
        "Sorted by helpful votes, then funny votes. Pick the review whose body "
        "most directly supports each finding's claim. Trim to 1-2 punchy "
        "sentences with `[...]` for elided middles. Do NOT paraphrase."
    )
    lines.append("")

    for i, r in enumerate(src.review_pool, 1):
        verdict = "recommended" if r.voted_up else "did not recommend"
        playtime_part = (
            f", {r.playtime_hours}h playtime" if r.playtime_hours > 0 else ""
        )
        lines.append(
            f"### {i}. id={r.review_id} | {r.votes_helpful} helpful, "
            f"{r.votes_funny} funny ({verdict}{playtime_part})"
        )
        lines.append("")
        body_lines = r.body.splitlines() or [r.body]
        for bl in body_lines:
            lines.append(f"> {bl}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reddit Drafter v2: turn a Phase 3 GameReport into a Reddit-ready markdown skeleton."
    )
    parser.add_argument(
        "--appid",
        type=int,
        required=True,
        help="Steam appid whose Phase 3 report drives the draft.",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Skip rendering and print the parsed SourceBundle JSON.",
    )
    args = parser.parse_args()

    generated_at = datetime.now(UTC)
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")

    conn = open_readonly_conn()
    try:
        bundle = load_source_bundle(conn, args.appid)
    finally:
        conn.close()

    if args.data_only:
        print(bundle.model_dump_json(indent=2))
        return

    data = RedditDrafterData(
        generated_at=generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source=bundle,
        titles=_pick_titles(bundle),
        tldr=_build_tldr(bundle),
        findings=_pick_findings(bundle),
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data_path = REPORTS_DIR / f"{args.appid}_{timestamp}_data.json"
    data_path.write_text(data.model_dump_json(indent=2) + "\n")

    md = render_markdown(data)
    md_path = REPORTS_DIR / f"{args.appid}_{timestamp}.md"
    md_path.write_text(md)

    print(md)
    print(f"\nWrote report to {md_path}")
    print(f"Wrote data to   {data_path}")


if __name__ == "__main__":
    main()
