# Prompt Eval Pipeline — Implementation Prompt

## Goal

Build a **lightweight, Python-native prompt evaluation harness** that scores
LLM analyzer output quality across measurable dimensions. No external eval
frameworks (no Promptfoo, no LangSmith) — just pytest + scoring functions +
Rich console reports.

The pipeline lets us:
1. Run the analyzer on **curated test games** with real review data
2. **Score outputs** against 40+ automated criteria extracted from our Pydantic models and prompt rules
3. **Compare prompt versions** side-by-side (before/after the upgrade)
4. **Catch regressions** — a CI-friendly pytest suite that fails if quality drops

---

## Architecture

```
scripts/eval/
├── __init__.py
├── runner.py           # Orchestrates eval runs, caches results
├── scorers.py          # All scoring functions (pure, no I/O)
├── reporter.py         # Rich console + JSON report generation
├── conftest.py         # pytest fixtures for eval tests
└── fixtures/
    └── .gitkeep        # Cached review data goes here (gitignored JSON)

tests/eval/
├── __init__.py
├── test_scorers.py     # Unit tests for every scoring function
└── test_eval_suite.py  # Integration: run analyzer + score (marks: slow, llm)
```

---

## Part 1 — Scoring Functions (`scripts/eval/scorers.py`)

Every scorer takes a report dict (the `GameReport.model_dump()` output) and
returns a `ScoreResult`. Scorers are **pure functions** — no DB, no network,
no LLM calls.

### Score Result Model

```python
"""Eval scoring functions for the LLM analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreResult:
    """Result of a single scoring check."""
    name: str
    passed: bool
    score: float          # 0.0 to 1.0
    max_score: float      # weight of this check
    details: str = ""     # human-readable explanation
    category: str = ""    # grouping key


@dataclass
class EvalReport:
    """Aggregated eval results for one game."""
    game_name: str
    appid: int
    total_reviews: int
    scores: list[ScoreResult] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return sum(s.score for s in self.scores)

    @property
    def max_possible(self) -> float:
        return sum(s.max_score for s in self.scores)

    @property
    def pct(self) -> float:
        return (self.total_score / self.max_possible * 100) if self.max_possible else 0.0

    @property
    def pass_count(self) -> int:
        return sum(1 for s in self.scores if s.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for s in self.scores if not s.passed)

    def by_category(self) -> dict[str, list[ScoreResult]]:
        cats: dict[str, list[ScoreResult]] = {}
        for s in self.scores:
            cats.setdefault(s.category, []).append(s)
        return cats
```

### Scoring Categories & Functions

Implement ALL of these. Each function signature:
```python
def score_xxx(report: dict, reviews: list[dict] | None = None) -> ScoreResult:
```

The optional `reviews` parameter is the raw review list fed to the analyzer —
needed for ground-truth checks.

---

#### Category 1: Structural Validity (weight: 1.0 each)

These are binary pass/fail — the output either conforms or it doesn't.

| Scorer | What it checks |
|--------|---------------|
| `score_pydantic_valid` | Report parses as `GameReport` without ValidationError. Run `GameReport(**report)`. Score 1.0 if valid, 0.0 if not. |
| `score_sentiment_score_range` | `sentiment_score` is float in [0.0, 1.0] |
| `score_sentiment_label_match` | `overall_sentiment` matches the expected label for the `sentiment_score` value. Use the same binning as `_sentiment_label()`: ≥0.95 → "Overwhelmingly Positive", ≥0.80 → "Very Positive", ≥0.65 → "Mostly Positive", ≥0.45 → "Mixed", ≥0.30 → "Mostly Negative", ≥0.15 → "Very Negative", else "Overwhelmingly Negative" |
| `score_hidden_gem_range` | `hidden_gem_score` is float in [0.0, 1.0] |
| `score_review_count_match` | `total_reviews_analyzed` matches `len(reviews)` (if reviews provided) |
| `score_sentiment_trend_valid` | `sentiment_trend` is one of "improving", "stable", "declining" |
| `score_appid_present` | `appid` is not None and is a positive integer |

#### Category 2: List Length Compliance (weight: 1.0 each)

Check every constrained list field against its Pydantic min/max:

