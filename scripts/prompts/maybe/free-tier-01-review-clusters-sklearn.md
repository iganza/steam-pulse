# Free Tier 01 — Sklearn review clusters ("What reviewers emphasize")

## Parent prompt
Decomposed from `scripts/prompts/exploration/unanalyzed-game-free-tier.md` (section "Sklearn-derived qualitative content"). Companion to `analysis-pipeline-sklearn-hybrid.md` which specs a related sklearn stack.

## Context

Today the unanalyzed game page is a stub: header, basic stats, RequestAnalysis CTA. Nothing qualitative. The exploration doc's central technical claim is that we can give every game (analyzed or not) a substantive "What reviewers emphasize" section **without per-game LLM cost** by combining:

1. Sentence-transformer embeddings of reviews
2. HDBSCAN clustering per game (≥50 reviews)
3. One-time per-genre LLM-generated cluster taxonomy
4. Centroid-distance matching of clusters → taxonomy items

This prompt builds that pipeline. The output is a new `game_review_clusters` table populated for every catalog game with enough reviews. The frontend rendering of these clusters lives in `free-tier-02-rich-unanalyzed-page.md`.

This is the largest single technical lift in the "make pages rich" effort. None of the dependencies are in `pyproject.toml` today (no `sentence-transformers`, no `hdbscan`, no `scikit-learn`). Per memory `feedback_lock_files`, every dep added requires `poetry lock` in both root and `library-layer` packages.

## What to do

### 1. Add Python dependencies

To `pyproject.toml` (root and `src/library-layer/library_layer/pyproject.toml`):

- `sentence-transformers` (latest stable)
- `hdbscan`
- `scikit-learn`
- `umap-learn` (used in companion clustering work)

Re-run `poetry lock` on both packages. Verify Lambda layer build still fits under the 250 MB unzipped quota — if not, sentence-transformers may need its own dedicated layer or a smaller model.

### 2. Embedding pipeline

Use `sentence-transformers/all-MiniLM-L6-v2` (cheap, 384-dim, well-suited to short review text). Embed each review's body once and cache in DB or S3:

- New table `review_embeddings(review_id BIGINT PK, embedding VECTOR(384), embedded_at TIMESTAMPTZ)` — requires `pgvector` extension if not already enabled
- Or, S3 keyed `embeddings/<appid>/<review_id>.npy` if pgvector is heavy lift

Per memory `feedback_crawl_timestamps`, embeddings are internally derived (not external-API-sourced), so `embedded_at` is fine.

Coordinate with `analysis-pipeline-sklearn-hybrid.md` if its Stage 1 also produces these embeddings — share the same table/cache, don't double-spend.

### 3. Per-game clustering

For each game with ≥50 reviews:

- Pull all review embeddings for that appid
- HDBSCAN cluster: `min_cluster_size=10`, `min_samples=5`, default metric (Euclidean on normalized embeddings)
- For each cluster, pick 1–2 representative reviews scored by `centroid_distance × log(1 + helpful_votes)` (closeness × community-validation)
- Persist clusters to a new table:

```sql
CREATE TABLE game_review_clusters (
    appid           INTEGER NOT NULL REFERENCES games(appid),
    cluster_id      INTEGER NOT NULL,
    taxonomy_label  TEXT NOT NULL,
    sentiment_pct   NUMERIC(5,2) NOT NULL,
    member_count    INTEGER NOT NULL,
    rep_review_ids  JSONB NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (appid, cluster_id)
);
```

Below the 50-review floor, fall back to top-helpful reviews only (already shown elsewhere on the page); no clusters row written.

### 4. Per-genre cluster taxonomy (one-time LLM)

For each genre present in the catalog (~50 expected):

- Sample 200–400 reviews across high-review games in the genre
- Cluster as above; extract the top 7–10 cluster centroids
- Send centroid-near review samples to Claude Haiku with a prompt asking for short, human-readable cluster labels (e.g. "Visual design", "Difficulty curve", "Run length", "Boss design", "Music", "Story", "Replayability")
- Store the result:

