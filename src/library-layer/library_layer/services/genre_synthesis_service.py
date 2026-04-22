"""GenreSynthesisService — Phase-4 cross-genre LLM synthesizer.

Step Functions drives this as a two-step batch lifecycle:

- ``prepare_batch()`` resolves eligible appids, computes the input_hash,
  short-circuits on cache hit (touches computed_at, returns skip=True),
  otherwise builds one LLMRequest, submits an Anthropic message batch,
  and inserts a ``batch_executions`` row keyed by slug.

- ``collect_batch()`` runs after the status poller reports ``Completed``:
  pulls the single result, assembles the ``GenreSynthesisRow``, upserts
  ``mv_genre_synthesis``, and marks the ``batch_executions`` row completed
  with token usage + estimated cost.

Input is the per-game GameReport JSON (~3k tokens each, Phase-3 output),
NOT raw reviews — synthesizing reports is ~$1.30 per genre, synthesizing
raw reviews would be ~$50+ per genre. At batch pricing the cost halves
again.
"""

from __future__ import annotations

import hashlib
import statistics
from datetime import UTC, datetime
from decimal import Decimal

from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from library_layer.config import SteamPulseConfig
from library_layer.llm.anthropic_batch import AnthropicBatchBackend
from library_layer.llm.backend import LLMRequest, estimate_batch_cost_usd
from library_layer.models.genre_synthesis import (
    SHARED_SIGNAL_MIN_MENTIONS,
    GenreSynthesis,
    GenreSynthesisRow,
)
from library_layer.prompts import genre_synthesis_v1
from library_layer.repositories.batch_execution_repo import BatchExecutionRepository
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.genre_synthesis_repo import (
    GenreSynthesisRepository,
)
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository
from pydantic import BaseModel, Field

logger = Logger()


# Registry of prompt-version → prompt module. Each module must expose
# SYSTEM_PROMPT (str) and build_user_message(*, display_name, reports, input_appids).
# Bumping the wire protocol requires adding a new module here AND the
# corresponding GENRE_SYNTHESIS_PROMPT_VERSION bump in config.
_PROMPT_MODULES = {
    "v1": genre_synthesis_v1,
}

GENRE_SYNTHESIS_PHASE = "genre_synthesis"


class NotEnoughReportsError(RuntimeError):
    """Raised when a slug has fewer than MIN_REPORTS_PER_GENRE eligible reports."""


class UnknownPromptVersionError(RuntimeError):
    """Raised when prompt_version doesn't map to a known prompt module."""


class PrepareResult(BaseModel):
    """Structured output of ``prepare_batch``, threaded through SFN state.

    When ``skip`` is True the caller should bypass Wait/Check/Collect and
    return directly (cache hit). Otherwise ``job_id`` identifies the
    Anthropic message batch that the status poller should watch, and the
    remaining fields are what ``collect_batch`` needs to build the final
    row without re-running any eligibility/aggregate queries.
    """

    slug: str
    skip: bool
    prompt_version: str
    execution_id: str
    job_id: str = ""
    display_name: str = ""
    selected_appids: list[int] = Field(default_factory=list)
    avg_positive_pct: float = 0.0
    median_review_count: int = 0
    input_hash: str = ""


