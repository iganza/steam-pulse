# Greenfield Review Analysis Pipeline (sklearn + LLM hybrid)

> **Status:** exploration. Not committed to ship. Saved here to preserve the design thinking for later evaluation.

## Context

Steam-pulse is **pre-launch and can pivot freely**. The current 3-phase MapReduce pipeline (Haiku chunk → Haiku merge → Sonnet synthesize) costs ~$1/game against a ~$500 wedge budget. Question: *if we were designing this from scratch in 2026, knowing modern NLP tooling (sentence-transformers, HDBSCAN, BERTopic, c-TF-IDF, sklearn), how would we build it?* Don't anchor to what exists.

The answer is **not** "rip out the LLM." A naive embedding-first replacement breaks the product in subtle ways that only show up after you build it. The right design is a **tiered hybrid** that puts each stage on the cheapest tool that preserves the insight depth that *is* the product.

## First principles: what's irreducible LLM work?

The product sells `GameReport` PDFs at $49/$149/$499. The fields that justify that price:

- `dev_priorities[]` — ranked actions with `why_it_matters`, `frequency`, `effort`. Requires reasoning about severity and tradeoffs.
- `audience_profile` (ideal_player, archetypes, not_for) — requires interpreting reviewer behavior, not just topics.
- `gameplay_friction[]` / `design_strengths[]` — categorized themes with the right severity language ("critical/significant/minor") and anti-duplication rules across sections.
- `one_liner` and `genre_context` — natural prose for human readers.
- `competitive_context[]` — named-entity extraction with judgment about relevance.

These are LLM-shaped. The mechanical work the LLM is doing today, that classical ML can do for free or near-free:
- Counting reviews and mentions
- Stratified sampling by sentiment (already half-Python)
- Sentiment polarity (Steam gives us `voted_up` — solved)
- Sentiment trend over time (already Python)
- Hidden gem score (already Python)
- Filtering language / dedup / quality (mechanical)
- Embedding reviews into a similarity space (sklearn/sentence-transformers)
- Clustering similar reviews (HDBSCAN)

The architectural question is *where to draw the line*.

## Why pure embedding-first ("BERTopic-replaces-Phase-1") doesn't work

Plan-agent stress-test surfaced six crippling failure modes:

1. **The 9-category constraint is unsolvable mechanically.** HDBSCAN clusters by semantic similarity. A cluster like "bots ruin matchmaking and netcode is awful" embeds *between* `gameplay_friction` and `technical_issues`. Today's prompt has explicit anti-duplication rules ("Bots ruining the game → gameplay_friction ONLY"). A one-shot LLM-categorize-the-clusters call doesn't have global context to enforce these rules; you'll get duplicate items across categories that the synthesis prompt can't repair.

2. **Granularity loss on diverse-topic games (sims, MMOs, sandboxes).** Today's `mention_count` per topic is **observation count** — one review can mention 8 topics. Cluster size is **review count** — one review belongs to 1 cluster. A passionate reviewer ranting about 6 issues contributes 1 to each topic today; under clustering they contribute 1 to whichever they ranted about most. **Secondary friction will be under-counted by 50–80%.**

3. **Centroid quotes are the *least* quotable.** Most-central means most-average. Today's LLM picks vivid, specific quotes; centrality picks generic ones.

4. **Cluster density ≠ confidence.** A 200-review cluster of "love the art" is high-confidence-positive and product-irrelevant. The LLM implicitly reasons about *actionability* and *severity*. A density score doesn't.

5. **Small games break entirely.** HDBSCAN + UMAP need ~500+ documents to behave. Below that, you get one giant cluster + a noise heap, or 4-review "high-confidence" clusters of random co-occurrence. The wedge includes plenty of <500-review indies.

6. **Monoculture corpora break too.** If everyone says "fun!", c-TF-IDF returns generic keywords and `gameplay_friction[]` goes empty — violating schema `min_length=1`.

Conclusion: full mechanical replacement of Phase 1 trades cost for product quality. **That's the wrong direction for a depth-of-insight product.**

## Greenfield design: tiered hybrid

Route games to one of three pipelines based on review count. Each tier preserves the GameReport schema and quality contract; only the *mechanism* differs.

### Tier S — Small games (<500 English reviews)

**Single LLM pass, no chunking.** Skip clustering entirely — the corpus fits in one Haiku context window with room to spare.

```
reviews → quality+dedup filter → single Haiku call (full review set + extraction prompt)
        → single Sonnet call (synthesis)
```

- Cost: ~$0.20–$0.30/game
- Quality: equivalent to current pipeline; in fact *better* because there's no chunk-then-merge information loss
- Implementation: ~1 day. Mostly deletion of code paths.

### Tier M — Mid-size games (500–5,000 reviews)

**Embedding-assisted sampling, LLM-on-representative-samples.** This is the sweet spot.

