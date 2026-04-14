# Move Merge Phase to Batch API

## Context

The batch analysis pipeline has three phases: chunk, merge, synthesis. Chunk and synthesis
use the Anthropic batch API (50% cheaper than realtime). Merge runs inline via
ConverseBackend at full price — it was designed this way when Bedrock was the batch backend
and per-job overhead was high. Now that we're on the Anthropic batch API (fast submission,
no S3 staging), the overhead argument no longer applies. For a 40-chunk game, merge sends
~60K input tokens through Sonnet — at 50% savings that's meaningful per-game and
significant across bulk analysis runs.

## Current Flow

```
PrepareChunk → [batch submit] → poll → CollectChunk
PrepareMerge → [inline ConverseBackend, returns skip=true] → (no poll/collect)
PrepareSynthesis → [batch submit] → poll → CollectSynthesis
```

`_prepare_merge` in `prepare_phase.py` calls `run_merge_phase()` with the ConverseBackend.
This runs the hierarchical merge synchronously inside the Lambda. The state machine sees
`skip=true` and jumps straight to synthesis.

### Hierarchical Merge

`run_merge_phase()` in `analyzer.py` implements tree reduction:
- Groups chunks into batches of `max_chunks_per_merge_call` (default 40)
- Each batch → 1 LLM call → 1 `MergedSummary`
- If multiple batches at a level → recurse to next level
- For most games (≤40 chunks): **1 LLM call total**
- For large games (41-80 chunks): 3 calls (2 at level 1, 1 at level 2)

Each level persists immediately. Source chunk IDs thread transitively through every level
so the cache key is always the exact set of leaf chunks, not an intermediate merge ID.

### Key Invariants

1. `source_chunk_ids` on every merge row = the transitive leaf chunk IDs (sorted `BIGINT[]`)
2. Per-group cache: before each LLM call, check if that exact set of leaf IDs already merged
3. Root `merged_summary_id` is threaded to synthesis via Step Functions state (not DB lookup)
4. `merge_level`, `chunks_merged`, `source_chunk_ids` are Python-computed, never LLM-guessed
5. Single-chunk games get a Python promotion row (no LLM call), `model_id="python-promotion"`

## Approach

For most games (≤40 chunks), merge is a **single LLM request** — identical to synthesis.
We handle it the same way: submit a 1-request batch, poll, collect. The hierarchical
multi-level case (>40 chunks) is rare and can be handled by looping in the state machine.

### Single-Level Case (≤ max_chunks_per_merge_call)

This is the common path. Treat it exactly like synthesis:

- `_prepare_merge`: build the merge `LLMRequest` via `build_merge_request()`, submit as
  a 1-record batch via `AnthropicBatchBackend.prepare()` + `submit()`, return `job_id`
  with `skip=false`
- State machine: wait → poll → collect (existing pattern)
- `_collect_merge`: collect the batch result, persist the `MergedSummary` row with
  source_chunk_ids, return `merged_summary_id` for synthesis

### Multi-Level Case (> max_chunks_per_merge_call)

When chunks exceed the per-call limit, we need multiple groups at level 1, then merge
those results at level 2. The state machine uses two fixed merge level chains (L1 → L2)
with a Choice gate between them:

- `_prepare_merge(merge_level=1)`: submit level-1 batch (N requests, one per group).
  Encode `record_id` as `"{appid}-merge-L{level}-G{group_index}"`.
- `_collect_merge`: collect results, persist each `MergedSummary`. Return
  `{"merged_summary_id": ID, "merged_ids": [ID]}` when 1 result, or
  `{"merged_summary_id": null, "merged_ids": [id1, id2, ...]}` when multiple remain.
- After L1 (skip or collect), a `MergeNeedsL2?` Choice checks
  `$.merge.merged_summary_id`: if non-null → synthesis; if null → L2.
- `_prepare_merge(merge_level=2)`: reads `merged_ids` from L1, loads intermediates by
  row ID, groups and submits.

Two levels covers up to 1600 chunks (40²), which exceeds any realistic game.

### Single-Chunk Short-Circuit

When there's only 1 chunk, no LLM call is needed — Python promotion creates a
`MergedSummary` from the single chunk. This stays inline in `_prepare_merge` (no batch
submission) and returns `skip=true` with `merged_summary_id`. No change from current
behavior.

### Cache Checks

