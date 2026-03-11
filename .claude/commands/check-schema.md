# Check report schema consistency

Verify that the report schema is consistent across the codebase.

Check that these files all reference the same field names:
1. `steampulse/analyzer.py` — the authoritative schema (source of truth)
2. `steampulse/api.py` — API response serialization
3. `frontend/` — any TypeScript types or API response handlers
4. `steampulse-design.org` — documentation

Report any fields present in analyzer.py but missing in other files, or vice versa.
The canonical field list is: game_name, appid, total_reviews_analyzed, overall_sentiment,
sentiment_score, sentiment_trend, sentiment_trend_note, one_liner, audience_profile,
design_strengths, gameplay_friction, player_wishlist, churn_triggers, dev_priorities,
competitive_context, genre_context, hidden_gem_score
