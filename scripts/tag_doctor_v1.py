"""Tag Doctor v1: audit one game's tag strategy against high-performing peers."""

from __future__ import annotations

import argparse
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

REPORTS_DIR = Path("reports/tag_doctor")
MODEL = "claude-opus-4-7"
GENERIC_THRESHOLD_PCT = 40.0
PEER_REVIEW_FLOOR = 500
PEER_POSITIVE_FLOOR = 75
DEV_TAG_LIMIT = 20
PEER_TOP_N = 10
PEER_OVERLAP_TOP_N = 20
MIN_SHARED_TOP_TAGS = 2
PEER_TAG_RICHNESS_FLOOR = 10
ELIGIBLE_REVIEW_FLOOR = 100
BATCH_POLL_SECONDS = 30
MAX_TOKENS = 4096


class TagWithVotes(BaseModel):
    name: str
    votes: int


class PeerSummary(BaseModel):
    appid: int
    name: str
    review_count: int
    positive_pct: int
    overlap_score: float
    shared_top_tag_count: int
    top_tags: list[TagWithVotes]


class PeerAdoption(BaseModel):
    tag_name: str
    peers_with_tag_in_top10: int
    peers_total: int
    adoption_pct: float
    avg_votes_among_peers: int


class GenericTagFlag(BaseModel):
    tag_name: str
    catalog_adoption_pct: float
    rank_in_dev_game: int


class DevGame(BaseModel):
    appid: int
    name: str
    slug: str
    review_count: int
    positive_pct: int
    release_date: str | None


class TagDoctorData(BaseModel):
    appid: int
    name: str
    review_count: int
    positive_pct: int
    dev_top_tags: list[TagWithVotes]
    peers: list[PeerSummary]
    missing_from_dev: list[PeerAdoption]
    generic_in_top5: list[GenericTagFlag]


SYSTEM_PROMPT = """You are a senior Steam tag strategist. You have one game's tag data plus
peer comparison data, all derived from the live Steam catalog.

Produce a tag wizard plan in markdown. Rules:

1. Lead with a one-paragraph verdict. State plainly whether the tag
   strategy is fine, has minor improvements, or is a significant drag
   on discovery.
2. Recommend at most 5 tag changes for this month, ordered by impact:
   add, drop, or reposition. Each must cite the data row that supports
   it (e.g. "12/15 peers carry Roguelite in their top 10").
3. If a recommendation is purely defensive (drop a generic), say so.
   If it is opportunistic (add a peer-popular niche tag), say so.
4. Do not invent tags that are not present in either the dev's tag
   list or the peers' tag lists.
5. Be blunt. No throat-clearing. No filler.
6. Close with one sentence on cadence: re-run Tag Doctor monthly."""


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


def fetch_dev_game(conn: psycopg2.extensions.connection, appid: int) -> DevGame:
    """Pull the dev's game row from games."""
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
    return DevGame(
        appid=int(row["appid"]),
        name=row["name"],
        slug=row["slug"],
        review_count=int(row["review_count"] or 0),
        positive_pct=int(row["positive_pct"] or 0),
        release_date=rd.isoformat() if rd else None,
    )