| Scorer | Field | Current Constraints | Post-Upgrade Constraints |
|--------|-------|-------------------|--------------------------|
| `score_design_strengths_len` | `design_strengths` | 4–8 items | 2–8 items |
| `score_gameplay_friction_len` | `gameplay_friction` | 3–7 items | 1–7 items |
| `score_player_wishlist_len` | `player_wishlist` | 3–6 items | 1–6 items |
| `score_churn_triggers_len` | `churn_triggers` | 2–4 items | 1–4 items |
| `score_dev_priorities_len` | `dev_priorities` | 3–5 items | 3–5 items |
| `score_archetypes_len` | `audience_profile.archetypes` | 2–4 | 2–4 |
| `score_not_for_len` | `audience_profile.not_for` | 2–3 | 2–3 |

**Important:** Make min/max configurable via a dict constant so the same scorers
work for both current and upgraded prompts:

```python
# Default constraints (current prompts)
LIST_CONSTRAINTS: dict[str, tuple[int, int]] = {
    "design_strengths": (4, 8),
    "gameplay_friction": (3, 7),
    "player_wishlist": (3, 6),
    "churn_triggers": (2, 4),
    "dev_priorities": (3, 5),
    "audience_profile.archetypes": (2, 4),
    "audience_profile.not_for": (2, 3),
}

# Post-upgrade constraints
LIST_CONSTRAINTS_V2: dict[str, tuple[int, int]] = {
    "design_strengths": (2, 8),
    "gameplay_friction": (1, 7),
    "player_wishlist": (1, 6),
    "churn_triggers": (1, 4),
    "dev_priorities": (3, 5),
    "audience_profile.archetypes": (2, 4),
    "audience_profile.not_for": (2, 3),
}
```

#### Category 3: Content Specificity (weight: 2.0 each — most important)

These use heuristics to detect vague vs. concrete language. Higher weight because
this is the difference between a useful report and LLM slop.

| Scorer | What it checks | Heuristic |
|--------|---------------|-----------|
| `score_no_vague_language` | Report doesn't contain weasel words | Check all string fields for: "some players", "various issues", "certain aspects", "a number of", "in many ways", "quite a few", "to some extent", "arguably", "it seems". Score = 1.0 - (vague_count × 0.1), min 0.0. |
| `score_no_corporate_jargon` | No banned corporate language | Check for: "leverage", "synergy", "pain points", "ecosystem", "robust", "scalable", "best-in-class", "industry-leading", "game-changing", "revolutionary". Score = 1.0 - (jargon_count × 0.15), min 0.0. |
| `score_churn_timing_language` | `churn_triggers` items contain temporal cues | Each trigger should reference timing: "first", "hour", "minute", "session", "early", "after", "within", "initial", "tutorial", "onboarding". Score = items_with_timing / total_items. |
| `score_dev_priorities_frequency` | `dev_priorities` items cite frequency % | Each dev_priority.frequency should contain a number with "%" (e.g., "~30% of negative reviews"). Score = items_with_pct / total_items. |
| `score_dev_priorities_actionable` | Actions are concrete, not vague | Each dev_priority.action should start with a verb and be ≥5 words. Score = actionable_count / total_items. |
| `score_one_liner_concise` | `one_liner` is ≤25 words | word_count = len(one_liner.split()). Score = 1.0 if ≤25, else max(0.0, 1.0 - (word_count - 25) × 0.1). |
| `score_one_liner_no_hedge` | `one_liner` is decisive, not wishy-washy | Check for hedging: "but", "however", "despite", "although", "if you". Score = 1.0 if none found, 0.5 if one, 0.0 if ≥2. |
| `score_strengths_specificity` | `design_strengths` items name concrete things | Each item should be ≥4 words and mention a specific game element (not "good gameplay"). Penalize items that are <4 words. Score = specific_count / total_items. |
| `score_genre_context_length` | `genre_context` is substantive | Should be 15–100 words. Score = 1.0 if in range, 0.5 if 10–14 or 101–150, 0.0 otherwise. |

#### Category 4: Anti-Duplication (weight: 2.0 each)

Our synthesis prompt has explicit anti-duplication rules. These scorers enforce
them programmatically.