```
reviews → quality+dedup filter
        → embed all (sentence-transformers, BAAI/bge-small-en-v1.5, ~33MB, CPU)
        → UMAP+HDBSCAN cluster
        → for each cluster, sample 50–100 representative reviews
            (mix: centroid, helpful-vote-leaders, recent, edge-of-cluster)
        → ONE Haiku call per cluster (extract topics from representative slice
            with current TopicSignal schema)
        → deterministic merge across clusters (sum mention_count, dedup by
            topic-name embedding similarity, reconcile sentiment by
            weighted-majority)
        → Sonnet synthesis
```

Why this preserves quality:
- LLM still does extraction (preserves multi-label `mention_count`, vivid quote picking, 9-category enforcement, confidence judgment)
- Clustering reduces redundant LLM work — no need to extract from 40 random chunks when 8 clusters cover 95% of variance
- Sampling within each cluster keeps the LLM seeing *real* reviews, not centroid summaries
- Merge stays deterministic because clusters are already semantically separated → topic dedup across clusters is a clean similarity threshold

Cost projection:
- Embedding: free (CPU, ~5–10s for 5k reviews)
- Clustering: free
- LLM extraction: ~8–15 Haiku calls × 50–100 reviews ≈ ~$0.20 (vs. ~$0.40 in current pipeline)
- Merge: deterministic, free
- Synthesis: ~$0.40 (unchanged)
- **Total: ~$0.60–$0.65/game, ~35% reduction**

### Tier L — Large games (>5,000 reviews)