def fetch_dev_tags(conn: psycopg2.extensions.connection, appid: int) -> list[TagWithVotes]:
    """Pull the dev's top 20 tags by votes."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT t.name, gt.votes FROM game_tags gt "
            "JOIN tags t ON t.id = gt.tag_id "
            "WHERE gt.appid = %s "
            "ORDER BY gt.votes DESC, t.name ASC "
            "LIMIT %s",
            (appid, DEV_TAG_LIMIT),
        )
        rows = cur.fetchall()
    if not rows:
        print(
            f"ERROR: no tags found for appid {appid}. "
            "Check the SteamSpy/Steam-store-page tag ingestion path "
            "(see steam-pulse.org backlog: tag pipelines).",
            file=sys.stderr,
        )
        sys.exit(4)
    return [TagWithVotes(name=r["name"], votes=int(r["votes"])) for r in rows]


def pick_peers(
    conn: psycopg2.extensions.connection, appid: int, peers: int
) -> list[dict[str, Any]]:
    """Pick peers by IDF-weighted cosine similarity over normalized top-20 tag profiles."""
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
                AND g.positive_pct >= %(positive_floor)s
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
            SELECT g.appid, g.name, g.slug, g.review_count, g.positive_pct,
                   SUM(pt.weight * dt.weight * dt.idf * dt.idf) AS overlap_score,
                   COUNT(*) AS shared_top_tag_count
            FROM peer_top pt
            JOIN dev_top dt ON dt.tag_id = pt.tag_id
            JOIN games g ON g.appid = pt.appid
            GROUP BY g.appid, g.name, g.slug, g.review_count, g.positive_pct
            HAVING COUNT(*) >= %(min_shared)s
            ORDER BY overlap_score DESC, g.appid ASC
            LIMIT %(peers)s
            """,
            {
                "appid": appid,
                "top_n": PEER_OVERLAP_TOP_N,
                "review_floor": PEER_REVIEW_FLOOR,
                "positive_floor": PEER_POSITIVE_FLOOR,
                "eligible_floor": ELIGIBLE_REVIEW_FLOOR,
                "richness_floor": PEER_TAG_RICHNESS_FLOOR,
                "min_shared": MIN_SHARED_TOP_TAGS,
                "peers": peers,
            },
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_peer_tags(
    conn: psycopg2.extensions.connection, peer_appids: list[int]
) -> dict[int, list[TagWithVotes]]:
    """Pull each peer's top 10 tags in one batched query."""
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


