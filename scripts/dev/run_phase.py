#!/usr/bin/env python3
"""Run the three-phase analyzer locally, one phase at a time.

Drives the SAME `analyzer.run_chunk_phase` / `run_merge_phase` /
`run_synthesis_phase` helpers the Lambda uses — no shortcuts, no stubs.
Connects to local Postgres (via `DATABASE_URL`) and real Bedrock (via
your AWS credentials) and stops after the requested phase so you can
eyeball the persisted artifacts before paying for the next phase.

Prereqs:
  - Local Postgres up: `./scripts/dev/start-local.sh`
  - Test data imported: `scripts/dev/import_from_prod.py --appids <…>`
  - DATABASE_URL + PYTHONPATH exported (start-local.sh prints them)
  - AWS creds with Bedrock access in the default profile

Usage:
    # Phase 1 only — write chunk_summaries rows, print topic counts.
    poetry run python scripts/dev/run_phase.py --appid 2358720 --phase chunk

    # Phase 1 + 2 — also merge into merged_summaries, print merge tree.
    poetry run python scripts/dev/run_phase.py --appid 2358720 --phase merge

    # Full pipeline — also synthesize GameReport into reports.
    poetry run python scripts/dev/run_phase.py --appid 2358720 --phase synthesis

Each phase is idempotent. Re-running `--phase synthesis` after a previous
`--phase chunk` skips Phase 1 entirely via the chunk_hash cache. Bump
`CHUNK_PROMPT_VERSION` / `MERGE_PROMPT_VERSION` / `SYNTHESIS_PROMPT_VERSION`
in `analyzer.py` to invalidate.
"""

import argparse
import json
import sys
from pathlib import Path

# Load .env BEFORE any library import — analyzer.py builds
# SteamPulseConfig() at module-import time and will fail without the
# _PARAM_NAME fields populated.
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")
# Also expose library_layer + lambda_functions on sys.path so this
# script runs without the caller having to export PYTHONPATH.
sys.path.insert(0, str(_REPO_ROOT / "src" / "library-layer"))
sys.path.insert(0, str(_REPO_ROOT / "src" / "lambda-functions"))

from library_layer.analyzer import (  # noqa: E402
    CHUNK_PROMPT_VERSION,
    PIPELINE_VERSION,
    AnalyzerSettings,
    run_chunk_phase,
    run_merge_phase,
    run_synthesis_phase,
)
from library_layer.config import SteamPulseConfig  # noqa: E402
from library_layer.llm import make_converse_backend  # noqa: E402
from library_layer.models.analyzer_models import (  # noqa: E402
    MergedSummary,
    RichChunkSummary,
)
from library_layer.models.metadata import build_metadata_context  # noqa: E402
from library_layer.models.temporal import build_temporal_context  # noqa: E402
from library_layer.repositories.chunk_summary_repo import ChunkSummaryRepository  # noqa: E402
from library_layer.repositories.game_repo import GameRepository  # noqa: E402
from library_layer.repositories.merged_summary_repo import MergedSummaryRepository  # noqa: E402
from library_layer.repositories.report_repo import ReportRepository  # noqa: E402
from library_layer.repositories.review_repo import ReviewRepository  # noqa: E402
from library_layer.repositories.tag_repo import TagRepository  # noqa: E402
from library_layer.utils.chunking import dataset_reference_time  # noqa: E402
from library_layer.utils.db import get_conn  # noqa: E402

_PHASES = ("chunk", "merge", "synthesis")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--appid", type=int, required=True)
    p.add_argument(
        "--phase",
        choices=_PHASES,
        required=True,
        help="Stop after this phase. 'chunk' runs Phase 1 only, "
        "'merge' runs 1+2, 'synthesis' runs all three.",
    )
    p.add_argument(
        "--max-reviews",
        type=int,
        default=None,
        help="Override ANALYSIS_MAX_REVIEWS for this run (e.g. --max-reviews 200 for a quick smoke test).",
    )
    p.add_argument(
        "--dump-dir",
        type=Path,
        default=_REPO_ROOT / "tmp" / "phase_dumps",
        help="Directory to write org-mode dumps of the persisted phase data. "
        "Each run writes <dump-dir>/<appid>_<phase>.org (overwrite).",
    )
    p.add_argument(
        "--no-dump",
        action="store_true",
        help="Skip writing the org-mode phase dump.",
    )
    return p.parse_args()