Same architecture as Tier M, but with stricter sampling caps (so cost doesn't scale with review count) and an LLM quote re-rank pass to compensate for centroid-quote weakness.

- Stricter `cluster_max_samples_for_llm = 60`
- After per-cluster topic extraction, batched Haiku call: "of these 5 candidate quotes per topic, pick the best 1–2"
- Cost: ~$0.50–$0.60/game (constant, not scaling with review count)

### Stage 0 (all tiers) — Ingest & filter

- **Language filter unnecessary** — fetcher already pulls `language=english` (`fetcher.py:66`, `:117`); eligibility is `review_count_english`.
- **Dedup**: MinHash LSH (`datasketch`), Jaccard threshold 0.85. Drops bot copy-paste / templated meme reviews. Expected 5–15%.
- **Quality floor**: drop reviews with `<5 words AND <1h playtime`. Expected 5–10%.

### Stage 1 (Tiers M, L) — Embedding

- Model: `BAAI/bge-small-en-v1.5` (33MB, 384d, MTEB-strong, fast on CPU). Alternative: `all-MiniLM-L6-v2` (90MB, 384d, classic).
- Persist embeddings to a new `review_embeddings` table (or `pgvector` column on `reviews`) for re-use across re-analysis runs and downstream features (similarity search, "find games like this").
- Lambda layer: bundle ONNX-converted model (~30MB) for cold-start speed.

### Stage 2 (Tiers M, L) — Clustering

- UMAP to 5d (n_neighbors=15, min_dist=0.0)
- HDBSCAN (min_cluster_size = max(15, n_reviews // 100), min_samples=5)
- Re-assign noise points to nearest cluster centroid (HDBSCAN's default discards them)
- Target: 5–20 clusters per game

### Stage 3 (Tiers M, L) — LLM extraction on representative slices

- Per cluster, sample 50–100 reviews:
  - 30% closest to centroid (representative)
  - 30% highest helpful-vote count (signal-rich)
  - 20% most recent (recency-weighted)
  - 20% edge-of-cluster, but NOT noise (boundary signal)
- Existing chunk system prompt + TopicSignal schema, unchanged
- Result: same `RichChunkSummary` shape as today, just with K=cluster-count chunks instead of K=40 random chunks

### Stage 4 (Tiers M, L) — Deterministic merge

Replace LLM merge with:
- Group topics across clusters by topic-name embedding cosine similarity (threshold 0.75)
- Sum `mention_count` per group
- Reconcile `sentiment` by weighted majority (mention_count-weighted)
- Reconcile `confidence` by max
- Pick best quotes by `votes_helpful DESC`, then `playtime DESC`, then **distance-from-centroid in [0.3, 0.6]** (representative but not generic)
- Output: same `MergedSummary` shape

### Stage 5 (all tiers) — Synthesis

Unchanged from today. Sonnet sees a `MergedSummary`, produces `GameReport` prose. This is the irreducible LLM work and where the product's value is encoded.

## Cost model (greenfield vs. current)

Per game:

| Tier | Reviews | Current | Greenfield | Δ |
|---|---|---|---|---|
| S | <500 | $0.50 (small chunks but full pipeline) | $0.25 | -50% |
| M | 500–5,000 | $1.00 | $0.60 | -40% |
| L | >5,000 | $1.20–$1.80 (capped at 2k today) | $0.55 | -55% to -65% |

Catalog impact: with $500 budget, current pipeline covers ~333 games at average $1.50; greenfield covers ~830 games at average $0.60. **~2.5× coverage at the same budget**, with no insight quality loss.

## Quality contract preservation

The greenfield design preserves these critical properties:
- 9-category enforcement (LLM still does extraction)
- Multi-label `mention_count` semantics (LLM extracts from real reviews, not aggregates)
- Vivid quote selection (LLM picks within a curated candidate pool, with optional re-rank in Tier L)
- Confidence judgment (LLM-rated, not density-derived)
- Severity language and anti-duplication rules (synthesis prompt unchanged)
- Steam-canonical sentiment magnitude (`positive_pct`, `voted_up`)
- Python-derived `sentiment_trend` and `hidden_gem_score` (already separated)

What changes:
- **Sampling strategy**: stratified-by-sentiment + helpfulness-recency-sort → embedding-cluster + multi-axis representative sampling
- **Number of LLM extraction calls**: 40 random chunks → 5–20 cluster slices (proportional to topic diversity, not review count)
- **Merge phase**: LLM call → deterministic algorithm
- **Tier-S games**: skip the chunk-then-merge dance entirely

## Open questions and verification

These need empirical answers before committing to greenfield:

1. **Does Stage 3 LLM extraction on cluster slices match the topic recall of the current full-coverage stratified chunking?** Risk: clusters miss long-tail signals that random chunking would have caught.
   - **Verify**: pick 5 games of varying size, run both pipelines, compare topic recall and `dev_priorities[]` content side-by-side.

2. **Does deterministic merge produce the same dedup quality as the LLM merge?** "Matchmaking is slow" + "matchmaking takes too long" — does cosine similarity catch this reliably at threshold 0.75?
   - **Verify**: build a fixture of synthetic chunk summaries with known duplicates; measure precision/recall of the deterministic merge.

3. **Cluster count vs. game type.** Some genres might cluster into 3 broad themes; others into 25 fine ones. Does Stage 3 cost stay bounded?
   - **Verify**: run Stage 1+2 on 30 games across genres; histogram cluster counts.

4. **Cold-start cost in Lambda.** ONNX BGE-small is 33MB; UMAP/HDBSCAN are pure Python. Acceptable?
   - **Verify**: measure cold-start in a one-off Lambda invocation.

5. **Tier-S threshold.** Is <500 the right cutoff? Maybe <300 or <800 better matches HDBSCAN's stability curve.
   - **Verify**: run Stage 2 on 20 games in 200–800 review range; check noise ratio + cluster coherence.

## Migration path

Pre-launch, no production users → no migration constraints. But the new pipeline shouldn't be built in a single jump.

1. **Land Stage 0 first** (dedup + quality filter). Pure cost win, zero risk, ~10–20% reduction. (~1 day)
2. **Build Stage 1** (embedding + persistence). Doesn't change pipeline yet — just produces embeddings as a side-effect. Unlocks future similarity features. (~2 days)
3. **Implement Tier S path** (single-pass LLM for <500-review games). Lowest risk because it's strictly less complex than current pipeline. (~1 day)
4. **Implement Tier M path** with eval harness comparing greenfield vs. current GameReports on a fixed test set. **Don't promote until eval shows quality parity.** (~1 week including eval)
5. **Implement Tier L path** with quote re-rank. (~3 days)

Each stage would be its own ship-able prompt under `scripts/prompts/`. Tier S and Stage 0 can ship immediately and capture most of the value if Tier M evaluation reveals quality regressions we can't fix.

## Critical files

| Path | Role |
|---|---|
| `src/library-layer/library_layer/preprocessing/` (new) | Stage 0 dedup + quality |
| `src/library-layer/library_layer/embeddings/` (new) | Stage 1 embedding wrapper, ONNX runtime |
| `src/library-layer/library_layer/clustering/` (new) | Stage 2 UMAP+HDBSCAN |
| `src/library-layer/library_layer/sampling/` (new) | Stage 3 representative sampling |
| `src/library-layer/library_layer/analyzer.py` | Tier router; orchestration; current monolith gets thinned |
| `src/library-layer/library_layer/utils/chunking.py` | Tier-S helper; Tier-M/L unused |
| `src/library-layer/library_layer/llm/anthropic_*.py` | Unchanged — same backends |
| `src/library-layer/library_layer/schema.py` | Add `review_embeddings` table; report telemetry columns |
| `src/library-layer/library_layer/models/analyzer_models.py` | Unchanged — same TopicSignal/RichChunkSummary/MergedSummary/GameReport |
| `pyproject.toml` (root + library-layer) | `datasketch`, `umap-learn`, `hdbscan`, `onnxruntime` (per `feedback_lock_files.md`, lock both) |

## Recommendation

**Ship the tiered hybrid greenfield**, in the migration order above. Capture Stage 0 and Tier S quickly (low-risk, immediate cost wins), then invest in the Tier M eval harness. Build the eval *before* Tier M, not after — that's the gate that protects product quality.

Skip the pure-mechanical Phase 1 replacement (BERTopic-replaces-LLM-extraction). The 9-category constraint, `mention_count` semantics, quote quality, and confidence calibration all degrade in ways the synthesis prompt can't repair. Cost-cutting that erodes the depth-of-insight is anti-strategy for a $49–$499 PDF product.