| Scorer | What it checks | Heuristic |
|--------|---------------|-----------|
| `score_no_cross_section_duplication` | Same concept doesn't appear in multiple sections | Build a set of 3-word shingles from each section (design_strengths, gameplay_friction, player_wishlist, churn_triggers). Check pairwise overlap. Score = 1.0 - (overlap_pairs × 0.2), min 0.0. |
| `score_wishlist_not_fixes` | `player_wishlist` items are net-new features, not fixes | Penalize items containing fix-language: "fix", "repair", "improve existing", "better", "more stable", "less buggy", "should work". Score = clean_count / total_items. |
| `score_friction_not_external` | `gameplay_friction` focuses on in-game issues | Penalize items about: "price", "developer", "update", "server", "community", "toxic". Score = in_game_count / total_items. |

#### Category 5: Ground Truth Consistency (weight: 1.5 each)

These require the raw `reviews` list to cross-check LLM claims.

| Scorer | What it checks | Heuristic |
|--------|---------------|-----------|
| `score_sentiment_score_ground_truth` | `sentiment_score` is close to actual positive ratio | Compute `actual = sum(r["voted_up"] for r in reviews) / len(reviews)`. Score = 1.0 - abs(report_score - actual). Note: sentiment_score is now Python-computed, so this should always be ~1.0 after the upgrade. |
| `score_notable_quotes_verbatim` | Quotes in chunk summaries appear in actual review text | For each notable_quote in chunk summaries, check if ≥80% of words appear in any review. This scorer takes `chunk_summaries` as additional input. Score = verified_count / total_quotes. |
| `score_batch_stats_accuracy` | Chunk batch_stats match actual review counts | Sum positive_count and negative_count across chunks. Compare to actual voted_up counts. Score = 1.0 if within 5% tolerance, else proportional. |

#### Category 6: New Sections (post-upgrade only, weight: 1.0 each)

These only run when the report includes the new sections from the upgrade.
Use a helper `_has_section(report, key)` that returns False if the key is
missing or None — don't fail, just skip with score=0 and details="section not present".

| Scorer | What it checks |
|--------|---------------|
| `score_refund_risk_present` | `refund_risk_assessment` exists with valid `risk_level` in ["low", "medium", "high"] |
| `score_refund_risk_coherent` | If `refund_language_frequency` is "none", then `risk_level` should be "low" and `primary_refund_drivers` should be empty |
| `score_community_health_present` | `community_health` exists with valid `overall` literal |
| `score_community_health_multiplayer_coherent` | If game is single-player (no multiplayer tag), `multiplayer_population` should be "not_applicable" |
| `score_monetization_present` | `monetization_sentiment` exists with valid `overall` literal |
| `score_monetization_f2p_coherent` | If game is F2P and has microtransaction complaints, `overall` should not be "not_applicable" |
| `score_content_depth_present` | `content_depth` exists with all four fields |
| `score_content_depth_playtime_coherent` | `perceived_length` should roughly correlate with avg playtime from reviews: <5h → short, 5-20h → medium, 20-100h → long, >100h → endless |
| `score_technical_issues_present` | `technical_issues` list exists and is non-empty (most games have at least one) |

---

## Part 2 — Eval Runner (`scripts/eval/runner.py`)

The runner orchestrates evaluation runs. It:
1. Loads review data (from DB or cached fixture files)
2. Runs the analyzer (or loads cached results)
3. Runs all applicable scorers
4. Returns `EvalReport` objects

### Key Design Decisions

**Caching is critical.** LLM calls cost money. The runner caches:
- **Review data** → `scripts/eval/fixtures/{appid}_reviews.json`
- **Analyzer results** → `scripts/eval/fixtures/{appid}_report_{version}.json`

Version is a hash of the prompt text so changed prompts auto-invalidate cache.