def _load_reviews(review_repo: ReviewRepository, appid: int, limit: int) -> list[dict]:
    """Mirror the Lambda handler's review shaping — same filter, same fields."""
    db_reviews = review_repo.find_by_appid(appid, limit=limit)
    return [
        {
            "steam_review_id": r.steam_review_id,
            "voted_up": r.voted_up,
            "review_text": r.body,
            "playtime_hours": r.playtime_hours or 0,
            "votes_helpful": r.votes_helpful,
            "votes_funny": r.votes_funny,
            "posted_at": r.posted_at.isoformat() if r.posted_at else None,
            "written_during_early_access": r.written_during_early_access,
            "received_for_free": r.received_for_free,
        }
        for r in db_reviews
        if r.body
    ]


def _print_chunk_summary(summaries: list) -> None:
    total_topics = sum(len(s.topics) for s in summaries)
    per_cat: dict[str, int] = {}
    for s in summaries:
        for t in s.topics:
            per_cat[t.category] = per_cat.get(t.category, 0) + 1
    print(f"\n✔ Phase 1 complete — {len(summaries)} chunk(s), {total_topics} topic(s)")
    for cat, n in sorted(per_cat.items(), key=lambda kv: -kv[1]):
        print(f"    {cat:25s} {n}")


def _print_merge_summary(merged: object, merge_id: int | None) -> None:
    topics = getattr(merged, "topics", [])
    print(
        f"\n✔ Phase 2 complete — merged_summary id={merge_id}, "
        f"merge_level={merged.merge_level}, chunks_merged={merged.chunks_merged}, "
        f"topics={len(topics)}"
    )
    for t in topics[:15]:
        print(
            f"    [{t.category:20s}] {t.topic!r:40s} "
            f"x{t.mention_count:<4d} ({t.sentiment}, {t.confidence})"
        )
    if len(topics) > 15:
        print(f"    ... {len(topics) - 15} more")


def _print_report(report: object) -> None:
    print("\n✔ Phase 3 complete — GameReport")
    print(f"    one_liner: {report.one_liner}")
    print(f"    sentiment_trend: {report.sentiment_trend} ({report.sentiment_trend_note})")
    print(f"    hidden_gem_score: {report.hidden_gem_score}")
    print(f"    design_strengths: {len(report.design_strengths)}")
    print(f"    gameplay_friction: {len(report.gameplay_friction)}")
    print(f"    dev_priorities: {len(report.dev_priorities)}")
    if report.store_page_alignment is not None:
        print(f"    store_page_alignment.audience_match: {report.store_page_alignment.audience_match}")


# ---------------------------------------------------------------------------
# Org-mode dumpers
#
# After each phase runs, read the persisted rows back from the DB (not the
# in-memory objects) so the dump reflects exactly what landed on disk. Org
# format keeps it diff-friendly in the repo and instantly navigable in Emacs.
# ---------------------------------------------------------------------------


def _org_escape(s: str | None) -> str:
    """Keep table cells single-line and pipe-free."""
    if s is None:
        return ""
    return str(s).replace("|", "/").replace("\n", " ⏎ ").strip()


