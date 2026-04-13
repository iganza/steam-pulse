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

When chunks exceed the per-call limit, we need multiple batches at level 1, then merge
those results at level 2, etc. The state machine already has a wait/poll/collect loop
per phase — we can reuse it with a "needs another level" signal:

- `_prepare_merge`: submit level-1 batch (N requests, one per group). Encode
  `(appid, level, group_index, source_chunk_ids_hash)` in each `record_id`.
- `_collect_merge`: collect results, persist each `MergedSummary`. If >1 result remains,
  return `{"skip": false, "needs_next_level": true, "merge_level": 2}` — the state machine
  loops back to prepare merge with the next level's inputs.
- When only 1 result remains, return `{"skip": true, "merged_summary_id": N}` and the
  state machine proceeds to synthesis.

The state machine's existing phase chain can handle this if we add a loop-back condition
in the merge Choice state: if collect returns `needs_next_level=true`, route back to
PrepareMerge instead of forward to synthesis.

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
- Otherwise: compute groups, check per-group cache, submit uncached groups as batch
- Encode `record_id` as `"{appid}-merge-L{level}-G{group_idx}-{leaf_ids_hash}"`
- Store group metadata (source_chunk_ids per group) in the event output so collect can
  reconstruct without re-querying
- Return `{"skip": false, "job_id": "...", "merge_level": 1, "group_meta": [...]}`

### 2. `collect_phase.py` — add `_collect_merge`

New function to collect merge batch results:
- Iterate batch results, parse `record_id` to identify group
- Persist each `MergedSummary` with correct `source_chunk_ids`, `merge_level`, `model_id`
- Record tokens/cost via `batch_exec_repo.mark_completed()`
- If >1 result: return `{"needs_next_level": true, "merge_level": N+1}`
- If 1 result: return `{"merged_summary_id": ID}`
- Fail pipeline on any validation failures (same pattern as chunks)

### 3. `batch_analysis_stack.py` — add merge loop in state machine

The merge phase chain needs a loop-back path:
- After CollectMerge, check if `needs_next_level` is true
- If true: route back to PrepareMerge (which reads the level-N results from DB and
  submits level N+1)
- If false: thread `merged_summary_id` forward to synthesis
- The existing `_phase_chain` pattern doesn't support loops — merge will need a custom
  chain or a small refactor of the phase wiring

### 4. Remove ConverseBackend from prepare_phase

- Remove `_converse_backend` module-level singleton
- Remove `make_converse_backend` import
- The prepare_phase Lambda no longer needs instructor or the realtime LLM path

### 5. `analyzer.py` — extract batch-friendly helpers

`run_merge_phase()` currently owns the full loop + LLM calls. Extract:
- `compute_merge_groups()` — given chunks + max_per_call, return groups with leaf IDs
- `build_merge_request()` already exists — reuse as-is
- Keep `run_merge_phase()` intact for the realtime path (used by `analysis/handler.py`)

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
