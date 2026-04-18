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
from library_layer.prompts import genre_synthesis_v1
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.genre_synthesis_repo import (
    GenreSynthesisRepository,
)
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.tag_repo import TagRepository

logger = Logger()


# Registry of prompt-version → prompt module. Each module must expose
# SYSTEM_PROMPT (str) and build_user_message(*, display_name, reports, input_appids).
# Bumping the wire protocol requires adding a new module here AND the
# corresponding GENRE_SYNTHESIS_PROMPT_VERSION bump in config.
_PROMPT_MODULES = {
    "v1": genre_synthesis_v1,
}


class NotEnoughReportsError(RuntimeError):
    """Raised when a slug has fewer than MIN_REPORTS_PER_GENRE eligible reports."""


class UnknownPromptVersionError(RuntimeError):
    """Raised when prompt_version doesn't map to a known prompt module."""


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
        required_pipeline_version: str,
    ) -> None:
        """`required_pipeline_version` gates which Phase-3 reports count as
        eligible input. After a Phase-3 PIPELINE_VERSION bump, stale reports
        at the old version are excluded — Phase-4 waits until enough games
        have been re-analyzed at the new version before synthesizing again.
        """
        self._report_repo = report_repo
        self._tag_repo = tag_repo
        self._game_repo = game_repo
        self._synthesis_repo = synthesis_repo
        self._llm = llm_backend
        self._config = config
        self._metrics = metrics
        self._required_pipeline_version = required_pipeline_version

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
        # Numerically sorted view of the same set, shown to the LLM as
        # the allow-list of valid source_appid values.
        sorted_appids = sorted(selected_appids)

        # Step 3: cache-hit short-circuit. An existing row with the same
        # input_hash means the inputs and prompt haven't changed, so re-
        # running the LLM would produce the same synthesis and waste money.
        # On hit we still bump computed_at so the next weekly stale-scan
        # doesn't re-enqueue the same slug forever — if we didn't, the row
        # would be stale → enqueued → cache-hit (no write) → still stale.
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
            # Return the row as stored, but with the refreshed timestamp so
            # the caller observes the state that's now in the DB.
            return existing.model_copy(update={"computed_at": now})

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