def fetch_generic_tag_rates(
    conn: psycopg2.extensions.connection, tag_names: list[str]
) -> dict[str, float]:
    """Compute catalog-wide adoption rate for each tag name."""
    if not tag_names:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH per_game_top10 AS (
              SELECT gt.appid, gt.tag_id,
                     ROW_NUMBER() OVER (
                       PARTITION BY gt.appid
                       ORDER BY gt.votes DESC
                     ) AS rnk
              FROM game_tags gt
              JOIN games g ON g.appid = gt.appid
              WHERE g.review_count >= %s
            )
            SELECT t.name,
                   COUNT(*) FILTER (WHERE pgt.rnk <= %s) AS games_with_in_top10,
                   (SELECT COUNT(*) FROM games WHERE review_count >= %s) AS eligible_total
            FROM per_game_top10 pgt
            JOIN tags t ON t.id = pgt.tag_id
            WHERE t.name = ANY(%s)
            GROUP BY t.name
            """,
            (ELIGIBLE_REVIEW_FLOOR, PEER_TOP_N, ELIGIBLE_REVIEW_FLOOR, tag_names),
        )
        rows = cur.fetchall()
    rates: dict[str, float] = {name: 0.0 for name in tag_names}
    for r in rows:
        eligible = int(r["eligible_total"] or 0)
        if eligible == 0:
            continue
        rates[r["name"]] = round((int(r["games_with_in_top10"]) / eligible) * 100.0, 2)
    return rates


def compute_diagnostics(
    dev_game: DevGame,
    dev_tags: list[TagWithVotes],
    peer_rows: list[dict[str, Any]],
    peer_tags_by_appid: dict[int, list[TagWithVotes]],
    generic_rates: dict[str, float],
) -> TagDoctorData:
    """Build the TagDoctorData diagnostic structure from raw inputs."""
    peer_summaries: list[PeerSummary] = []
    for r in peer_rows:
        ptags = peer_tags_by_appid.get(int(r["appid"]), [])
        peer_summaries.append(
            PeerSummary(
                appid=int(r["appid"]),
                name=r["name"],
                review_count=int(r["review_count"] or 0),
                positive_pct=int(r["positive_pct"] or 0),
                overlap_score=round(float(r["overlap_score"] or 0.0), 6),
                shared_top_tag_count=int(r.get("shared_top_tag_count") or 0),
                top_tags=ptags,
            )
        )

    dev_tag_names = {t.name for t in dev_tags}
    peers_total = len(peer_summaries)
    tag_votes_across_peers: dict[str, list[int]] = {}
    for p in peer_summaries:
        for t in p.top_tags:
            tag_votes_across_peers.setdefault(t.name, []).append(t.votes)

    missing: list[PeerAdoption] = []
    if peers_total > 0:
        for tag_name, votes_list in tag_votes_across_peers.items():
            if tag_name in dev_tag_names:
                continue
            peers_with = len(votes_list)
            adoption_pct = (peers_with / peers_total) * 100.0
            if adoption_pct < GENERIC_THRESHOLD_PCT:
                continue
            avg_votes = int(sum(votes_list) / len(votes_list))
            missing.append(
                PeerAdoption(
                    tag_name=tag_name,
                    peers_with_tag_in_top10=peers_with,
                    peers_total=peers_total,
                    adoption_pct=round(adoption_pct, 2),
                    avg_votes_among_peers=avg_votes,
                )
            )
    missing.sort(key=lambda m: (-m.adoption_pct, -m.avg_votes_among_peers, m.tag_name))
    missing = missing[:10]

    generic_flags: list[GenericTagFlag] = []
    for idx, t in enumerate(dev_tags[:5], start=1):
        rate = generic_rates.get(t.name, 0.0)
        if rate > GENERIC_THRESHOLD_PCT:
            generic_flags.append(
                GenericTagFlag(
                    tag_name=t.name,
                    catalog_adoption_pct=rate,
                    rank_in_dev_game=idx,
                )
            )

    return TagDoctorData(
        appid=dev_game.appid,
        name=dev_game.name,
        review_count=dev_game.review_count,
        positive_pct=dev_game.positive_pct,
        dev_top_tags=dev_tags,
        peers=peer_summaries,
        missing_from_dev=missing,
        generic_in_top5=generic_flags,
    )


def render_header(data: TagDoctorData, generated_at: datetime) -> str:
    """Render the report title and metadata block."""
    lines = [
        f"# Tag Doctor for {data.name} (appid {data.appid})",
        "",
        f"Generated {generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')} against prod",
        "",
        f"- Review count: {data.review_count}",
        f"- Positive %: {data.positive_pct}",
        "",
    ]
    return "\n".join(lines)


def render_data_sections(data: TagDoctorData) -> str:
    """Render the six data sections, deterministic given the same input."""
    lines: list[str] = []

    lines.append("## Your top tags")
    lines.append("")
    lines.append("| Rank | Tag | Votes |")
    lines.append("|---:|---|---:|")
    for i, t in enumerate(data.dev_top_tags, start=1):
        lines.append(f"| {i} | {t.name} | {t.votes} |")
    lines.append("")

    lines.append("## High-performing peers")
    lines.append("")
    lines.append("| Peer | Reviews | Positive % | Shared top tags | Similarity |")
    lines.append("|---|---:|---:|---:|---:|")
    for p in data.peers:
        lines.append(
            f"| {p.name} (appid {p.appid}) | {p.review_count} | {p.positive_pct} | "
            f"{p.shared_top_tag_count} | {p.overlap_score:.4f} |"
        )
    lines.append("")

    lines.append("## Tags peers ride that you don't")
    lines.append("")
    if not data.missing_from_dev:
        lines.append("_No peer-popular tags missing from your top 20._")
    else:
        lines.append("| Tag | Peer adoption | Avg votes (across peers carrying it) |")
        lines.append("|---|---:|---:|")
        for m in data.missing_from_dev:
            lines.append(
                f"| {m.tag_name} | {m.peers_with_tag_in_top10}/{m.peers_total} "
                f"({m.adoption_pct}%) | {m.avg_votes_among_peers} |"
            )
    lines.append("")

    lines.append("## Generic tags currently in your top 5")
    lines.append("")
    if not data.generic_in_top5:
        lines.append("_No generic tags flagged in your top 5._")
    else:
        lines.append("| Rank | Tag | Catalog adoption % |")
        lines.append("|---:|---|---:|")
        for g in data.generic_in_top5:
            lines.append(
                f"| {g.rank_in_dev_game} | {g.tag_name} | {g.catalog_adoption_pct}% |"
            )
    lines.append("")

    lines.append("## Peer-by-peer tag breakdown")
    lines.append("")
    for p in data.peers:
        summary = (
            f"{p.name} (appid {p.appid}): {p.review_count} reviews, "
            f"{p.positive_pct}% positive"
        )
        lines.append(f"<details><summary>{summary}</summary>")
        lines.append("")
        lines.append("| Tag | Votes |")
        lines.append("|---|---:|")
        for t in p.top_tags:
            lines.append(f"| {t.name} | {t.votes} |")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def submit_batch_and_wait(api_key: str, data: TagDoctorData) -> str:
    """Submit a single-request Anthropic batch and return the narrative markdown."""
    client = anthropic.Anthropic(api_key=api_key)
    payload = data.model_dump_json(indent=2)
    user_text = f"{payload}\n\nProduce the tag wizard plan."
    requests = [
        {
            "custom_id": "tag_doctor_v1",
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
        if entry.custom_id != "tag_doctor_v1":
            continue
        if entry.result.type != "succeeded":
            print(f"ERROR: batch result type was {entry.result.type}", file=sys.stderr)
            sys.exit(6)
        for block in entry.result.message.content:
            if getattr(block, "type", None) == "text":
                return block.text
        print("ERROR: no text content in batch result", file=sys.stderr)
        sys.exit(7)

    print("ERROR: batch result for custom_id tag_doctor_v1 not found", file=sys.stderr)
    sys.exit(8)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tag Doctor v1: audit a Steam game's tag strategy against high-performing peers."
    )
    parser.add_argument("--appid", type=int, required=True, help="Steam appid of the dev's game.")
    parser.add_argument("--peers", type=int, default=15, help="Peer set cap (default 15).")
    parser.add_argument(
        "--data-only",
        action="store_true",
        help="Skip the LLM narrative and emit the data report only.",
    )
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")

    conn = open_readonly_conn()
    try:
        dev_game = fetch_dev_game(conn, args.appid)
        dev_tags = fetch_dev_tags(conn, args.appid)
        peer_rows = pick_peers(conn, args.appid, args.peers)
        peer_appids = [int(r["appid"]) for r in peer_rows]
        peer_tags_by_appid = fetch_peer_tags(conn, peer_appids)
        dev_top10_names = [t.name for t in dev_tags[:PEER_TOP_N]]
        generic_rates = fetch_generic_tag_rates(conn, dev_top10_names)
    finally:
        conn.close()

    data = compute_diagnostics(
        dev_game, dev_tags, peer_rows, peer_tags_by_appid, generic_rates
    )

    data_path = REPORTS_DIR / f"{args.appid}_{timestamp}_data.json"
    data_path.write_text(data.model_dump_json(indent=2) + "\n")

    header = render_header(data, generated_at)
    data_sections = render_data_sections(data)

    if args.data_only:
        report = header + data_sections
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print(
                "ERROR: ANTHROPIC_API_KEY not set (use --data-only to skip the narrative).",
                file=sys.stderr,
            )
            sys.exit(2)
        narrative = submit_batch_and_wait(api_key, data).strip()
        verdict_block = f"## Verdict and Recommendations\n\n{narrative}\n\n"
        report = header + verdict_block + data_sections

    md_path = REPORTS_DIR / f"{args.appid}_{timestamp}.md"
    md_path.write_text(report)

    print(report)
    print(f"\nWrote report to {md_path}")
    print(f"Wrote data to   {data_path}")


if __name__ == "__main__":
    main()
