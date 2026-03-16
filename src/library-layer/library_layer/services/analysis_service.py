"""AnalysisService — LLM analysis orchestration."""

from __future__ import annotations

import logging
from typing import Any

from library_layer.models.report import Report
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository

logger = logging.getLogger(__name__)

MAX_REVIEWS = 2000


class AnalysisService:
    """Load reviews from DB → run LLM analysis → persist report."""

    def __init__(
        self,
        report_repo: ReportRepository,
        review_repo: ReviewRepository,
        game_repo: GameRepository,
        analyzer: Any,  # library_layer.analyzer.analyze_reviews (async callable)
    ) -> None:
        self._report_repo = report_repo
        self._review_repo = review_repo
        self._game_repo = game_repo
        self._analyzer = analyzer

    async def analyze(self, appid: int) -> Report:
        """Load reviews from DB, run two-pass LLM analysis, upsert report.

        Returns:
            The newly created Report.

        Raises:
            ValueError: If game not found or no reviews available.
        """
        game = self._game_repo.find_by_appid(appid)
        if game is None:
            raise ValueError(f"appid={appid} not found in games table")

        db_reviews = self._review_repo.find_by_appid(appid, limit=MAX_REVIEWS)
        if not db_reviews:
            raise ValueError(f"No reviews found for appid={appid}")

        # Convert DB Review models to the dict format expected by analyzer
        reviews_for_llm = [
            {
                "voted_up": r.voted_up,
                "review_text": r.body or "",
                "playtime_at_review": (r.playtime_hours or 0) * 60,
            }
            for r in db_reviews
            if r.body
        ]

        if not reviews_for_llm:
            raise ValueError(f"No non-empty review bodies for appid={appid}")

        logger.info(
            "Analyzing appid=%s name=%r reviews=%d",
            appid, game.name, len(reviews_for_llm),
        )

        result = await self._analyzer(reviews_for_llm, game.name, appid=appid)
        self._report_repo.upsert(result)

        logger.info(
            "Report stored for appid=%s sentiment=%s",
            appid, result.get("overall_sentiment"),
        )

        report = self._report_repo.find_by_appid(appid)
        if report is None:
            raise RuntimeError(f"Report upsert succeeded but find_by_appid({appid}) returned None")
        return report