```python
"""Eval pipeline runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .scorers import (
    EvalReport,
    ScoreResult,
    # ... all scorer functions
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURES_DIR.mkdir(exist_ok=True)


class EvalRunner:
    """Orchestrates prompt evaluation runs."""

    def __init__(self, prompt_version: str = "current"):
        self.prompt_version = prompt_version
        self._scorers = _build_scorer_list(prompt_version)

    def load_reviews(self, appid: int) -> list[dict]:
        """Load reviews from cache or DB."""
        cache_path = FIXTURES_DIR / f"{appid}_reviews.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())

        # Fall back to DB
        reviews = self._fetch_reviews_from_db(appid)
        cache_path.write_text(json.dumps(reviews, indent=2))
        return reviews

    def run_analysis(self, appid: int, reviews: list[dict], game_name: str) -> dict:
        """Run analyzer and cache result."""
        cache_path = FIXTURES_DIR / f"{appid}_report_{self.prompt_version}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())

        import asyncio
        from library_layer.analyzer import analyze_reviews
        result = asyncio.run(analyze_reviews(reviews, game_name, appid=appid))
        cache_path.write_text(json.dumps(result, indent=2))
        return result

    def score(self, report: dict, reviews: list[dict] | None = None,
              chunk_summaries: list[dict] | None = None) -> EvalReport:
        """Run all scorers against a report."""
        eval_report = EvalReport(
            game_name=report.get("game_name", "Unknown"),
            appid=report.get("appid", 0),
            total_reviews=report.get("total_reviews_analyzed", 0),
        )
        for scorer_fn in self._scorers:
            try:
                result = scorer_fn(report, reviews=reviews)
                eval_report.scores.append(result)
            except Exception as exc:
                eval_report.scores.append(ScoreResult(
                    name=scorer_fn.__name__,
                    passed=False,
                    score=0.0,
                    max_score=1.0,
                    details=f"Scorer error: {exc}",
                    category="error",
                ))
        return eval_report

    def _fetch_reviews_from_db(self, appid: int) -> list[dict]:
        """Fetch reviews from the local database."""
        import os
        import psycopg2
        import psycopg2.extras
        url = os.environ.get("DATABASE_URL", "postgresql://steampulse:dev@localhost:5432/steampulse")
        conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT voted_up, body, playtime_at_review, votes_helpful, "
                    "votes_funny, posted_at, written_during_early_access, received_for_free "
                    "FROM reviews WHERE appid = %s ORDER BY posted_at DESC LIMIT 2000",
                    (appid,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]


def _build_scorer_list(version: str) -> list:
    """Build the list of scorer functions based on prompt version."""
    # Always include structural, list-length, content, anti-dup scorers
    # Only include Category 6 (new sections) for version "v2" or "upgraded"
    ...
```

### CLI Interface

Add an `eval` subcommand to `scripts/sp.py`:

```bash
# Run eval on a single game (fetches reviews, runs analyzer, scores)
poetry run python scripts/sp.py eval 440

# Run eval on a game with cached results only (no LLM call)
poetry run python scripts/sp.py eval 440 --cached

# Run eval on all test games
poetry run python scripts/sp.py eval --suite

# Compare two prompt versions
poetry run python scripts/sp.py eval 440 --compare current upgraded

# Export results as JSON
poetry run python scripts/sp.py eval --suite --json > eval_results.json
```

**sp.py integration pattern** — follow the existing subcommand pattern:

```python
def cmd_eval(appids: list[int], suite: bool, cached: bool,
             compare: str | None, json_output: bool) -> None:
    """Run prompt evaluation pipeline."""
    from scripts.eval.runner import EvalRunner
    from scripts.eval.reporter import print_eval_report, print_comparison

    if suite:
        appids = TEST_SUITE_GAMES

    runner = EvalRunner()
    reports = []
    for appid in appids:
        reviews = runner.load_reviews(appid) if not cached else None
        report = runner.run_analysis(appid, reviews, _game_name(appid))
        eval_report = runner.score(report, reviews=reviews)
        reports.append(eval_report)

    if compare:
        runner_v2 = EvalRunner(prompt_version=compare)
        # ... run v2, print side-by-side
    elif json_output:
        # ... dump JSON
    else:
        for er in reports:
            print_eval_report(er)
```

---

## Part 3 — Rich Console Reporter (`scripts/eval/reporter.py`)

### Single Game Report