Cache lookups stay in `_prepare_merge` (runs inline before batch submission):
- Whole-set cache: if all chunks already merged at current prompt version, skip entirely
- Per-group cache: if a group's leaf IDs already merged, exclude from batch submission
- If all groups cached at a level, skip the batch and proceed to next level or return root

## Changes

### 1. `prepare_phase.py` — rewrite `_prepare_merge`

Replace inline ConverseBackend call with batch submission:
- Load chunk summaries + IDs from DB (unchanged)
- Single-chunk: Python promotion, return `skip=true` (unchanged)
- Whole-set cached: return `skip=true` with cached `merged_summary_id` (unchanged)
- Otherwise: compute groups via `compute_merge_groups()`, check per-group cache, submit
  uncached groups as batch
- Encode `record_id` as `"{appid}-merge-L{level}-G{group_idx}"`
- Store group metadata (source_chunk_ids per group) in the event output so collect can
  reconstruct without re-querying
- Return `{"skip": false, "job_id": "...", "merge_level": 1, "group_meta": [...],
  "cached_group_meta": [...]}`

### 2. `collect_phase.py` — add `_collect_merge`

New function to collect merge batch results:
- Iterate batch results, parse `record_id` to identify group
- Validate `level` from record_id matches `merge_level` from the event
- Persist each `MergedSummary` with correct `source_chunk_ids`, `merge_level`, `model_id`
- Record tokens/cost via `batch_exec_repo.mark_completed()`
- Build `merged_ids` sorted by group_index (deterministic ordering for cache consistency)
- Merge freshly persisted IDs with cached group IDs from prepare
- If 1 total result: return `{"merged_summary_id": ID, "merged_ids": [ID]}`
- If >1 results: return `{"merged_summary_id": null, "merged_ids": [...]}`
- Fail pipeline on any validation failures (same pattern as chunks)

### 3. `batch_analysis_stack.py` — two-level merge chain

Replace `_phase_chain("merge", synthesis_chain)` with:
- `_merge_level_chain("", 1, merge_needs_l2)` — level 1
- `MergeNeedsL2?` Choice: `is_not_null($.merge.merged_summary_id)` → synthesis, else → L2
- `_merge_level_chain("L2", 2, synthesis_chain)` — level 2
- Both levels share `$.merge` as result_path; collect writes to `$.merge` (not
  `$.merge.collected`) so `merged_summary_id` is always at `$.merge.merged_summary_id`
- Synthesis payload unchanged: still reads `$.merge.merged_summary_id`

### 4. Remove ConverseBackend from prepare_phase

- Remove `_converse_backend` module-level singleton
- Remove `make_converse_backend` import
- The prepare_phase Lambda no longer needs instructor or the realtime LLM path

### 5. `analyzer.py` — extract batch-friendly helpers

`run_merge_phase()` currently owns the full loop + LLM calls. Extract:
- `compute_merge_groups()` — given chunks + source_id_sets + max_per_call, return
  `MergeGroupPlan` with separate `pending` and `cached` lists (no `| None` fields)
- `build_merge_record_id()` / `parse_merge_record_id()` — encode/decode
  `"{appid}-merge-L{level}-G{group_index}"`
- `build_merge_request()` updated to accept explicit `record_id` parameter
- `promote_single_chunk()` and `merged_as_chunk_like()` made public (cross-module use)
- Keep `run_merge_phase()` intact for the realtime path (used by `analysis/handler.py`),
  refactored to call `compute_merge_groups()` internally

## Files Touched

| File | Change |
|------|--------|
| `prepare_phase.py` | Rewrite `_prepare_merge` to submit batch; remove ConverseBackend |
| `collect_phase.py` | Add `_collect_merge` function |
| `batch_analysis_stack.py` | Add merge loop-back in state machine |
| `analyzer.py` | Extract `compute_merge_groups()` helper |

## Verification

1. Run existing analyzer tests — `run_merge_phase` must still work for realtime path
2. CDK synth — state machine definition compiles
3. Deploy to staging, run batch on a game with <40 chunks (single-level merge via batch)
4. Deploy to staging, run batch on a game with >40 chunks (multi-level merge via batch)
5. Verify `batch_executions` table has rows for merge phase with token counts and costs
6. Verify `merged_summaries` rows have correct `source_chunk_ids` and `merge_level`