def _truncate(s: str | None, n: int) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _dump_chunk_phase(
    path: Path,
    *,
    appid: int,
    game_name: str,
    chunk_repo: ChunkSummaryRepository,
) -> None:
    rows = chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)
    rows.sort(key=lambda r: r.get("chunk_index", 0))
    lines: list[str] = [
        f"#+TITLE: Phase 1 (chunk) dump — {game_name} ({appid})",
        f"#+PIPELINE: {PIPELINE_VERSION}",
        f"#+CHUNK_PROMPT_VERSION: {CHUNK_PROMPT_VERSION}",
        f"#+CHUNKS: {len(rows)}",
        "",
    ]
    for row in rows:
        summary = RichChunkSummary.model_validate(row["summary_json"])
        idx = row.get("chunk_index")
        lines += [
            f"* Chunk {idx} (row id {row['id']})",
            f"  - chunk_hash :: ={row.get('chunk_hash')}=",
            f"  - chunk_size :: {row.get('chunk_size')}",
            f"  - model_id   :: {row.get('model_id')}",
            f"  - stats      :: +{summary.batch_stats.positive_count} "
            f"-{summary.batch_stats.negative_count} "
            f"avg_playtime={summary.batch_stats.avg_playtime_hours}h "
            f"high_playtime={summary.batch_stats.high_playtime_count} "
            f"EA={summary.batch_stats.early_access_count} "
            f"free={summary.batch_stats.free_key_count}",
            "",
            "** Topics",
            "",
            "   | # | category | topic | sentiment | conf | mentions | summary |",
            "   |---+----------+-------+-----------+------+----------+---------|",
        ]
        for i, t in enumerate(summary.topics, 1):
            lines.append(
                f"   | {i} | {_org_escape(t.category)} | {_org_escape(t.topic)} "
                f"| {t.sentiment} | {t.confidence} | {t.mention_count} "
                f"| {_org_escape(_truncate(t.summary, 120))} |"
            )
        lines.append("")
        if summary.competitor_refs:
            lines += ["** Competitor refs", ""]
            for c in summary.competitor_refs:
                lines.append(
                    f"   - *{_org_escape(c.game)}* ({c.sentiment}) — "
                    f"{_org_escape(_truncate(c.context, 200))}"
                )
            lines.append("")
        if summary.notable_quotes:
            lines += ["** Notable quotes", ""]
            for q in summary.notable_quotes:
                lines.append(
                    f"   - [[steam:{q.steam_review_id}]] "
                    f"({'+' if q.voted_up else '-'}, "
                    f"{q.playtime_hours}h, {q.votes_helpful} helpful): "
                    f"{_org_escape(_truncate(q.text, 200))}"
                )
            lines.append("")
    path.write_text("\n".join(lines) + "\n")


