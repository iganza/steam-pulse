"""GenreSynthesisService — Phase-4 cross-genre LLM synthesizer.

Coordinates: resolve eligible appids → cache-check via input_hash →
load GameReports → build LLM prompt → call Bedrock via instructor with
tool_use → persist row → return.

Single Sonnet call per genre per refresh. Input is the per-game
GameReport JSON (~3k tokens each, Phase-3 output), NOT raw reviews —
synthesizing reports is ~$1.30 per genre, synthesizing raw reviews
would be ~$50+ per genre.
"""

from __future__ import annotations

import hashlib
import statistics
from datetime import UTC, datetime

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from library_layer.config import SteamPulseConfig
from library_layer.llm.backend import LLMRequest
from library_layer.llm.converse import ConverseBackend
from library_layer.models.genre_synthesis import (
    GenreSynthesis,
    GenreSynthesisRow,
)
from library_layer.prompts.genre_synthesis_v1 import (
    SYSTEM_PROMPT as GENRE_SYNTHESIS_V1_SYSTEM_PROMPT,
)
from library_layer.prompts.genre_synthesis_v1 import (
    build_user_message as build_genre_synthesis_v1_user_message,
)
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.genre_synthesis_repo import (
    GenreSynthesisRepository,
)
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository

logger = Logger()


class NotEnoughReportsError(RuntimeError):
    """Raised when a slug has fewer than MIN_REPORTS_PER_GENRE eligible reports."""