```
╭─ Eval: Team Fortress 2 (440) ── 188 reviews ─╮
│                                                │
│  Overall: 87.3% (34/39 passed)                 │
│                                                │
│  ✅ Structural Validity    7/7   100%          │
│  ✅ List Length             7/7   100%          │
│  ⚠️  Content Specificity    7/9   82%           │
│  ✅ Anti-Duplication        3/3   100%          │
│  ⚠️  Ground Truth           2/3   89%           │
│  ❌ New Sections            0/9   n/a (v1)     │
│                                                │
│  Failed Checks:                                │
│  · score_churn_timing_language: 0.50           │
│    2/4 triggers missing temporal cues           │
│  · score_dev_priorities_frequency: 0.60        │
│    2/5 priorities missing % frequency           │
│                                                │
╰────────────────────────────────────────────────╯
```

Use Rich `Panel`, `Table`, and color coding:
- ✅ green for ≥90%
- ⚠️ yellow for ≥70%
- ❌ red for <70%

### Comparison Report

When `--compare` is used, show side-by-side:

```
╭─ Comparison: Team Fortress 2 (440) ───────────────╮
│                                                     │
│  Category              current  upgraded    Δ      │
│  ─────────────────────────────────────────────────  │
│  Structural Validity    100%     100%      =       │
│  List Length             100%     100%      =       │
│  Content Specificity     82%      91%     +9% ↑    │
│  Anti-Duplication        100%     100%      =       │
│  Ground Truth            89%      98%     +9% ↑    │
│  New Sections            n/a      78%     new      │
│  ─────────────────────────────────────────────────  │
│  TOTAL                   87%      93%     +6% ↑    │
│                                                     │
╰─────────────────────────────────────────────────────╯
```

### Suite Summary Table

When `--suite` runs multiple games:

```
╭─ Eval Suite Summary ─────────────────────────────╮
│                                                    │
│  Game                    Reviews  Score  Status   │
│  ──────────────────────────────────────────────   │
│  Team Fortress 2 (440)    188     87%    ⚠️       │
│  Stardew Valley (413150)  500     94%    ✅       │
│  Cyberpunk 2077 (1091500) 500     91%    ✅       │
│  No Man's Sky (275850)    500     89%    ⚠️       │
│  ──────────────────────────────────────────────   │
│  Average                          90%    ✅       │
│                                                    │
╰────────────────────────────────────────────────────╯
```

---

## Part 4 — Test Suite Games

