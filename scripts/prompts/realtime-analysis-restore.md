# Restore Real-Time Analysis — Add Metadata Context

## Background

The batch analysis pipeline (Bedrock Batch Inference) requires AWS account-level
enablement that is pending a support ticket. Until it's resolved, the real-time
Converse API analysis path is the only way to generate reports.

The real-time handler (`analysis/handler.py`) is deployed and functional but is
missing the game metadata context that the batch pipeline passes. Without it, the
LLM cannot produce `store_page_alignment` (Promise Gap) data. This is a ~6-line
change in one file.

---

## Goal

1. Remove the DEPRECATED notice from `analysis/handler.py` — it's the active path.
2. Add metadata context (tags, genres, store description) to the analysis call so
   reports include `store_page_alignment`.

No new files. No CDK changes. No new endpoints.

---

## Codebase Orientation

- **Handler**: `src/lambda-functions/lambda_functions/analysis/handler.py` — the file to modify
- **analyze_reviews()**: `src/library-layer/library_layer/analyzer.py:526` — already accepts `metadata=` parameter
- **build_metadata_context()**: `src/library-layer/library_layer/models/metadata.py:25` — pure function, takes `(game, tags, genres)`
- **TagRepository**: `src/library-layer/library_layer/repositories/tag_repo.py` — has `find_tags_for_game(appid)` and `find_genres_for_game(appid)`
- **Batch equivalent**: `src/lambda-functions/lambda_functions/batch_analysis/prepare_pass2.py:141` — does exactly this already

---

## Changes

### `src/lambda-functions/lambda_functions/analysis/handler.py`

**1. Update docstring** — remove DEPRECATED lines:

```python
"""Lambda handler — LLM analysis for a single game.

Triggered by Step Functions. Input: {"appid": <int>, "game_name": <str>}
Reads reviews from DB, runs two-pass LLM analysis, writes report to DB.
"""
```

**2. Add imports** (after existing imports):

```python
from library_layer.models.metadata import build_metadata_context
from library_layer.repositories.tag_repo import TagRepository
```

**3. Add TagRepository initialization** (after `_report_repo` on line 44):

```python
_tag_repo: TagRepository = TagRepository(_conn)
```

**4. Build metadata context** (after the `temporal = ...` line, before `analyze_reviews`):

```python
    # Build metadata context for store page alignment analysis
    tags = _tag_repo.find_tags_for_game(req.appid)
    genres = _tag_repo.find_genres_for_game(req.appid)
    metadata = build_metadata_context(game, tags, genres)
```

**5. Pass metadata to analyze_reviews** — change line 93 from:

```python
    result = analyze_reviews(reviews_for_llm, name, appid=req.appid, temporal=temporal)
```

to:

```python
    result = analyze_reviews(reviews_for_llm, name, appid=req.appid, temporal=temporal, metadata=metadata)
```

That's it.

---

## Verification

1. `poetry run pytest tests/handlers/ -v` — all tests pass
2. Invoke the Lambda (staging):
   ```bash
   aws lambda invoke --function-name <analysis-fn-name> \
     --payload '{"appid": 440, "game_name": "Team Fortress 2"}' \
     --cli-binary-format raw-in-base64-out \
     /dev/stdout
   ```
3. Check the report in DB — `store_page_alignment` should be non-null for the analyzed game
