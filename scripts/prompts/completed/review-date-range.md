# Review Date Range Display

Show the time range of reviews used in analysis, so users understand what period
the intelligence covers. Currently the report footer says:

> Analysis based on 2,000 reviews

It should say:

> Analysis based on 2,000 reviews (Mar 2021 – Jan 2025)

---

## The Data Already Exists

The date range is already collected during Phase 1 (chunking) and flows through
the pipeline. No new data collection is needed.

**Where it lives today:**

1. `RichBatchStats` model (`analyzer_models.py:134-135`):
   ```python
   date_range_start: str | None = None  # ISO date
   date_range_end: str | None = None
   ```

2. Phase 1 chunk prompt (`analyzer.py:435`): extracts min/max dates from reviews
   in each chunk and passes them to the LLM as context.

3. `RichChunkSummary.batch_stats` → `MergedSummary.total_stats`: the date range
   propagates through merge. Single-chunk promotions copy `batch_stats` directly.
   Multi-chunk merges should produce merged date ranges (min of starts, max of
   ends).

**Where it stops:** The `GameReport` model (`analyzer_models.py:237-270`) has no
date range fields. The data is available in `MergedSummary.total_stats` at
synthesis time but is never written to the final report.

---

## Changes

### 1. Add fields to `GameReport` (`analyzer_models.py:270`)

```python
review_date_range_start: str | None = None
review_date_range_end: str | None = None
```

Both must default to `None` — existing reports in the DB won't have them, and
`model_validate()` must not reject them.

### 2. Thread data in synthesis (`analyzer.py:1207`)

After the existing defensive overrides (line 1207), extract dates from the merged
summary and assign to the response:

```python
if merged.total_stats:
    response.review_date_range_start = merged.total_stats.date_range_start
    response.review_date_range_end = merged.total_stats.date_range_end
```

The `merged` variable is the `MergedSummary` passed to `run_synthesis_phase()` —
check the function signature to confirm the parameter name.

### 3. Add to TypeScript interface (`frontend/lib/types.ts`)

Add to the `GameReport` interface:

```typescript
review_date_range_start?: string | null;
review_date_range_end?: string | null;
```

### 4. Display in report footer (`GameReportClient.tsx:629-631`)

Current:
```tsx
Analysis based on{" "}
{report.total_reviews_analyzed?.toLocaleString() ?? "—"} reviews
```

New — append the date range when both dates are present:
```tsx
Analysis based on{" "}
{report.total_reviews_analyzed?.toLocaleString() ?? "—"} reviews
{report.review_date_range_start && report.review_date_range_end && (
  <span>
    {" "}({formatMonth(report.review_date_range_start)} –{" "}
    {formatMonth(report.review_date_range_end)})
  </span>
)}
```

Where `formatMonth` is a small inline helper:
```typescript
function formatMonth(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}
```

### 5. Also show in the report header area (`GameReportClient.tsx:211-212`)

The report header already shows `"{total_reviews_analyzed} reviews"`. Consider
appending the date range there too, or just in the footer — whichever reads
cleaner. The footer is more natural since it's the metadata line.

---

## Edge Cases

- **Existing reports**: `review_date_range_start/end` will be `null`. The UI
  shows the count without the range — no visual regression.
- **Single-chunk analysis** (few reviews): date range still makes sense, just
  might be narrow (e.g., "Jan 2024 – Mar 2024").
- **Same month start and end**: Show "Mar 2024" once, not "Mar 2024 – Mar 2024".
- **Missing dates in batch_stats**: If the LLM didn't return dates (shouldn't
  happen but guard), fields stay `null` and the UI omits the range.

---

## Files to Modify

| File | Change |
|---|---|
| `src/library-layer/library_layer/models/analyzer_models.py` | Add 2 fields to `GameReport` |
| `src/library-layer/library_layer/analyzer.py` | Thread `total_stats` dates to response |
| `frontend/lib/types.ts` | Add 2 fields to `GameReport` interface |
| `frontend/app/games/[appid]/[slug]/GameReportClient.tsx` | Display date range in footer |

## Verification

- `poetry run ruff check .` — no lint errors
- `cd frontend && npx tsc --noEmit` — no type errors
- Run `poetry run python scripts/dev/run_phase.py --appid 440 --phase synthesis`
  and check the output JSON for `review_date_range_start/end` fields
- Manual: game page with fresh report → shows date range
- Manual: game page with old report (pre-change) → shows count only, no range