```sql
CREATE TABLE genre_cluster_taxonomy (
    genre          TEXT NOT NULL,
    label          TEXT NOT NULL,
    centroid       VECTOR(384) NOT NULL,
    sample_quotes  JSONB NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (genre, label)
);
```

Budget cap: ~$1/genre × 50 genres = ~$50 total. Per memory `feedback_llm_cadence_economics`, this is one-time, not scheduled — re-run only when the genre taxonomy is materially stale (annually-ish).

### 5. Match per-game clusters → taxonomy

For each `game_review_clusters` row, compute cosine distance between its centroid and each taxonomy entry for the game's primary genre. Assign the nearest taxonomy label. Store on the cluster row.

### 6. API endpoint

Extend the existing game-report endpoint payload to include cluster results:

```json
{
  "game": {...},
  "report": {...},
  "review_clusters": [
    {
      "label": "Art and visual design",
      "member_count": 892,
      "sentiment_pct": 96,
      "quotes": [
        {"body": "...", "playtime_hours": 47, "helpful_votes": 312},
        {"body": "...", "playtime_hours": 12, "helpful_votes": 88},
        {"body": "...", "playtime_hours": 200, "helpful_votes": 64}
      ]
    }
  ]
}
```

Return all clusters with all representative quotes — no free-vs-paid carving. Frontend rendering decisions (how many to show by default, expand-to-see-more, etc.) belong in `free-tier-02-rich-unanalyzed-page.md`.

### 7. Backfill / scheduling

- One-shot operator script: cluster every game with ≥50 reviews. Memory `feedback_no_script_tests`: no unit tests on operator scripts. Memory `feedback_sp_py_import_side_effects`: don't `from sp import ...` — inline helpers.
- Scheduled (production-only per `feedback_no_staging_schedules`): re-cluster games whose review counts have changed materially since last computation (e.g. >20% delta or >30 days).

## Files to modify / create

| Path | Change |
|------|--------|
| `pyproject.toml` (root + library-layer) | Add deps; re-lock both |
| `src/lambda-functions/migrations/<NNNN>_review_clusters.sql` | New tables + pgvector extension if needed |
| `src/library-layer/library_layer/services/review_clusters.py` | Embedding + HDBSCAN logic |
| `src/library-layer/library_layer/services/genre_taxonomy.py` | One-time taxonomy LLM call |
| `src/library-layer/library_layer/repos/review_clusters_repo.py` | Read/write |
| `src/lambda-functions/lambda_functions/cluster_reviews/handler.py` | Per-game cluster Lambda |
| `scripts/backfill_review_clusters.py` | Operator script for one-shot backfill |
| `scripts/build_genre_taxonomy.py` | Operator script for taxonomy generation |
| `src/lambda-functions/lambda_functions/api/handler.py` | Extend report endpoint |

## Out of scope

- No frontend changes — that's `free-tier-02-rich-unanalyzed-page.md`
- No tier-aware rendering, no locked sections, no `analysis_state` enum, no Stripe wiring, no Decision Pack PDF — packaging decisions are deferred until Phase A is live
- No upgrade of the main analysis pipeline to the sklearn-hybrid model — that's the separate `analysis-pipeline-sklearn-hybrid.md` prompt and may share infrastructure but is a different scope

## Dependencies

- `analysis-pipeline-sklearn-hybrid.md` Stage 1 (if shipped first, share embedding cache; otherwise this prompt establishes the cache)
- pgvector extension on Postgres (if going that route) or S3 bucket (if not)

## Verification

- Backfill script runs end-to-end on the 141-game roguelike-deckbuilder wedge
- Random spot-check 10 games: cluster labels are sensible, quotes are well-chosen, sentiment % matches manual read
- API response on a known wedge game includes a populated `review_clusters` array with 5–10 entries
- `poetry run pytest -v` for cluster service + repo
- Cost ledger: per-game clustering should be $0 in API spend (only the one-time genre taxonomy spends LLM); confirm in CloudWatch
