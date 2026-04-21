"""Smoke tests for the /genre/[slug]/ synthesis page's backend surface.

Extends test_genre_insights.py with the page-level population thresholds
(friction >= 10, wishlist >= 10, benchmarks >= 5, dev_priorities >= 3) and
with the pre-order/buy report endpoint. The report endpoint is owned by
`stripe-checkout-report-delivery.md` and may not be deployed yet — any of
200, 404, 405, or 501 is accepted, since the page renders gracefully with
`report === null`.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.smoke

RDB_SLUG = "roguelike-deckbuilder"


def test_rdb_insights_meets_page_thresholds(api: httpx.Client) -> None:
    """If RDB synthesis is seeded, its counts meet the page's structural
    expectations. If unseeded (404), skip — the page falls back to 404 too.
    """
    r = api.get(f"/api/tags/{RDB_SLUG}/insights")
    if r.status_code == 404:
        pytest.skip("Roguelike-deckbuilder synthesis not seeded against this target")
    assert r.status_code == 200, r.text

    body = r.json()
    assert body["slug"] == RDB_SLUG
    assert body["display_name"]
    assert body["input_count"] >= 1
    assert body["narrative_summary"].strip(), "narrative_summary must be non-empty"

    s = body["synthesis"]
    assert len(s["friction_points"]) >= 10, (
        f"page expects at least 10 friction points, got {len(s['friction_points'])}"
    )
    assert len(s["wishlist_items"]) >= 10, (
        f"page expects at least 10 wishlist items, got {len(s['wishlist_items'])}"
    )
    assert len(s["benchmark_games"]) >= 5, (
        f"page expects at least 5 benchmark games, got {len(s['benchmark_games'])}"
    )
    assert len(s["dev_priorities"]) >= 3, (
        f"page expects at least 3 dev priorities, got {len(s['dev_priorities'])}"
    )

    # Nested shape sanity — each friction carries the fields the blockquote
    # renders. Catching a missing field here beats debugging a prod render.
    first = s["friction_points"][0]
    assert {"title", "description", "representative_quote", "source_appid", "mention_count"} <= set(first)

    assert s["churn_insight"]["primary_reason"].strip()
    assert s["churn_insight"]["typical_dropout_hour"] >= 0


def test_rdb_report_endpoint_responds_or_is_absent(api: httpx.Client) -> None:
    """GET /api/genres/{slug}/report is owned by the Stripe prompt. The
    genre page tolerates any of:
      - 200 (row exists → block renders, pre-order or live)
      - 404 (route exists, no reports row → block hidden)
      - 501 or 405 (route not implemented yet → block hidden)
    """
    r = api.get(f"/api/genres/{RDB_SLUG}/report")
    assert r.status_code in (200, 404, 405, 501), (
        f"unexpected status {r.status_code} for report endpoint: {r.text[:200]}"
    )
    if r.status_code == 200:
        body = r.json()
        assert body["slug"]
        assert body["display_name"]
        assert isinstance(body["tiers"], list) and len(body["tiers"]) >= 1
        assert "published_at" in body
        assert isinstance(body["is_pre_order"], bool)
