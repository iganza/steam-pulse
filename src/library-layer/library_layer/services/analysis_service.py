"""AnalysisService — LLM analysis orchestration."""

from __future__ import annotations

from typing import Any

from aws_lambda_powertools import Logger
from library_layer.models.report import Report
from library_layer.repositories.game_repo import GameRepository
from library_layer.repositories.report_repo import ReportRepository
from library_layer.repositories.review_repo import ReviewRepository

logger = Logger()

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
                "playtime_hours": r.playtime_hours or 0,
                "votes_helpful": r.votes_helpful or 0,
                "votes_funny": r.votes_funny or 0,
                "posted_at": r.posted_at.isoformat() if r.posted_at else None,
                "written_during_early_access": r.written_during_early_access or False,
                "received_for_free": r.received_for_free or False,
            }
            for r in db_reviews
            if r.body
        ]
        reviews_for_llm.sort(key=lambda r: r["posted_at"] or "")

        if not reviews_for_llm:
            raise ValueError(f"No non-empty review bodies for appid={appid}")

        logger.info("Analyzing reviews", extra={"appid": appid, "game_name": game.name, "reviews": len(reviews_for_llm)})

        result = await self._analyzer(reviews_for_llm, game.name, appid=appid)
        self._report_repo.upsert(result)

        logger.info("Report stored", extra={"appid": appid, "sentiment": result.get("overall_sentiment")})

        report = self._report_repo.find_by_appid(appid)
        if report is None:
            raise RuntimeError(f"Report upsert succeeded but find_by_appid({appid}) returned None")
        return report