def _dump_merge_phase(
    path: Path,
    *,
    appid: int,
    game_name: str,
    merge_repo: MergedSummaryRepository,
    root_merge_id: int,
) -> None:
    root = merge_repo.find_by_id(root_merge_id)
    if root is None:
        raise RuntimeError(f"merge phase dump: root id={root_merge_id} not found")
    merged = MergedSummary.model_validate(root["summary_json"])
    stats = merged.total_stats
    lines: list[str] = [
        f"#+TITLE: Phase 2 (merge) dump — {game_name} ({appid})",
        f"#+PIPELINE: {PIPELINE_VERSION}",
        f"#+ROOT_MERGE_ID: {root_merge_id}",
        f"#+MERGE_LEVEL: {merged.merge_level}",
        f"#+CHUNKS_MERGED: {merged.chunks_merged}",
        f"#+SOURCE_CHUNK_IDS: {merged.source_chunk_ids}",
        f"#+MODEL_ID: {root.get('model_id')}",
        "",
        "* Total stats",
        "",
        f"  - positive :: {stats.positive_count}",
        f"  - negative :: {stats.negative_count}",
        f"  - avg_playtime_hours :: {stats.avg_playtime_hours}",
        f"  - high_playtime_count :: {stats.high_playtime_count}",
        f"  - early_access_count :: {stats.early_access_count}",
        f"  - free_key_count :: {stats.free_key_count}",
        f"  - date_range :: {stats.date_range_start} → {stats.date_range_end}",
        "",
        f"* Merged Topics ({len(merged.topics)})",
        "",
        "  | # | category | topic | sentiment | conf | mentions | avg_play | summary |",
        "  |---+----------+-------+-----------+------+----------+----------+---------|",
    ]
    for i, t in enumerate(merged.topics, 1):
        lines.append(
            f"  | {i} | {_org_escape(t.category)} | {_org_escape(t.topic)} "
            f"| {t.sentiment} | {t.confidence} | {t.mention_count} "
            f"| {t.avg_playtime_hours} | {_org_escape(_truncate(t.summary, 140))} |"
        )
    lines.append("")

    if merged.topics:
        lines += ["* Topic quotes", ""]
        for t in merged.topics:
            if not t.quotes:
                continue
            lines.append(f"** {_org_escape(t.topic)} [{t.category}]")
            for q in t.quotes:
                lines.append(
                    f"   - [[steam:{q.steam_review_id}]] "
                    f"({'+' if q.voted_up else '-'}, "
                    f"{q.playtime_hours}h, {q.votes_helpful} helpful): "
                    f"{_org_escape(_truncate(q.text, 240))}"
                )
            lines.append("")

    if merged.competitor_refs:
        lines += ["* Competitor refs", ""]
        for c in merged.competitor_refs:
            lines.append(
                f"  - *{_org_escape(c.game)}* ({c.sentiment}) — "
                f"{_org_escape(_truncate(c.context, 240))}"
            )
        lines.append("")

    if merged.notable_quotes:
        lines += ["* Notable quotes", ""]
        for q in merged.notable_quotes:
            lines.append(
                f"  - [[steam:{q.steam_review_id}]] "
                f"({'+' if q.voted_up else '-'}, "
                f"{q.playtime_hours}h, {q.votes_helpful} helpful): "
                f"{_org_escape(_truncate(q.text, 240))}"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


def _dump_synthesis_phase(
    path: Path,
    *,
    appid: int,
    game_name: str,
) -> None:
    # Read the row directly — the Report pydantic model doesn't expose
    # the pipeline bookkeeping columns (pipeline_version, chunk_count,
    # merged_summary_id) but we want them in the dump header.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT report_json, reviews_analyzed, pipeline_version,
                   chunk_count, merged_summary_id, last_analyzed
            FROM reports WHERE appid = %s
            """,
            (appid,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"synthesis phase dump: no report for appid={appid}")
    if isinstance(row, dict):
        (
            report_json, reviews_analyzed, pipeline_version,
            chunk_count, merged_summary_id, last_analyzed,
        ) = (
            row["report_json"], row["reviews_analyzed"], row["pipeline_version"],
            row["chunk_count"], row["merged_summary_id"], row["last_analyzed"],
        )
    else:
        (
            report_json, reviews_analyzed, pipeline_version,
            chunk_count, merged_summary_id, last_analyzed,
        ) = row
    r = report_json
    lines: list[str] = [
        f"#+TITLE: Phase 3 (synthesis) dump — {game_name} ({appid})",
        f"#+PIPELINE: {pipeline_version}",
        f"#+REVIEWS_ANALYZED: {reviews_analyzed}",
        f"#+CHUNK_COUNT: {chunk_count}",
        f"#+MERGED_SUMMARY_ID: {merged_summary_id}",
        f"#+LAST_ANALYZED: {last_analyzed}",
        "",
        "* One-liner",
        "",
        f"  {r.get('one_liner', '')}",
        "",
        "* Scores",
        "",
        f"  - hidden_gem_score :: {r.get('hidden_gem_score')}",
        f"  - sentiment_trend :: {r.get('sentiment_trend')} "
        f"({r.get('sentiment_trend_note')})",
        f"  - sentiment_trend_reliable :: {r.get('sentiment_trend_reliable')}",
        f"  - sentiment_trend_sample_size :: {r.get('sentiment_trend_sample_size')}",
        f"  - total_reviews_analyzed :: {r.get('total_reviews_analyzed')}",
        "",
    ]

    ap = r.get("audience_profile") or {}
    lines += [
        "* Audience profile",
        "",
        f"  - ideal_player :: {_org_escape(ap.get('ideal_player'))}",
        f"  - casual_friendliness :: {ap.get('casual_friendliness')}",
        f"  - archetypes :: {ap.get('archetypes')}",
        f"  - not_for :: {ap.get('not_for')}",
        "",
    ]

    def _list_section(title: str, key: str) -> list[str]:
        items = r.get(key) or []
        out = [f"* {title} ({len(items)})", ""]
        for i, item in enumerate(items, 1):
            out.append(f"  {i}. {_org_escape(_truncate(str(item), 400))}")
        out.append("")
        return out

    lines += _list_section("Design strengths", "design_strengths")
    lines += _list_section("Gameplay friction", "gameplay_friction")
    lines += _list_section("Player wishlist", "player_wishlist")
    lines += _list_section("Churn triggers", "churn_triggers")
    lines += _list_section("Technical issues", "technical_issues")

    dp = r.get("dev_priorities") or []
    lines += [f"* Dev priorities ({len(dp)})", ""]
    lines += [
        "  | # | action | why_it_matters | frequency | effort |",
        "  |---+--------+----------------+-----------+--------|",
    ]
    for i, item in enumerate(dp, 1):
        lines.append(
            f"  | {i} | {_org_escape(_truncate(item.get('action'), 80))} "
            f"| {_org_escape(_truncate(item.get('why_it_matters'), 100))} "
            f"| {_org_escape(item.get('frequency'))} "
            f"| {item.get('effort')} |"
        )
    lines.append("")

    cc = r.get("competitive_context") or []
    lines += [f"* Competitive context ({len(cc)})", ""]
    for item in cc:
        lines.append(
            f"  - *{_org_escape(item.get('game'))}* "
            f"({item.get('comparison_sentiment')}): "
            f"{_org_escape(_truncate(item.get('note'), 200))}"
        )
    lines.append("")

    lines += [
        "* Genre context",
        "",
        f"  {_org_escape(r.get('genre_context'))}",
        "",
    ]

    for section_key, title in (
        ("refund_signals", "Refund signals"),
        ("community_health", "Community health"),
        ("monetization_sentiment", "Monetization sentiment"),
        ("content_depth", "Content depth"),
    ):
        obj = r.get(section_key) or {}
        lines.append(f"* {title}")
        lines.append("")
        for k, v in obj.items():
            lines.append(f"  - {k} :: {_org_escape(_truncate(str(v), 240))}")
        lines.append("")

    spa = r.get("store_page_alignment")
    if spa is not None:
        lines += [
            "* Store page alignment",
            "",
            f"  - audience_match :: {spa.get('audience_match')}",
            f"  - audience_match_note :: {_org_escape(spa.get('audience_match_note'))}",
            "",
            "** Promises delivered",
            "",
        ]
        for p in spa.get("promises_delivered") or []:
            lines.append(f"   - {_org_escape(_truncate(p, 240))}")
        lines += ["", "** Promises broken", ""]
        for p in spa.get("promises_broken") or []:
            lines.append(f"   - {_org_escape(_truncate(p, 240))}")
        lines += ["", "** Hidden strengths", ""]
        for p in spa.get("hidden_strengths") or []:
            lines.append(f"   - {_org_escape(_truncate(p, 240))}")
        lines.append("")

    lines += [
        "* Full GameReport JSON",
        "",
        "#+BEGIN_SRC json",
        json.dumps(r, indent=2, default=str),
        "#+END_SRC",
        "",
    ]
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    args = _parse_args()
    appid = args.appid
    stop_after = args.phase

    config = SteamPulseConfig()
    settings = AnalyzerSettings.from_config(config)
    max_reviews = args.max_reviews or config.ANALYSIS_MAX_REVIEWS

    game_repo = GameRepository(get_conn)
    review_repo = ReviewRepository(get_conn)
    chunk_repo = ChunkSummaryRepository(get_conn)
    merge_repo = MergedSummaryRepository(get_conn)
    report_repo = ReportRepository(get_conn)
    tag_repo = TagRepository(get_conn)

    game = game_repo.find_by_appid(appid)
    if game is None:
        print(f"ERROR: appid={appid} not in local games table — run import_from_prod.py first")
        sys.exit(1)

    print(f"▶ Loading up to {max_reviews} reviews for {game.name} (appid={appid})...")
    reviews = _load_reviews(review_repo, appid, max_reviews)
    if not reviews:
        print(f"ERROR: no non-empty reviews for appid={appid}")
        sys.exit(1)
    print(f"  Loaded {len(reviews)} review(s) with non-empty bodies.")

    # Bedrock's instructor retry path had a bug (round-tripping tool_use
    # with caller=None). The direct Anthropic API doesn't have this issue,
    # so retries are safe there. Haiku in particular needs retries —
    # it occasionally misspells enum values that instructor can self-correct.
    retries = config.ANALYSIS_CONVERSE_MAX_RETRIES if config.LLM_BACKEND == "anthropic" else 0
    backend = make_converse_backend(
        config,
        max_workers=config.ANALYSIS_CONVERSE_MAX_WORKERS,
        max_retries=retries,
    )
    reference_time = dataset_reference_time(reviews)

    # -------- Phase 1: chunk --------
    print("\n▶ Phase 1: chunking + topic extraction...")
    chunk_summaries, chunk_ids = run_chunk_phase(
        appid=appid,
        game_name=game.name,
        reviews=reviews,
        backend=backend,
        chunk_repo=chunk_repo,
        chunk_size=settings.chunk_size,
        reference_time=reference_time,
        shuffle_seed=settings.shuffle_seed,
        chunk_max_tokens=settings.chunk_max_tokens,
        chunk_temperature=settings.chunk_temperature,
    )
    _print_chunk_summary(chunk_summaries)
    print(f"    chunk_summary row ids: {chunk_ids}")
    if not args.no_dump:
        args.dump_dir.mkdir(parents=True, exist_ok=True)
        chunk_model = config.model_for("chunking").replace(".", "-").replace("claude-", "")
        chunk_dump = args.dump_dir / f"{appid}_{game.slug}_{chunk_model}_chunk.org"
        _dump_chunk_phase(
            chunk_dump,
            appid=appid,
            game_name=game.name,
            chunk_repo=chunk_repo,
        )
        print(f"    org dump: {chunk_dump}")
    if stop_after == "chunk":
        return

    # -------- Phase 2: merge --------
    print("\n▶ Phase 2: hierarchical merge...")
    merged, merge_id = run_merge_phase(
        appid=appid,
        game_name=game.name,
        chunk_summaries=chunk_summaries,
        chunk_ids=chunk_ids,
        backend=backend,
        merge_repo=merge_repo,
        max_chunks_per_merge_call=settings.max_chunks_per_merge_call,
        merge_max_tokens=settings.merge_max_tokens,
        merge_temperature=settings.merge_temperature,
    )
    _print_merge_summary(merged, merge_id)
    if not args.no_dump and merge_id is not None:
        merge_model = config.model_for("merging").replace(".", "-").replace("claude-", "")
        merge_dump = args.dump_dir / f"{appid}_{game.slug}_{merge_model}_merge.org"
        _dump_merge_phase(
            merge_dump,
            appid=appid,
            game_name=game.name,
            merge_repo=merge_repo,
            root_merge_id=merge_id,
        )
        print(f"    org dump: {merge_dump}")
    if stop_after == "merge":
        return

    # -------- Phase 3: synthesis --------
    print("\n▶ Phase 3: synthesis (GameReport)...")
    velocity = review_repo.find_review_velocity(appid)
    ea = review_repo.find_early_access_impact(appid)
    temporal = build_temporal_context(game, velocity, ea)

    tags = tag_repo.find_tags_for_game(appid)
    genres = tag_repo.find_genres_for_game(appid)
    metadata = build_metadata_context(game, tags, genres)

    report = run_synthesis_phase(
        appid=appid,
        game_name=game.name,
        merged=merged,
        total_reviews=len(reviews),
        reviews=reviews,
        steam_positive_pct=float(game.positive_pct) if game.positive_pct is not None else None,
        steam_review_count=game.review_count or None,
        steam_review_score_desc=game.review_score_desc,
        temporal=temporal,
        metadata=metadata,
        backend=backend,
        synthesis_max_tokens=settings.synthesis_max_tokens,
        synthesis_temperature=settings.synthesis_temperature,
    )
    _print_report(report)

    # Persist the report with the same bookkeeping the Lambda writes.
    payload = report.model_dump()
    payload["pipeline_version"] = PIPELINE_VERSION
    payload["chunk_count"] = len(chunk_summaries)
    payload["merged_summary_id"] = merge_id
    report_repo.upsert(payload)
    print(f"\n✔ Report upserted. pipeline_version={PIPELINE_VERSION}")

    if not args.no_dump:
        synth_model = config.model_for("summarizer").replace(".", "-").replace("claude-", "")
        synth_dump = args.dump_dir / f"{appid}_{game.slug}_{synth_model}_synthesis.org"
        _dump_synthesis_phase(
            synth_dump,
            appid=appid,
            game_name=game.name,
        )
        print(f"    org dump: {synth_dump}")


if __name__ == "__main__":
    main()
