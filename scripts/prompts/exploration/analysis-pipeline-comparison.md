# Analysis Pipeline: Current vs. Greenfield Hybrid

**Decision aid.** Companion to `analysis-pipeline-sklearn-hybrid.md`. Should we do this?

## TL;DR

- Cost savings: **~40–50% per game** (~$1.00 → ~$0.50 average)
- Absolute savings on the 141-game wedge: **~$70 per full re-analysis cycle**
- Engineering investment: **~2 weeks** of work, plus an eval harness
- **The cost argument alone is weak in the short term.** The real upside is unlocking embeddings (similarity search, "games like this") and better quality on diverse-topic games. Decide on those, not the cost.

---

## Current pipeline — ~$1.00/game

```
   reviews (≤2000, English-only from Steam)
        │
        ▼
   ┌─────────────────────────┐
   │ Stratified chunking     │   sentiment-balanced
   │   40 × 50 reviews       │   helpful×recency sort
   └────────────┬────────────┘
                │
                ▼
   ┌─────────────────────────┐
   │ PHASE 1 — Haiku × 40    │   ~$0.40
   │ each extracts ≤12       │   prompt cached
   │ TopicSignals            │
   └────────────┬────────────┘
                │
                ▼
   ┌─────────────────────────┐
   │ PHASE 2 — Haiku × 1     │   ~$0.05
   │ dedupes & merges topics │
   └────────────┬────────────┘
                │
                ▼
   ┌─────────────────────────┐
   │ PHASE 3 — Sonnet × 1    │   ~$0.40
   │ → GameReport prose      │
   └────────────┬────────────┘
                ▼
            GameReport
```

**Key properties:**
- 42 LLM calls per game (40 + 1 + 1)
- All reviews seen by an LLM at least once
- Random chunking → some chunks are 50 reviews about the same topic; redundant work
- Cost scales linearly with review count up to the 2000 cap

---

## Greenfield hybrid — ~$0.50/game (avg)

```
                    reviews (English)
                          │
                          ▼
                ┌─────────────────────┐
                │ Dedup + length floor│   MinHash LSH, ~10–20% drop
                └──────────┬──────────┘
                           │
                  review count?
              ┌────────────┼────────────┐
              ▼            ▼            ▼
            <500       500–5k         >5k
           TIER S      TIER M         TIER L
           $0.25       $0.60          $0.55
              │            │            │
              │            └────┬───────┘
              │                 │
              ▼                 ▼
   ┌─────────────────┐  ┌────────────────────────────┐
   │ Single Haiku    │  │ Embed all (BGE-small, CPU) │  free
   │ (full reviews)  │  └────────────┬───────────────┘
   │ → Sonnet        │               ▼
   └────────┬────────┘  ┌────────────────────────────┐
            │           │ UMAP + HDBSCAN             │  free
            │           │ → 5–20 clusters            │
            │           └────────────┬───────────────┘
            │                        ▼
            │           ┌────────────────────────────┐
            │           │ Sample 50–100 per cluster  │  free
            │           │ centroid+helpful+recent+   │
            │           │ edge mix                   │
            │           └────────────┬───────────────┘
            │                        ▼
            │           ┌────────────────────────────┐
            │           │ Haiku × K (K = 5–20)       │  ~$0.20
            │           │ extract TopicSignals       │
            │           └────────────┬───────────────┘
            │                        ▼
            │           ┌────────────────────────────┐
            │           │ Deterministic merge        │  free
            │           │ cosine-dedup, sum counts   │
            │           └────────────┬───────────────┘
            │                        ▼
            │           ┌────────────────────────────┐
            └─────────► │ Sonnet → GameReport prose  │  ~$0.40
                        └────────────┬───────────────┘
                                     ▼
                                 GameReport
```

**Key properties:**
- 6–22 LLM calls per game (vs. 42 today)
- LLM never sees redundant chunks — each cluster covers a distinct topic
- Embeddings persist → reusable for similarity features later
- Cost stops scaling with review count above ~5k (Tier L caps it)

---

## Side-by-side

