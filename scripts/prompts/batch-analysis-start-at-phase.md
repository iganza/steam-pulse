# Operator lever: `--start-at <phase>` for batch analysis

## Context

A handful of per-game analyses fail because one chunk out of N fails
pydantic validation at the collect phase. The game's other chunks
(e.g. 11 of 12) are already persisted to `chunk_summaries` with a
valid schema. Today the only way forward is to keep re-rolling the
missing chunk until the LLM happens to comply — at ~$0.10 per
re-roll with a non-trivial miss rate, for a single game that's
annoying; across a wedge run it gets expensive.

Example: appid `1184820` (Poker Quest). 11 of 12 chunks persisted
under `chunk-v2.0`. Chunk 0 (50 reviews, hash
`2a1cf5f61f7f50c4`) keeps failing on `topics.N.sentiment =
'neutral'` — the model emits a neutral-valence topic despite the
prompt's explicit omit-instead-of-neutral rule, and our strict
enum rejects it. Every retry resubmits the same 50 reviews to the
backend and gambles on model compliance.

What we actually want here is an **operator lever** — when the
state machine fails at the chunk phase on 1 of 12 chunks, let the
operator advance the game manually, using whatever is already
persisted. The merge phase reads cached chunks via
`chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)`, so 11
chunks is the corpus the merge sees — and the report it produces
honestly reflects the 11-chunk corpus (e.g. ~550 of 561 reviews).

## Scope (this prompt)

Add a `--start-at <phase>` flag to `scripts/trigger_batch_analysis.py`
that, when set to `merge`, causes the per-game state machine to
skip the chunk phase and begin at `PrepareMerge`. Synthesize from
the already-persisted chunks.

**In scope for this prompt:**
- `--start-at chunk` (default; today's behavior)
- `--start-at merge` (skip chunk phase, start at merge L1 prepare)

**Deferred (NOT this prompt):** `--start-at synthesis` — would
require threading `merged_summary_id` through the input, and the
per-game machine has a race-condition comment at
`batch_analysis_stack.py:206-214` explicitly warning against any
"non-deterministic (appid, latest)" lookup for the merge row.
Doing synthesis-start right is its own prompt. For now: enum
restricted to `{chunk, merge}`; raise `argparse.ArgumentTypeError`
if anything else is passed.

## What to do

### 1. `scripts/trigger_batch_analysis.py`

Add:

```python
parser.add_argument(
    "--start-at",
    choices=["chunk", "merge"],
    default="chunk",
    help="Phase to start at. 'merge' skips chunk phase — the "
         "per-game machine reads cached chunks from chunk_summaries "
         "and begins at PrepareMerge. Use when chunks are already "
         "persisted (e.g. a prior run failed on one chunk). Default: chunk.",
)
```

Include `start_at` in the execution input payload:

```python
payload = {
    "appids": args.appids,
    "max_concurrency": args.concurrency,
    "start_at": args.start_at,
}
```

Print `start_at` in the summary line after submission so the
operator sees it echoed back.

### 2. Orchestrator — thread `start_at` through the DistributedMap

In `infra/stacks/batch_analysis_stack.py` at the `RunPerGame` task
inside `fan_out.item_processor` (~line 500-508), change the input
to also carry `start_at` from the orchestrator execution input:

```python
input=sfn.TaskInput.from_object({
    "appid": sfn.JsonPath.number_at("$"),
    "start_at": sfn.JsonPath.string_at("$$.Execution.Input.start_at"),
}),
```

`$$.Execution.Input.start_at` reaches back to the orchestrator's
input payload. The DistributedMap's per-item context (`$`) is the
current appid only.

If the orchestrator is invoked without `start_at` in its input
(e.g. via the matview-scheduled dispatch path at
`batch_analysis_stack.py:424+`), this JSONPath reference will
raise. Guard one of two ways — pick whichever is cleaner in this
codebase:

- **Option A** (preferred): update the dispatch Lambda and any
  other programmatic callers to always include `start_at: "chunk"`
  in their input.
- **Option B**: use `States.JsonToString` + a default in a
  Pass state. Heavier.

### 3. Per-game AnalysisMachine — branch on `start_at`

In `infra/stacks/batch_analysis_stack.py`, the machine is currently
built as:

```python
merge_l1_chain = _merge_level_chain("", 1, merge_needs_l2)
chunk_chain = _phase_chain("chunk", merge_l1_chain)
state_machine = sfn.StateMachine(..., definition_body=sfn.DefinitionBody.from_chainable(chunk_chain), ...)
```

Insert a Choice state as the new entry point BEFORE
`state_machine` is constructed:

```python
start_choice = sfn.Choice(self, "StartAtChoice")
start_choice.when(
    sfn.Condition.string_equals("$.start_at", "merge"),
    merge_l1_chain,
).otherwise(chunk_chain)

state_machine = sfn.StateMachine(
    ...,
    definition_body=sfn.DefinitionBody.from_chainable(start_choice),
    ...
)
```

The merge-start branch requires no other state-machine change —
`_merge_level_chain("")` begins at `PrepareMerge` which calls the
prepare Lambda with `phase="merge"`, and the prepare Lambda
already does `chunk_repo.find_by_appid(appid, CHUNK_PROMPT_VERSION)`
to build the merge batch. It naturally works on 11 chunks or 40
chunks — whatever is there.

### 4. Minimum-chunks floor in `run_merge_phase`

Today `run_merge_phase` in `analyzer.py:1012` raises only for zero
chunks. Anything ≥1 is allowed through. With the new lever,
operators can now start merge against whatever is cached — so we
need a **hard floor** below which cross-chunk synthesis becomes
statistically unreliable.

Pick `5 chunks` (= 250 reviews at the default 50-review chunk
size). Rationale:

- **Statistical cover:** the genre synthesizer's
  `SHARED_SIGNAL_MIN_MENTIONS = 3` means a "recurring signal"
  needs to appear in 60% of chunks at 5-chunk corpora. Below 5,
  any single chunk's opinion dominates — the "cross-chunk merge"
  stops being cross-chunk.
- **Anchored to wedge eligibility:** the wedge restricts games to
  ≥500 reviews, implying ~10 chunks per fully-analyzed game. 5 is
  half that — the obvious "something's broken, don't synthesize"
  line.
- **Doesn't trip the real use case:** 11-of-12 chunks (appid
  `1184820`) and 17-of-18 chunks (typical partial case) pass
  comfortably. 5 only catches pathological states (operator typo,
  stale partial set, future soft-threshold misconfig).