Define a curated set of games that exercise different scenarios. Use these
appids (we'll populate fixture data during the first run):

```python
# scripts/eval/runner.py

TEST_SUITE_GAMES: dict[int, dict] = {
    # appid → metadata for context-aware scoring
    440: {
        "name": "Team Fortress 2",
        "tags": ["Free to Play", "Multiplayer", "FPS", "Shooter"],
        "is_f2p": True,
        "is_multiplayer": True,
        "is_early_access": False,
        "expected_sentiment": "Very Positive",
    },
    413150: {
        "name": "Stardew Valley",
        "tags": ["Farming Sim", "RPG", "Indie", "Relaxing"],
        "is_f2p": False,
        "is_multiplayer": False,
        "is_early_access": False,
        "expected_sentiment": "Overwhelmingly Positive",
    },
    1091500: {
        "name": "Cyberpunk 2077",
        "tags": ["RPG", "Open World", "Cyberpunk", "Singleplayer"],
        "is_f2p": False,
        "is_multiplayer": False,
        "is_early_access": False,
        "expected_sentiment": "Mostly Positive",
    },
    275850: {
        "name": "No Man's Sky",
        "tags": ["Open World", "Survival", "Exploration", "Multiplayer"],
        "is_f2p": False,
        "is_multiplayer": True,
        "is_early_access": False,
        "expected_sentiment": "Mostly Positive",
    },
    # Add more after initial run — aim for 8-10 covering:
    # - An Early Access game
    # - A "Mixed" sentiment game
    # - A hidden gem (low reviews, high sentiment)
    # - A game with known monetization complaints
}
```

**Why these four:**
- **TF2:** F2P + multiplayer + old → tests community_health, monetization, churn
- **Stardew Valley:** Overwhelmingly Positive indie → tests hidden_gem_score, content_depth
- **Cyberpunk 2077:** Rocky launch → tests technical_issues, refund_risk, sentiment_trend
- **No Man's Sky:** Massive sentiment reversal → tests sentiment_trend "improving"

---

## Part 5 — pytest Integration (`tests/eval/`)

### Unit Tests for Scorers (`tests/eval/test_scorers.py`)

Every scorer needs at least 3 unit tests: a passing case, a failing case, and
an edge case. **No LLM calls — all use synthetic report dicts.**

```python
"""Unit tests for eval scoring functions."""

import pytest
from scripts.eval.scorers import (
    ScoreResult,
    score_pydantic_valid,
    score_sentiment_score_range,
    score_sentiment_label_match,
    score_no_vague_language,
    score_no_corporate_jargon,
    score_churn_timing_language,
    score_dev_priorities_frequency,
    score_no_cross_section_duplication,
    score_wishlist_not_fixes,
    score_sentiment_score_ground_truth,
    score_one_liner_concise,
    score_design_strengths_len,
    # ... etc
)


# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def valid_report() -> dict:
    """A minimal valid GameReport dict that passes all structural checks."""
    return {
        "game_name": "Test Game",
        "total_reviews_analyzed": 100,
        "overall_sentiment": "Mostly Positive",
        "sentiment_score": 0.72,
        "sentiment_trend": "stable",
        "sentiment_trend_note": "Sentiment has been consistent over the past 6 months.",
        "one_liner": "A solid RPG with deep crafting but rough edges in combat balance.",
        "audience_profile": {
            "ideal_player": "Patient RPG fans who enjoy crafting systems",
            "casual_friendliness": "medium",
            "archetypes": ["Crafters", "Explorers", "Completionists"],
            "not_for": ["Speedrunners", "PvP-focused players"],
        },
        "design_strengths": [
            "Deep crafting system with 200+ recipes",
            "Procedurally generated dungeons maintain freshness",
            "Excellent soundtrack with dynamic music system",
            "Smooth controller support with remappable buttons",
        ],
        "gameplay_friction": [
            "Combat balance favors ranged builds over melee",
            "Inventory management becomes tedious past hour 20",
            "Boss difficulty spikes at chapter 3 with no warning",
        ],
        "player_wishlist": [
            "Mod support for custom recipes",
            "New game plus mode",
            "Transmog or cosmetic system",
        ],
        "churn_triggers": [
            "Mandatory 45-minute tutorial with no skip option",
            "First boss at hour 3 is an unlearnable difficulty spike",
        ],
        "dev_priorities": [
            {
                "action": "Add skip option for the tutorial sequence",
                "why_it_matters": "Players cite the tutorial as the #1 reason they nearly quit",
                "frequency": "~40% of negative reviews mention this",
                "effort": "low",
            },
            {
                "action": "Rebalance chapter 3 boss HP and damage output",
                "why_it_matters": "Causes a visible churn spike at the 3-hour mark",
                "frequency": "~25% of negative reviews",
                "effort": "medium",
            },
            {
                "action": "Implement auto-sort and search for inventory",
                "why_it_matters": "Inventory friction compounds over long play sessions",
                "frequency": "~15% of all reviews mention inventory",
                "effort": "medium",
            },
        ],
        "competitive_context": [],
        "genre_context": "Performs above average for indie RPGs in crafting depth, but combat polish trails behind genre leaders like Hades and Dead Cells.",
        "hidden_gem_score": 0.65,
        "appid": 99999,
    }


@pytest.fixture
def sample_reviews() -> list[dict]:
    """Matching reviews for the valid_report fixture."""
    positive = [{"voted_up": True, "review_text": f"Great game #{i}", "playtime_at_review": 3600} for i in range(72)]
    negative = [{"voted_up": False, "review_text": f"Bad balance #{i}", "playtime_at_review": 1800} for i in range(28)]
    return positive + negative


# ── Structural Validity Tests ─────────────────────────────

class TestStructuralValidity:
    def test_pydantic_valid_passes(self, valid_report):
        r = score_pydantic_valid(valid_report)
        assert r.passed and r.score == 1.0

    def test_pydantic_valid_fails_bad_sentiment(self, valid_report):
        valid_report["overall_sentiment"] = "Kinda Good"
        r = score_pydantic_valid(valid_report)
        assert not r.passed and r.score == 0.0

    def test_sentiment_range_passes(self, valid_report):
        r = score_sentiment_score_range(valid_report)
        assert r.passed

    def test_sentiment_range_fails_negative(self, valid_report):
        valid_report["sentiment_score"] = -0.1
        r = score_sentiment_score_range(valid_report)
        assert not r.passed

    def test_sentiment_label_match_correct(self, valid_report):
        # 0.72 → Mostly Positive (≥0.65)
        r = score_sentiment_label_match(valid_report)
        assert r.passed

    def test_sentiment_label_match_wrong(self, valid_report):
        valid_report["overall_sentiment"] = "Very Positive"  # Wrong for 0.72
        r = score_sentiment_label_match(valid_report)
        assert not r.passed


# ── Content Specificity Tests ─────────────────────────────

class TestContentSpecificity:
    def test_no_vague_language_clean(self, valid_report):
        r = score_no_vague_language(valid_report)
        assert r.passed

    def test_no_vague_language_catches_weasel_words(self, valid_report):
        valid_report["design_strengths"][0] = "Some players enjoy various aspects of the game"
        r = score_no_vague_language(valid_report)
        assert r.score < 1.0

    def test_no_corporate_jargon_clean(self, valid_report):
        r = score_no_corporate_jargon(valid_report)
        assert r.passed

    def test_no_corporate_jargon_catches_synergy(self, valid_report):
        valid_report["genre_context"] = "This game leverages synergy between combat and crafting."
        r = score_no_corporate_jargon(valid_report)
        assert r.score < 1.0

    def test_churn_timing_all_present(self, valid_report):
        r = score_churn_timing_language(valid_report)
        assert r.score == 1.0  # Both triggers have timing

    def test_churn_timing_none_present(self, valid_report):
        valid_report["churn_triggers"] = ["Bad combat", "Boring gameplay"]
        r = score_churn_timing_language(valid_report)
        assert r.score == 0.0

    def test_dev_priorities_frequency_present(self, valid_report):
        r = score_dev_priorities_frequency(valid_report)
        assert r.score == 1.0  # All have ~X%

    def test_one_liner_concise_passes(self, valid_report):
        r = score_one_liner_concise(valid_report)
        assert r.passed  # 13 words

    def test_one_liner_too_long(self, valid_report):
        valid_report["one_liner"] = " ".join(["word"] * 30)
        r = score_one_liner_concise(valid_report)
        assert r.score < 1.0


# ── Anti-Duplication Tests ────────────────────────────────

class TestAntiDuplication:
    def test_no_duplication_clean(self, valid_report):
        r = score_no_cross_section_duplication(valid_report)
        assert r.passed

    def test_duplication_detected(self, valid_report):
        # Put the same phrase in both sections
        valid_report["design_strengths"][0] = "Combat balance is excellent across all builds"
        valid_report["gameplay_friction"][0] = "Combat balance favors certain builds unfairly"
        r = score_no_cross_section_duplication(valid_report)
        # Shingling may or may not catch this — depends on overlap threshold
        # At minimum, the scorer should run without error

    def test_wishlist_not_fixes_clean(self, valid_report):
        r = score_wishlist_not_fixes(valid_report)
        assert r.score == 1.0

    def test_wishlist_catches_fix_language(self, valid_report):
        valid_report["player_wishlist"][0] = "Fix the broken inventory system"
        r = score_wishlist_not_fixes(valid_report)
        assert r.score < 1.0


# ── Ground Truth Tests ────────────────────────────────────

class TestGroundTruth:
    def test_sentiment_ground_truth_accurate(self, valid_report, sample_reviews):
        # Report says 0.72, actual is 72/100 = 0.72
        r = score_sentiment_score_ground_truth(valid_report, reviews=sample_reviews)
        assert r.score >= 0.95

    def test_sentiment_ground_truth_way_off(self, valid_report, sample_reviews):
        valid_report["sentiment_score"] = 0.10  # Way off from 0.72
        r = score_sentiment_score_ground_truth(valid_report, reviews=sample_reviews)
        assert r.score < 0.5
```

### Integration Tests (`tests/eval/test_eval_suite.py`)

These actually call the LLM. Mark them so they only run when explicitly requested.

```python
"""Integration tests that run the actual analyzer and score the output.

Run with: pytest tests/eval/test_eval_suite.py -m llm --timeout=120
"""

import pytest
from scripts.eval.runner import EvalRunner, TEST_SUITE_GAMES

pytestmark = [
    pytest.mark.llm,       # Only run when -m llm is specified
    pytest.mark.slow,      # Takes 30-60s per game
    pytest.mark.timeout(180),
]


QUALITY_THRESHOLD = 75.0  # Minimum acceptable score (%)


@pytest.fixture(scope="module")
def runner():
    return EvalRunner()


@pytest.mark.parametrize("appid", list(TEST_SUITE_GAMES.keys()))
def test_game_quality_above_threshold(runner, appid):
    """Every test game must score above the quality threshold."""
    meta = TEST_SUITE_GAMES[appid]
    reviews = runner.load_reviews(appid)
    report = runner.run_analysis(appid, reviews, meta["name"])
    eval_report = runner.score(report, reviews=reviews)
    assert eval_report.pct >= QUALITY_THRESHOLD, (
        f"{meta['name']} scored {eval_report.pct:.1f}% "
        f"(threshold: {QUALITY_THRESHOLD}%)\n"
        f"Failed: {[s.name for s in eval_report.scores if not s.passed]}"
    )


@pytest.mark.parametrize("appid", list(TEST_SUITE_GAMES.keys()))
def test_structural_validity_perfect(runner, appid):
    """Structural checks must always be 100% — no excuses."""
    meta = TEST_SUITE_GAMES[appid]
    reviews = runner.load_reviews(appid)
    report = runner.run_analysis(appid, reviews, meta["name"])
    eval_report = runner.score(report, reviews=reviews)
    structural = [s for s in eval_report.scores if s.category == "structural"]
    failed = [s for s in structural if not s.passed]
    assert not failed, f"Structural failures: {[s.name for s in failed]}"
```

---

## Part 6 — `pytest.ini` / `pyproject.toml` Markers

Register the custom markers so pytest doesn't warn:

```toml
# In pyproject.toml [tool.pytest.ini_options]
markers = [
    "llm: tests that make real LLM API calls (deselect with -m 'not llm')",
    "slow: tests that take >10 seconds",
]
```

---

## Part 7 — `.gitignore` Updates

Add to `.gitignore`:
```
# Eval pipeline cached fixtures (contain review data, large)
scripts/eval/fixtures/*.json
```

---

## Implementation Order

1. **`scripts/eval/__init__.py`** — empty
2. **`scripts/eval/scorers.py`** — all scorer functions + models (ScoreResult, EvalReport)
3. **`tests/eval/__init__.py`** — empty
4. **`tests/eval/test_scorers.py`** — unit tests (run these first, no LLM needed)
5. **`scripts/eval/runner.py`** — EvalRunner class with caching
6. **`scripts/eval/reporter.py`** — Rich console output
7. **`scripts/sp.py`** — add `eval` subcommand
8. **`tests/eval/test_eval_suite.py`** — integration tests
9. **`.gitignore`** + `pyproject.toml` marker registration

### Verification

```bash
# Unit tests pass (no LLM, no DB)
poetry run pytest tests/eval/test_scorers.py -v

# Eval a single game (requires DB with reviews + Bedrock credentials)
poetry run python scripts/sp.py eval 440

# Full suite
poetry run python scripts/sp.py eval --suite

# Integration tests (requires Bedrock credentials)
poetry run pytest tests/eval/test_eval_suite.py -m llm -v --timeout=180
```

---

## Important Conventions

Follow the existing codebase patterns:

- **Imports:** Library-layer code uses `from library_layer.analyzer_models import GameReport`
- **Logging:** Use `logging.getLogger(__name__)` not print statements (except sp.py CLI which uses Rich console)
- **sp.py pattern:** Subcommands use `cmd_xxx()` functions called from the CLI parser. Use `_info()`, `_ok()`, `_warn()`, `_err()` helpers for console output.
- **No external eval frameworks.** Pure Python + pytest + Rich.
- **Scorer purity:** Scorers never do I/O. All data passed as arguments.
- **Cache-first:** Never make an LLM call if a cached result exists.