class GenreSynthesisService:
    """Coordinates the cross-genre synthesis for a single slug."""

    def __init__(
        self,
        *,
        report_repo: ReportRepository,
        tag_repo: TagRepository,
        game_repo: GameRepository,
        synthesis_repo: GenreSynthesisRepository,
        llm_backend: ConverseBackend,
        config: SteamPulseConfig,
        metrics: Metrics,
    ) -> None:
        self._report_repo = report_repo
        self._tag_repo = tag_repo
        self._game_repo = game_repo
        self._synthesis_repo = synthesis_repo
        self._llm = llm_backend
        self._config = config
        self._metrics = metrics

    def synthesize(
        self,
        *,
        slug: str,
        prompt_version: str,
    ) -> GenreSynthesisRow:
        """Run (or cache-hit) the synthesis for one genre slug.

        Steps:
          1. Resolve eligible appids (tag ⋈ games with reports ⋈ min_reviews).
          2. Compute input_hash from (prompt_version, sorted_appids).
          3. Short-circuit: if an existing row has the same input_hash, return it.
          4. Load GameReport JSON for each appid (bounded to MAX_REPORTS_PER_GENRE
             by review_count DESC).
          5. Build the LLM request (system prompt cached, user = report dumps).
          6. Call Bedrock Sonnet via tool_use with GenreSynthesis as response_model.
          7. Upsert the row.
          8. Return the row.
        """
        display_name = self._resolve_display_name(slug)

        eligible = self._tag_repo.find_eligible_for_synthesis(
            slug,
            min_reviews=self._config.GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT,
        )
        if len(eligible) < self._config.MIN_REPORTS_PER_GENRE:
            raise NotEnoughReportsError(
                f"Slug {slug!r} has {len(eligible)} eligible reports; "
                f"need at least {self._config.MIN_REPORTS_PER_GENRE}."
            )

        # find_eligible_for_synthesis returns review_count DESC — take the top N.
        selected_appids = eligible[: self._config.MAX_REPORTS_PER_GENRE]
        sorted_appids = sorted(selected_appids)

        input_hash = _compute_input_hash(
            prompt_version=prompt_version, sorted_appids=sorted_appids
        )

        # Step 3: cache-hit short-circuit. An existing row with the same
        # input_hash means the inputs and prompt haven't changed, so re-
        # running the LLM would produce the same synthesis and waste money.
        existing = self._synthesis_repo.get_by_slug(slug)
        if existing is not None and existing.input_hash == input_hash:
            logger.info(
                "genre_synthesis_cache_hit",
                extra={"slug": slug, "input_hash": input_hash},
            )
            self._metrics.add_metric(
                name="GenreSynthesisCacheHit", unit=MetricUnit.Count, value=1
            )
            return existing

        reports = self._load_reports(selected_appids)
        avg_positive_pct, median_review_count = self._compute_aggregates(selected_appids)

        user_message = build_genre_synthesis_v1_user_message(
            display_name=display_name,
            reports=reports,
            input_appids=sorted_appids,
        )
        request = LLMRequest(
            record_id=f"genre_synthesis:{slug}:{prompt_version}",
            task="genre_synthesis",
            system=GENRE_SYNTHESIS_V1_SYSTEM_PROMPT,
            user=user_message,
            max_tokens=self._config.GENRE_SYNTHESIS_MAX_TOKENS,
            response_model=GenreSynthesis,
        )

        logger.info(
            "genre_synthesis_start",
            extra={
                "slug": slug,
                "input_count": len(selected_appids),
                "prompt_version": prompt_version,
                "input_hash": input_hash,
            },
        )
        self._metrics.add_metric(
            name="GenreSynthesisRuns", unit=MetricUnit.Count, value=1
        )

        [synthesis_obj] = self._llm.run([request])
        if not isinstance(synthesis_obj, GenreSynthesis):
            raise RuntimeError(
                f"LLM returned {type(synthesis_obj).__name__}, expected GenreSynthesis"
            )

        row = GenreSynthesisRow(
            slug=slug,
            display_name=display_name,
            input_appids=selected_appids,
            input_count=len(selected_appids),
            prompt_version=prompt_version,
            input_hash=input_hash,
            synthesis=synthesis_obj,
            narrative_summary=synthesis_obj.narrative_summary,
            avg_positive_pct=avg_positive_pct,
            median_review_count=median_review_count,
            computed_at=datetime.now(UTC),
        )
        self._synthesis_repo.upsert(row)
        logger.info(
            "genre_synthesis_complete",
            extra={"slug": slug, "input_hash": input_hash},
        )
        return row

    def _resolve_display_name(self, slug: str) -> str:
        name = self._tag_repo.find_display_name_for_slug(slug)
        if name is None:
            raise ValueError(f"Unknown tag slug: {slug!r}")
        return name

    def _load_reports(self, appids: list[int]) -> list[dict]:
        """Return [{"appid": int, "report": <GameReport dict>}, ...]

        Ordered to match the input appids list. Skips appids with no
        report (defensive — the tag_repo eligibility query already joined
        on reports).
        """
        entries: list[dict] = []
        for appid in appids:
            report = self._report_repo.find_by_appid(appid)
            if report is None:
                logger.warning(
                    "genre_synthesis_missing_report", extra={"appid": appid}
                )
                continue
            entries.append({"appid": appid, "report": report.report_json})
        return entries

    def _compute_aggregates(self, appids: list[int]) -> tuple[float, int]:
        """Return (avg_positive_pct, median_review_count) across the input games.

        Sourced from the games table — these are descriptive stats about
        the synthesis input set, not derived from the LLM. Used in the
        free insights page header.
        """
        rows = self._game_repo.find_review_stats_for_appids(appids)
        positives = [float(r["positive_pct"]) for r in rows if r["positive_pct"] is not None]
        review_counts = [int(r["review_count"]) for r in rows if r["review_count"] is not None]
        if not positives or not review_counts:
            raise RuntimeError(
                f"No review stats available for any of {len(appids)} appids — "
                f"eligibility query is out of sync with games table."
            )
        avg_positive = sum(positives) / len(positives)
        median_reviews = int(statistics.median(review_counts))
        return avg_positive, median_reviews


def _compute_input_hash(*, prompt_version: str, sorted_appids: list[int]) -> str:
    """Stable cache key for (prompt_version, input set)."""
    appids_str = ",".join(str(a) for a in sorted_appids)
    payload = f"{prompt_version}|{appids_str}".encode()
    return hashlib.sha256(payload).hexdigest()
