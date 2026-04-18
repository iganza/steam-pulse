"""Phase-specific LLM prompts.

Phase-1/2/3 (per-game analyzer) prompts live inline in analyzer.py for
historical reasons. Phase-4 (cross-genre synthesizer) owns this package
because its prompt is versioned independently (prompt_version bumps
invalidate the mv_genre_synthesis cache).
"""
