"""Tests for scoring utilities."""

import pytest
from library_layer.utils.scores import compute_hidden_gem_score, steam_review_label


@pytest.mark.parametrize(
    "pct, total, expected",
    [
        # Empty → ""
        (0, 0, ""),
        (100, 0, ""),
        # Overwhelmingly Positive: ≥95% & ≥500
        (95, 500, "Overwhelmingly Positive"),
        (99, 2000, "Overwhelmingly Positive"),
        (95, 499, "Very Positive"),  # just below count threshold
        # Very Positive: ≥80% & ≥50
        (80, 50, "Very Positive"),
        (94, 499, "Very Positive"),
        # Positive: ≥80% & <50
        (85, 10, "Positive"),
        (80, 49, "Positive"),
        # Mostly Positive: 70-79%
        (70, 100, "Mostly Positive"),
        (79, 1000, "Mostly Positive"),
        # Mixed: 40-69%
        (40, 100, "Mixed"),
        (55, 500, "Mixed"),
        (69, 10, "Mixed"),
        # Overwhelmingly Negative: <20% & ≥500
        (10, 500, "Overwhelmingly Negative"),
        (19, 1000, "Overwhelmingly Negative"),
        # Very Negative: <20% & ≥50
        (10, 50, "Very Negative"),
        (19, 499, "Very Negative"),
        # Mostly Negative: 20-39%
        (30, 20, "Mostly Negative"),
        (39, 49, "Mostly Negative"),
        # Negative: <20% & <50
        (15, 10, "Negative"),
        (5, 49, "Negative"),
    ],
)
def test_steam_review_label_breakpoints(pct: int, total: int, expected: str) -> None:
    assert steam_review_label(pct, total) == expected


def test_hidden_gem_zero_for_high_reviews() -> None:
    assert compute_hidden_gem_score(90, 10_000) == 0.0


def test_hidden_gem_zero_for_low_quality() -> None:
    assert compute_hidden_gem_score(70, 100) == 0.0


def test_hidden_gem_nonzero_for_scarce_high_quality() -> None:
    assert compute_hidden_gem_score(90, 1000) > 0.0