Extend the existing zero-check:

```python
MIN_CHUNKS_FOR_MERGE = 5  # Hard floor below which cross-chunk
                          # signal becomes noise. Anchored to the
                          # wedge's ≥500-review / ~10-chunk implied
                          # minimum.

if len(chunks) < MIN_CHUNKS_FOR_MERGE:
    raise ValueError(
        f"run_merge_phase requires at least {MIN_CHUNKS_FOR_MERGE} "
        f"chunks (got {len(chunks)} for appid={appid}). Below this "
        f"floor, cross-chunk topic synthesis is statistically "
        f"unreliable. If this is a start_at=merge run, verify "
        f"chunk_summaries has the expected rows for this appid."
    )
```

The single guard covers both paths: `--start-at merge` with zero
or too-few cached chunks, AND any future automated soft-threshold
flow that lets chunk phase proceed with partial success. No
separate `start_at=="merge"` branch needed — the floor is
universal.

Constant lives in `analyzer.py` next to `CHUNK_PROMPT_VERSION`
(module-level). Don't promote to `SteamPulseConfig` yet; it's an
invariant, not a tuning knob.

## Verification

1. **Unit + lint locally:**
   ```
   poetry run pytest -v tests/
   poetry run ruff check .
   ```

2. **Dry-run the trigger script:**
   ```
   poetry run python scripts/trigger_batch_analysis.py \
       --env staging --start-at merge --appids 1184820 --dry-run
   ```
   Payload in the "would-send" output should include
   `"start_at": "merge"`.

3. **CDK diff:** `cdk diff --app "python app.py"` for the
   BatchAnalysis stack. Expect: new `StartAtChoice` Choice state +
   modified `RunPerGame` task input. No Lambda code signature
   changes.

4. **Staging smoke test — default path:**
   ```
   poetry run python scripts/trigger_batch_analysis.py \
       --env staging --appids <a staging appid with no reports>
   ```
   (No `--start-at`, so it defaults to `chunk`.) Expect: standard
   chunk → merge → synthesis flow. Existing behavior preserved.

5. **Staging smoke test — merge-start path:**
   - Pick a staging appid that has a FULL set of chunks under
     `chunk-v2.0` but no report (or delete the report to redo it).
   - Run: `--start-at merge --appids <that appid>`.
   - Expected: execution skips chunk, starts at `PrepareMerge`,
     succeeds through merge and synthesis.
   - Check Step Functions execution history — first state entered
     should be `StartAtChoice`, immediate transition to
     `PrepareMerge`.

6. **Staging smoke test — minimum-chunks floor:**
   - Pick (or set up) a staging appid with fewer than 5 chunks in
     `chunk_summaries` (e.g. DELETE all but 3 chunks for a test
     appid).
   - Run: `--start-at merge --appids <that appid>`.
   - Expected: merge prepare fails with a clean ValueError citing
     `MIN_CHUNKS_FOR_MERGE = 5` and the actual chunk count.
     Execution transitions from `PrepareMerge` to `PhaseFailed`
     without submitting a batch request to the backend (no money
     spent).

6. **Production cutover — the actual use case:**
   ```
   poetry run python scripts/trigger_batch_analysis.py \
       --env production --start-at merge --appids 1184820 3205380
   ```
   Expected: both games produce reports using their existing
   cached chunks (11 of 12 for 1184820, 18-of-whatever for 3205380).

## Rollout

- Single deploy. Default `--start-at chunk` preserves all existing
  automated and manual flows.
- The user runs `bash scripts/deploy.sh` — do not deploy from
  Claude.
- After deploy, use the new flag on the two stuck appids per the
  command above.

## Out of scope

- `--start-at synthesis`. Adds complexity around
  `merged_summary_id` plumbing and intersects with the
  race-condition commentary at `batch_analysis_stack.py:204-214`.
  Separate prompt when/if needed.
- Per-topic drop-instead-of-fail (previous proposal). Covered by
  this lever for the current case; revisit only if the chunk-phase
  compliance miss rate becomes a systemic cost issue.
- Soft chunk-failure threshold (`CHUNK_PHASE_MIN_PERSIST_RATIO`)
  inside the chunk collect phase. Still a separate lever — this
  prompt gives operators a manual escape hatch; the soft threshold
  would be an automated policy. Both can coexist later.
- Changing `CHUNK_PROMPT_VERSION` or any model schemas.