| Dimension              | Current                   | Greenfield                       |
|------------------------|---------------------------|----------------------------------|
| Cost / game            | ~$1.00                    | ~$0.50 avg                       |
| LLM calls / game       | 42                        | 6–22                             |
| Cost scales with size? | Yes (linear to 2k cap)    | No (tiered, capped)              |
| Small games            | OK, slight overkill       | **Better** (no chunk-merge loss) |
| Diverse-topic games    | OK                        | **Better** (clusters cover all)  |
| Monoculture games      | OK                        | OK (Tier S falls back)           |
| Quote quality          | LLM-picked                | LLM-picked (same)                |
| Topic categorization   | LLM-judged (9 cats)       | LLM-judged (same)                |
| `mention_count` semantics | Observation count      | Observation count (preserved)    |
| Embeddings persisted?  | No                        | **Yes — unlocks future features**|
| New deps               | —                         | datasketch, umap, hdbscan, onnx  |
| Lambda cold-start      | Fast                      | +30MB ONNX model load            |

---

## Where the savings come from

```
   Current        Greenfield       Notes
  ─────────────  ──────────────   ────────────────────────────
   Phase 1   $0.40    →    $0.20   half the LLM calls
   Phase 2   $0.05    →    $0.00   replaced with sklearn merge
   Phase 3   $0.40    →    $0.40   unchanged (irreducible)
   Filter    $0.00    →    $0.00   ~10% input reduction (free)
                ────         ────
                $0.85         $0.60
```

(Phase 1 cost cut comes from 40 random chunks → ~10 cluster-targeted chunks. Phase 2 elimination comes from clusters being already-separated by embedding distance, so dedup is just cosine similarity.)

---

## What you actually gain

1. **~$0.40/game saved.** Wedge re-analysis: $141 → $85.
2. **Persisted embeddings.** Once reviews are embedded, you get for free:
   - "Games like this" similarity search
   - Per-genre semantic search
   - Duplicate-review detection across the catalog
   - Future ABSA / fine-tuned classifiers without re-embedding
3. **Better quality on M-tier games.** Random chunking can miss minority topics that fall outside the helpful-vote leaders. Clustering ensures every topic gets sampled.
4. **Cost stops scaling with review count.** Big games (>5k reviews, e.g. AAA) get cheaper per game, not more expensive.

## What you risk

1. **Topic recall regression.** Stage 3 LLM only sees 50–100 reviews per cluster, not all 2000. If the cluster sampler misses a thematic outlier, the synthesizer never sees it. *Need eval harness to verify.*
2. **Cluster instability between runs.** HDBSCAN is deterministic for fixed input but sensitive to the embedding model. Locking the model version is essential.
3. **Cold-start latency.** ONNX model load on cold Lambda invocation adds ~1–3s. Probably fine but needs measurement.
4. **Eng opportunity cost.** Two weeks not building user-facing features pre-launch.

---

## Cost vs. effort

```
   Wedge re-analysis savings:    $56  per cycle
   Engineering investment:      ~2 weeks
   Break-even (cost only):      ~10+ re-analysis cycles
                                 OR
                                 catalog expansion to ~830 games
```

**Honest read:** if you'd run the analyzer once on the 141-game wedge and never touch it again, the cost case is zero. The case is only positive if either (a) you re-analyze frequently as new reviews come in (likely — Steam reviews accumulate), or (b) you scale the catalog past the wedge into adjacent genres.

---

## Decision criteria

**Do this if:**
- You expect to re-analyze the catalog monthly+ (cost compounds)
- You want similarity search as a near-term feature
- You're worried about cost when scaling past 500 games
- The wedge hits an audience that wants cross-game comparison

**Skip this if:**
- The wedge is the final scope and re-analysis is rare
- You'd rather spend 2 weeks on user-facing pre-launch work
- The current $1/game is comfortable inside the runway
- No similarity-search feature is on the roadmap

**Do partial (Stage 0 only) if:**
- You want the easy 10–20% cost win without architectural rework
- This is ~1 day of work, not 2 weeks
- It can ship now and the rest can wait

---

## Recommendation

**Don't do the full greenfield yet.** Two reasons:
1. The cost case is real but small in absolute terms relative to engineering time.
2. You don't have an eval harness, and shipping Tier M without one risks silent quality regression.

**Do this instead, in order:**
1. **Ship Stage 0 (dedup + length floor).** ~1 day. Captures 10–20% cost win, zero risk, no architectural change. *This is essentially free money.*
2. **Build a GameReport eval harness** (compare two reports for the same game, measure topic recall and prose quality). ~3 days. *This unblocks any future pipeline change.*
3. **Then revisit.** With the eval harness in place, the Tier M migration becomes safe. Make the call based on whether similarity-search features are on the near-term roadmap.

The full Tier M/L work is a real win, but only when the supporting eval infrastructure exists. Without it, you're betting product quality on uncalibrated cost savings.
