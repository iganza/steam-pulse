# Analyze a Steam game

Run a full two-pass LLM analysis on a Steam game by appid.

Usage: /analyze-game <appid>

Steps:
1. Run: `poetry run python steampulse/main.py --appid $ARGUMENTS --max-reviews 500`
2. Check the output JSON matches the current schema in analyzer.py (all fields present: design_strengths, gameplay_friction, player_wishlist, churn_triggers, dev_priorities, competitive_context, genre_context, hidden_gem_score)
3. Report any missing fields or JSON parse errors
4. If successful, show the one_liner and top 3 dev_priorities