class GenreSynthesisService:
    """Coordinates the cross-genre synthesis batch lifecycle for a single slug."""

    def __init__(
        self,
        *,
        report_repo: ReportRepository,
        tag_repo: TagRepository,
        game_repo: GameRepository,
        synthesis_repo: GenreSynthesisRepository,
        batch_exec_repo: BatchExecutionRepository,
        config: SteamPulseConfig,
        metrics: Metrics,
        required_pipeline_version: str,
    ) -> None:
        """`required_pipeline_version` gates which Phase-3 reports count as
        eligible input. After a Phase-3 PIPELINE_VERSION bump, stale reports
        at the old version are excluded — Phase-4 waits until enough games
        have been re-analyzed at the new version before synthesizing again.
        """
        if config.MIN_REPORTS_PER_GENRE < SHARED_SIGNAL_MIN_MENTIONS:
            # friction_points / wishlist_items require mention_count >=
            # SHARED_SIGNAL_MIN_MENTIONS. Asking the LLM to produce them
            # from fewer input reports than that minimum is literally
            # impossible — the tool_use schema will fail-and-retry until
            # instructor gives up. Catch the misconfiguration here.
            raise ValueError(
                f"MIN_REPORTS_PER_GENRE={config.MIN_REPORTS_PER_GENRE} is below "
                f"the cross-genre mention_count floor "
                f"({SHARED_SIGNAL_MIN_MENTIONS}). Raise MIN_REPORTS_PER_GENRE or "
                f"lower SHARED_SIGNAL_MIN_MENTIONS if the schema contract is "
                f"being intentionally relaxed."
            )
        self._report_repo = report_repo
        self._tag_repo = tag_repo
        self._game_repo = game_repo
        self._synthesis_repo = synthesis_repo
        self._batch_exec_repo = batch_exec_repo
        self._config = config
        self._metrics = metrics
        self._required_pipeline_version = required_pipeline_version

    # ------------------------------------------------------------------
    # Phase 1: prepare & submit the single-request batch
    # ------------------------------------------------------------------
    def prepare_batch(
        self,
        *,
        slug: str,
        prompt_version: str,
        execution_id: str,
        backend: AnthropicBatchBackend,
    ) -> PrepareResult:
        """Resolve inputs, cache-check, and submit the batch.

        Returns a ``PrepareResult`` with ``skip=True`` on a cache hit
        (``computed_at`` is bumped, no batch submitted, no
        ``batch_executions`` row). Otherwise returns ``skip=False`` plus
        the ``job_id`` of the submitted Anthropic batch and the context
        fields ``collect_batch`` needs to finish the run.
        """
        prompt_module = _PROMPT_MODULES.get(prompt_version)
        if prompt_module is None:
            raise UnknownPromptVersionError(
                f"No prompt module for prompt_version={prompt_version!r}. "
                f"Known versions: {sorted(_PROMPT_MODULES)}"
            )

        display_name = self._resolve_display_name(slug)

        # SQL caps at MAX_REPORTS_PER_GENRE — the repo won't return more than
        # the service intends to synthesize. pipeline_version excludes stale
        # Phase-3 output so a bump forces a natural cache miss and refresh.
        selected_appids = self._tag_repo.find_eligible_for_synthesis(
            slug,
            min_reviews=self._config.GENRE_SYNTHESIS_MIN_GAME_REVIEW_COUNT,
            limit=self._config.MAX_REPORTS_PER_GENRE,
            pipeline_version=self._required_pipeline_version,
        )
        if len(selected_appids) < self._config.MIN_REPORTS_PER_GENRE:
            raise NotEnoughReportsError(
                f"Slug {slug!r} has {len(selected_appids)} eligible reports; "
                f"need at least {self._config.MIN_REPORTS_PER_GENRE}."
            )

        input_hash = _compute_input_hash(
            prompt_version=prompt_version,
            pipeline_version=self._required_pipeline_version,
            appids=selected_appids,
        )

        # Cache-hit short-circuit. An existing row with the same input_hash
        # means the inputs and prompt haven't changed, so re-running the
        # LLM would produce the same synthesis and waste money. On hit we
        # still bump computed_at so the next stale-scan (if one ever
        # re-enters service) doesn't re-enqueue the same slug forever.
        existing = self._synthesis_repo.get_by_slug(slug)
        if existing is not None and existing.input_hash == input_hash:
            now = datetime.now(UTC)
            self._synthesis_repo.touch_computed_at(slug, at=now)
            logger.info(
                "genre_synthesis_cache_hit",
                extra={"slug": slug, "input_hash": input_hash},
            )
            self._metrics.add_metric(
                name="GenreSynthesisCacheHit", unit=MetricUnit.Count, value=1
            )
            return PrepareResult(
                slug=slug,
                skip=True,
                prompt_version=prompt_version,
                execution_id=execution_id,
            )

        # Numerically sorted view of the same set, shown to the LLM as
        # the allow-list of valid source_appid values.
        sorted_appids = sorted(selected_appids)
        reports = self._load_reports(selected_appids)
        avg_positive_pct, median_review_count = self._compute_aggregates(selected_appids)

        user_message = prompt_module.build_user_message(
            display_name=display_name,
            reports=reports,
            input_appids=sorted_appids,
        )
        request = LLMRequest(
            record_id=f"genre_synthesis:{slug}:{prompt_version}",
            task="genre_synthesis",
            system=prompt_module.SYSTEM_PROMPT,
            user=user_message,
            max_tokens=self._config.GENRE_SYNTHESIS_MAX_TOKENS,
            response_model=GenreSynthesis,
        )

        logger.info(
            "genre_synthesis_submit",
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

        prepared = backend.prepare([request], phase=GENRE_SYNTHESIS_PHASE)
        job_id = backend.submit(
            prepared, "genre_synthesis", phase=GENRE_SYNTHESIS_PHASE
        )

        self._batch_exec_repo.insert(
            execution_id=execution_id,
            slug=slug,
            phase=GENRE_SYNTHESIS_PHASE,
            backend=self._config.LLM_BACKEND,
            batch_id=job_id,
            model_id=self._config.model_for("genre_synthesis"),
            request_count=1,
            pipeline_version=self._required_pipeline_version,
            prompt_version=prompt_version,
        )

        return PrepareResult(
            slug=slug,
            skip=False,
            prompt_version=prompt_version,
            execution_id=execution_id,
            job_id=job_id,
            display_name=display_name,
            selected_appids=selected_appids,
            avg_positive_pct=avg_positive_pct,
            median_review_count=median_review_count,
            input_hash=input_hash,
        )

    # ------------------------------------------------------------------
    # Phase 2: collect the batch result and persist
    # ------------------------------------------------------------------
    def collect_batch(
        self,
        *,
        slug: str,
        job_id: str,
        selected_appids: list[int],
        display_name: str,
        avg_positive_pct: float,
        median_review_count: int,
        input_hash: str,
        prompt_version: str,
        backend: AnthropicBatchBackend,
    ) -> GenreSynthesisRow:
        """Pull the single batch result, upsert the row, close the tracking row.

        Tokens and cost are recorded via ``batch_executions.mark_completed``
        before the row is built, so even a validation failure leaves
        cost visible. On failure to build the row, the tracking row is
        flipped to ``failed`` with the failure reason captured.
        """
        collect_result = backend.collect(
            job_id, default_response_model=GenreSynthesis
        )

        # Validate the result shape before recording counts so
        # ``mark_completed`` sees accurate succeeded/failed figures even
        # when the batch is about to be flipped to ``failed``. The
        # lightweight checks never touch the DB and can't raise
        # transient errors, so running them first is safe.
        expected_record_id = f"genre_synthesis:{slug}:{prompt_version}"
        validation_error: str = ""
        synthesis_obj: GenreSynthesis | None = None

        if not collect_result.results:
            validation_error = (
                f"No genre_synthesis output for slug={slug!r} "
                f"(job_id={job_id}, failed_ids={collect_result.failed_ids})"
            )
        elif len(collect_result.results) != 1:
            # prepare_batch submits exactly one request per slug — more
            # than one result means the backend returned something we
            # didn't ask for, bail rather than silently persist results[0].
            validation_error = (
                f"Expected exactly 1 genre_synthesis result for slug={slug!r}, "
                f"got {len(collect_result.results)} "
                f"(record_ids={[rid for rid, _ in collect_result.results]})"
            )
        else:
            record_id, obj = collect_result.results[0]
            if record_id != expected_record_id:
                validation_error = (
                    f"record_id mismatch for slug={slug!r}: expected "
                    f"{expected_record_id!r}, got {record_id!r}"
                )
            elif not isinstance(obj, GenreSynthesis):
                validation_error = (
                    f"Expected GenreSynthesis, got {type(obj).__name__}"
                )
            else:
                synthesis_obj = obj

        if synthesis_obj is None:
            # Collect any result record_ids the batch produced but that
            # didn't pass validation, so operators can correlate.
            unexpected_ids = [rid for rid, _ in collect_result.results]
            succeeded_count = 0
            failed_record_ids = list(collect_result.failed_ids) + unexpected_ids
            failed_count = len(failed_record_ids)
        else:
            succeeded_count = 1
            failed_record_ids = list(collect_result.failed_ids)
            failed_count = len(failed_record_ids)

        # Cost estimation can raise if the model_id isn't in the pricing
        # table — never let that strand the batch_executions row in
        # 'submitted'. Record cost=0 with a warning so mark_completed
        # still runs and the row reaches a terminal state.
        try:
            cost = estimate_batch_cost_usd(
                model_id=self._config.model_for("genre_synthesis"),
                input_tokens=collect_result.input_tokens,
                output_tokens=collect_result.output_tokens,
                cache_read_tokens=collect_result.cache_read_tokens,
                cache_write_tokens=collect_result.cache_write_tokens,
            )
        except Exception:
            logger.exception(
                "batch_execution_cost_estimation_failed",
                extra={"slug": slug, "job_id": job_id},
            )
            cost = 0.0

        # Always record token usage and cost — even if validation below
        # flips the row to 'failed', the API consumed tokens and we need
        # the cost tracked. succeeded/failed counts now reflect the
        # validated outcome, not raw backend.collect output.
        try:
            self._batch_exec_repo.mark_completed(
                job_id,
                succeeded_count=succeeded_count,
                failed_count=failed_count,
                failed_record_ids=failed_record_ids,
                input_tokens=collect_result.input_tokens,
                output_tokens=collect_result.output_tokens,
                cache_read_tokens=collect_result.cache_read_tokens,
                cache_write_tokens=collect_result.cache_write_tokens,
                estimated_cost_usd=Decimal(str(round(cost, 4))),
            )
        except Exception:
            logger.exception(
                "batch_execution_mark_completed_failed",
                extra={"slug": slug, "job_id": job_id},
            )

        if synthesis_obj is None:
            try:
                self._batch_exec_repo.mark_failed(
                    job_id,
                    failure_reason=f"genre_synthesis collect failed for slug={slug!r}: {validation_error}",
                )
            except Exception:
                logger.exception(
                    "batch_execution_mark_failed_failed",
                    extra={"slug": slug, "job_id": job_id},
                )
            raise RuntimeError(validation_error)

        try:
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
        except Exception as exc:
            try:
                self._batch_exec_repo.mark_failed(
                    job_id,
                    failure_reason=f"genre_synthesis collect failed for slug={slug!r}: {exc}",
                )
            except Exception:
                logger.exception(
                    "batch_execution_mark_failed_failed",
                    extra={"slug": slug, "job_id": job_id},
                )
            raise

        logger.info(
            "genre_synthesis_complete",
            extra={"slug": slug, "input_hash": input_hash, "job_id": job_id},
        )
        return row

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_display_name(self, slug: str) -> str:
        name = self._tag_repo.find_display_name_for_slug(slug)
        if name is None:
            raise ValueError(f"Unknown tag slug: {slug!r}")
        return name

    def _load_reports(self, appids: list[int]) -> list[dict[str, object]]:
        """Return [{"appid": int, "report": <GameReport dict>}, ...]

        Ordered to match the input appids list. The eligibility query
        already INNER-joined on `reports`, so every appid here MUST have
        a report. A None return is treated as an invariant violation:
        silently skipping would make input_hash (built from selected_appids)
        disagree with the actually-sent input and produce a poisoned
        cache entry on next run.
        """
        entries: list[dict[str, object]] = []
        for appid in appids:
            report = self._report_repo.find_by_appid(appid)
            if report is None:
                raise RuntimeError(
                    f"Report missing for appid={appid} despite passing "
                    f"eligibility join — race between tag_repo.find_eligible_"
                    f"for_synthesis and report_repo.find_by_appid. "
                    f"Abort to avoid a poisoned input_hash."
                )
            entries.append({"appid": appid, "report": report.report_json})
        return entries

    def _compute_aggregates(self, appids: list[int]) -> tuple[float, int]:
        """Return (avg_positive_pct, median_review_count) across the input games.

        Sourced from the games table — these are descriptive stats about
        the synthesis input set, not derived from the LLM. Used in the
        free insights page header.

        Every appid in `appids` must produce non-NULL positive_pct and
        review_count. The tag-eligibility query already INNER-joined on
        `games`, and the review-count threshold filter there guarantees
        non-NULL review_count. If this invariant ever breaks, fail loudly
        instead of silently computing stats over a subset.
        """
        rows = self._game_repo.find_review_stats_for_appids(appids)
        if len(rows) != len(appids):
            returned = {int(r["appid"]) for r in rows}
            missing = sorted(set(appids) - returned)
            raise RuntimeError(
                f"Review stats missing for {len(missing)} of {len(appids)} "
                f"appids ({missing[:10]}…) — eligibility query is out of "
                f"sync with games table."
            )
        null_positive = [int(r["appid"]) for r in rows if r["positive_pct"] is None]
        null_reviews = [int(r["appid"]) for r in rows if r["review_count"] is None]
        if null_positive or null_reviews:
            raise RuntimeError(
                f"NULL aggregate inputs — positive_pct NULL for "
                f"{null_positive[:10]}, review_count NULL for {null_reviews[:10]}. "
                f"Every eligible game must have both populated."
            )
        positives = [float(r["positive_pct"]) for r in rows]
        review_counts = [int(r["review_count"]) for r in rows]
        avg_positive = sum(positives) / len(positives)
        # median_low is a deterministic integer drawn from the sample —
        # int(statistics.median(...)) truncates the .5 case for even-count
        # samples and skews the statistic.
        median_reviews = statistics.median_low(review_counts)
        return avg_positive, median_reviews


def _compute_input_hash(
    *, prompt_version: str, pipeline_version: str, appids: list[int]
) -> str:
    """Stable cache key for (prompt_version, pipeline_version, appid set).

    Including `pipeline_version` matters because a Phase-3 PIPELINE_VERSION
    bump can refresh the underlying reports without changing the eligible
    appid set (if the same games get re-analyzed at the new version). A
    hash keyed only on appids would treat that as a cache hit and return
    a synthesis built from the old, no-longer-present reports.

    Callers pass appids in any order; the function sorts internally so
    review_count-DESC and numerically-sorted views of the same set hash
    to the same value.
    """
    appids_str = ",".join(str(a) for a in sorted(appids))
    payload = f"{prompt_version}|{pipeline_version}|{appids_str}".encode()
    return hashlib.sha256(payload).hexdigest()
