"""Reddit Drafter v1: turn a Phase 3 GameReport into a Reddit-ready draft."""

from __future__ import annotations

import argparse
import json
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

REPORTS_DIR = Path("reports/reddit_drafts")
MODEL = "claude-opus-4-7"
MAX_TOKENS = 6144
BATCH_POLL_SECONDS = 30
CUSTOM_ID = "reddit_drafter_v1"

EXIT_BAD_ENV = 2
EXIT_NO_REPORT = 3
EXIT_BATCH_TERMINAL = 5
EXIT_BATCH_FAILED = 6
EXIT_BATCH_NO_TEXT = 7
EXIT_BATCH_NO_RESULT = 8
EXIT_BATCH_PARSE = 9


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


class SubredditRecommendation(BaseModel):
    name: str
    confidence: str
    rationale: str
    body_tweaks: str


class RedditDraft(BaseModel):
    candidate_titles: list[str]
    recommended_subreddits: list[SubredditRecommendation]
    chosen_audience: str
    post_body: str
    tldr: str
    self_edit_checklist: list[str]


class RedditDrafterData(BaseModel):
    generated_at: str
    source: SourceBundle
    target_subreddit: str
    requested_audience: str
    draft: RedditDraft


SYSTEM_PROMPT = """\
You are a Reddit-savvy indie game analyst writing a draft post grounded
in one Phase 3 GameReport. The operator will hand-edit before posting,
so prioritize structure, evidence, and substance over voice perfection.

<inputs>
A single SourceBundle JSON document containing:
- appid, game_name: the target game
- total_reviews_analyzed: the headline number; use the EXACT integer in
  titles, never round
- review_date_range_start, review_date_range_end: temporal hook for
  longevity or recency angles
- pipeline_version, report_created_at: metadata only
- review_count_total: Steam's all-language total (for context)
- positive_pct: Steam's positive percentage (for context)
- genres: list of Steam genre slugs (for subreddit suggestions)
- report_json: the full Phase 3 GameReport. Quote verbatim from
  design_strengths, gameplay_friction, churn_triggers, dev_priorities,
  audience_profile, store_page_alignment, content_depth,
  competitive_context, hidden_strengths

Two trailing lines in the user message:
- Target subreddit: a canonical name like "r/gamedev", or "none
  specified" meaning recommend 1-3
- Requested audience: "devs" or "players", or "let the model pick"
</inputs>

<goal>
Produce a Reddit post draft modeled on the "I analyzed [N] reviews of
[Game] and here's what I found" format. Optimize for upvotes from
craft-focused indie devs OR thoughtful players depending on
chosen_audience. Three title candidates, ranked. 1-3 subreddit
recommendations with body-tweak notes (or, if target_subreddit is set,
return exactly that one entry, confidence "high", body_tweaks empty).
</goal>

<grounding_rules>
- Every numeric claim cites a field from report_json. No invented
  stats. Use total_reviews_analyzed exactly, never round.
- Pick the most counterintuitive finding for the title. Strong
  candidates: a store_page_alignment.promises_broken item that
  contradicts marketing, a hidden_strengths item the store page
  underplays, a churn trigger with a specific time window, a
  dev_priority with a high mention count, longevity if
  review_date_range_start is more than 5 years ago.
- Include up to 3 positive findings drawn from design_strengths,
  hidden_strengths, audience_profile praise drivers, or
  store_page_alignment.hidden_strengths. Mix them with friction or
  churn findings; do not stack all positives or all negatives.
- When dev_priorities[i].why_it_matters contains mention counts like
  "28+ explicit mentions", quote them in the body. Mention counts are
  credibility multipliers. Use at least two when available.
- Quote churn_triggers as specific behaviors with their time window or
  trigger condition (e.g. "players expecting RPG progression drop out
  within 3-9 hours"), not as paraphrase.
- If chosen_audience is "devs": frame findings as design and marketing
  lessons. Pull from dev_priorities, churn_triggers,
  store_page_alignment, competitive_context. Body 600-900 words.
- If chosen_audience is "players": frame as whether to buy, what to
  expect, who it's for. Pull from audience_profile, design_strengths,
  content_depth, store_page_alignment.hidden_strengths, playtime
  correlation if present. Body 400-700 words.
- If target_subreddit is set, override chosen_audience accordingly:
  r/gamedev, r/IndieDev, r/SoloDevelopment -> devs.
  r/patient_gamers, r/Steam, r/pcgaming -> players. Genre subs
  (r/towerdefense, r/roguelikedev, etc.) -> players by default
  unless the source data is exceptionally design-focused.
- Limitations paragraph mandatory. Use these honest limits for Phase 3
  reports: English-language reviews only, post-launch only (no
  pre-release wishlist signal), Steam-only (no console/Epic/GOG),
  self-selected reviewers (Steam reviewers skew positive vs silent
  majority), total_reviews_analyzed is a cap (large games sample 2000
  of many more). Pick 2-3 that fit; do not list all of them.
- Soft CTA only. Accepted forms: "happy to run this on your game,
  drop the appid", "DM me if you want the methodology". Forbidden:
  "check out my SaaS", "sign up at", any link to steam-pulse.org or
  any domain.
- First-person. "I" not "we". One mention of "a small tool I built"
  allowed, late, in passing. The post is about the findings, not the
  tool.
- Mild self-deprecation when honest. "I expected X but the data said
  Y" works when supported by the report.
- Do not use em-dashes (the long horizontal dash, U+2014). Use commas,
  colons, parentheses, or short sentences instead. Hard rule, applies
  to titles and body.
- Banned words and phrases (anti-AI tells): "delve", "tapestry",
  "navigate the landscape", "in today's rapidly evolving", "crucial"
  (as adjective), "leverage" (as verb), "myriad", "robust", "seamless".
- Reddit markdown only: **bold**, *italic*, "1." ordered lists, "*"
  unordered, ">" block quotes, code via 4-space indent. No tables.
  No HTML.
- Skip r/IndieDev as a recommendation when the game is clearly not
  indie (heuristic: a AAA studio shows up in
  report_json.competitive_context, or review_count_total is very
  large).
</grounding_rules>

<output_rubric>
You return ONE JSON object matching the RedditDraft schema below.
No code fences, no preamble, no trailing prose. JSON only.

{
  "candidate_titles": [string, string, string],
  "recommended_subreddits": [
    {
      "name": "r/...",
      "confidence": "high" | "medium" | "low",
      "rationale": "1-2 sentences",
      "body_tweaks": "how to adjust the draft for this sub, or empty"
    }
  ],
  "chosen_audience": "devs" | "players",
  "post_body": "Reddit-flavored markdown",
  "tldr": "2-3 sentences",
  "self_edit_checklist": [string, string, string, string, string]
}

Section requirements:
- candidate_titles: exactly 3, ranked. Each title 60-110 characters.
  Title #1 has the sharpest specific number plus game name plus a
  counterintuitive claim. Titles 2 and 3 vary the angle (one drier or
  methodological, one bolder or contrarian) so the operator has real
  choices.
- recommended_subreddits: 1-3 entries. Each names the sub, confidence,
  rationale (1-2 sentences), body_tweaks (what to change for that sub).
  If target_subreddit is set, return exactly one entry, confidence
  "high", body_tweaks empty.
- chosen_audience: a single word, "devs" or "players". Echoes
  requested_audience if set, otherwise picks based on report strengths.
- post_body: structure, in order:
  1. Hook: 1-2 sentences leading with total_reviews_analyzed and the
     surprise.
  2. Methodology: 1-2 casual sentences; mention the review-date range
     if it strengthens the angle.
  3. 3-5 numbered findings. Each: bold claim, evidence with cited
     stat or mention count, what-it-means line.
  4. Limitations: 1 paragraph with 2-3 honest limits from the list
     in grounding_rules.
  5. Soft CTA: 1 line, per grounding_rules.
  Do NOT include the title (separate field). Do NOT include the TLDR
  (separate field; the operator pastes it). Word band depends on
  chosen_audience (see grounding_rules).
- tldr: 2-3 sentences. Distilled. Operator pastes at top or bottom;
  you do not position it.
- self_edit_checklist: 5-7 items. Each is a concrete edit. Required
  items: confirm appid and game name accuracy; add one personal
  sentence only the operator could write (why they ran this, current
  project, a confession); read limitations aloud for tone; verify
  subreddit self-promo rules; double-check any quoted mention counts
  against the source. Other 1-2 items are draft-specific.
</output_rubric>

<style>
- Indie-dev-to-indie-devs (or thoughtful-player-to-thoughtful-players)
  voice. Blunt. Lightly self-deprecating when honest. No marketing
  adjectives. No corporate voice.
- Use real numbers, real game names, real tag names from the source.
  No placeholders.
- The operator hand-edits, so prioritize structure and substance over
  voice perfection.
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


def load_source_bundle(
    conn: psycopg2.extensions.connection, appid: int
) -> SourceBundle:
    """Pull the GameReport row plus the joined games metadata."""
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
    )


def build_user_message(
    bundle: SourceBundle, target_subreddit: str, requested_audience: str
) -> str:
    """Compose the user message: bundle JSON, target sub line, audience line, kicker."""
    sub_line = target_subreddit if target_subreddit else "none specified"
    audience_line = requested_audience if requested_audience else "let the model pick"
    return (
        f"{bundle.model_dump_json(indent=2)}\n\n"
        f"Target subreddit: {sub_line}.\n"
        f"Requested audience: {audience_line}.\n\n"
        f"Produce the draft."
    )


def _strip_code_fences(text: str) -> str:
    """If the LLM wrapped the JSON in a fenced block, strip the fences."""
    s = text.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[: -len("```")]
    return s.strip()


def submit_batch_and_wait(api_key: str, user_text: str) -> RedditDraft:
    """Submit one batch request and parse the JSON result into a RedditDraft."""
    client = anthropic.Anthropic(api_key=api_key)
    requests = [
        {
            "custom_id": CUSTOM_ID,
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
            sys.exit(EXIT_BATCH_TERMINAL)

    text = ""
    for entry in client.messages.batches.results(batch_id):
        if entry.custom_id != CUSTOM_ID:
            continue
        if entry.result.type != "succeeded":
            print(f"ERROR: batch result type was {entry.result.type}", file=sys.stderr)
            sys.exit(EXIT_BATCH_FAILED)
        for block in entry.result.message.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break
        if not text:
            print("ERROR: no text content in batch result", file=sys.stderr)
            sys.exit(EXIT_BATCH_NO_TEXT)
        break
    else:
        print(f"ERROR: batch result for custom_id {CUSTOM_ID} not found", file=sys.stderr)
        sys.exit(EXIT_BATCH_NO_RESULT)

    cleaned = _strip_code_fences(text)
    try:
        return RedditDraft.model_validate_json(cleaned)
    except Exception as exc:
        print(
            f"ERROR: failed to parse RedditDraft JSON from LLM: {exc}\n"
            f"--- raw response (first 800 chars) ---\n{cleaned[:800]}",
            file=sys.stderr,
        )
        sys.exit(EXIT_BATCH_PARSE)


def render_markdown(data: RedditDrafterData) -> str:
    """Render a human-friendly markdown view of the draft."""
    src = data.source
    draft = data.draft
    lines: list[str] = []

    lines.append(f"# Reddit Draft: {src.game_name} (appid {src.appid})")
    lines.append("")
    lines.append(f"- Generated at: {data.generated_at}")
    lines.append(
        f"- Source report: pipeline_version={src.pipeline_version}, "
        f"created_at={src.report_created_at}"
    )
    lines.append(
        f"- Reviews analyzed: {src.total_reviews_analyzed} "
        f"(Steam total all languages: {src.review_count_total}, "
        f"positive {src.positive_pct}%)"
    )
    lines.append(
        f"- Review date range: {src.review_date_range_start} to "
        f"{src.review_date_range_end}"
    )
    lines.append(
        f"- Target subreddit: {data.target_subreddit or '(model recommends)'}"
    )
    lines.append(
        f"- Requested audience: {data.requested_audience or '(model picks)'}"
    )
    lines.append(f"- Chosen audience: {draft.chosen_audience}")
    lines.append("")

    lines.append("## Candidate titles")
    lines.append("")
    for i, t in enumerate(draft.candidate_titles, 1):
        lines.append(f"{i}. {t}")
    lines.append("")

    lines.append("## Recommended subreddits")
    lines.append("")
    for s in draft.recommended_subreddits:
        lines.append(f"- **{s.name}** (confidence: {s.confidence})")
        lines.append(f"  - Rationale: {s.rationale}")
        if s.body_tweaks:
            lines.append(f"  - Body tweaks: {s.body_tweaks}")
    lines.append("")

    lines.append("## Post body")
    lines.append("")
    lines.append(draft.post_body.rstrip())
    lines.append("")

    lines.append("## TLDR")
    lines.append("")
    lines.append(draft.tldr.rstrip())
    lines.append("")

    lines.append("## Self-edit checklist")
    lines.append("")
    for item in draft.self_edit_checklist:
        lines.append(f"- [ ] {item}")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reddit Drafter v1: turn a Phase 3 GameReport into a Reddit-ready draft."
    )
    parser.add_argument(
        "--appid",
        type=int,
        required=True,
        help="Steam appid whose Phase 3 report drives the draft.",
    )
    parser.add_argument(
        "--subreddit",
        type=str,
        default="",
        help="Canonical subreddit name (e.g. r/gamedev). Empty -> model recommends.",
    )
    parser.add_argument(
        "--audience",
        type=str,
        default="",
        choices=["", "devs", "players"],
        help="Force the audience framing. Empty -> model picks.",
    )
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Skip the LLM call and print the parsed SourceBundle.",
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

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ERROR: ANTHROPIC_API_KEY not set (use --data-only to skip the LLM call).",
            file=sys.stderr,
        )
        sys.exit(EXIT_BAD_ENV)

    user_text = build_user_message(bundle, args.subreddit, args.audience)
    draft = submit_batch_and_wait(api_key, user_text)

    data = RedditDrafterData(
        generated_at=generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source=bundle,
        target_subreddit=args.subreddit,
        requested_audience=args.audience,
        draft=draft,
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
