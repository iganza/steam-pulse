# waitlist-suggestion-capture

Capture optional Pro-feature suggestions from waitlist signups in the **post-signup success state** of the existing `WaitlistEmailForm`, persist them to a new `waitlist_suggestions` table, and expose a small `POST /api/waitlist/suggestion` endpoint.

## Why

The landing page already gates on a single dominant CTA (the hero waitlist form). Adding a separate "suggest a feature" textarea as its own card on the landing page would compete with that CTA, attract anonymous spam, and require its own anti-abuse layer. Capturing the suggestion **after** someone has converted preserves the single-CTA discipline, restricts input to people who already gave us their email (high signal, low spam pressure), and gives the existing copy "Waitlist members shape priorities" something tangible to point at.

Implementation is also cheap: one new table, one repository, one handler, one extra UI state in the existing form. No new component on the landing page; the `ProPreview` section's third card (`More on the way`) keeps working as a quiet teaser.

## Scope

**In:**
- New DB table `waitlist_suggestions` (migration appended to `library_layer/schema.py`).
- New repository `WaitlistSuggestionRepository`.
- New endpoint `POST /api/waitlist/suggestion`.
- Frontend: extend the success state of `WaitlistEmailForm` to show a one-textarea "What would make Pro most useful for you?" form. After submit (or skip), show the existing thank-you message.
- Tests for the new endpoint (in-memory mock repo, parallel to the existing `test_waitlist_*` cases).

**Out:**
- No category dropdown for v1 (keep optionality minimal; one freeform textarea only). Categories can be a follow-up if signal volume warrants it.
- No standalone "suggest a feature" card on the landing page. `ProPreview` stays as-is (3 cards with the dimmed teaser).
- No moderation UI, no admin export, no email confirmation back to the user. Suggestions land in Postgres for the user to query directly.
- No edits to `ProPreview.tsx`.
- No changes to the `waitlist` table itself (separate table, joined by email).

## Changes

### 1. Schema migration — `src/library-layer/library_layer/schema.py`

Append a new `CREATE TABLE IF NOT EXISTS` statement to the migration list (same idempotent style as the existing `waitlist` table at line 260):

```sql
CREATE TABLE IF NOT EXISTS waitlist_suggestions (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    suggestion  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
)
```

`email` is **not** declared `UNIQUE` and is **not** a foreign key to `waitlist.email`. Rationale: a person may submit more than one suggestion over time, and we don't want a missing waitlist row (e.g. signup race) to reject a suggestion. Soft-coupling by email matches the existing waitlist model.

Add a non-unique index on `email` only if the table grows large enough to need it; not required for v1.

### 2. Repository — `src/library-layer/library_layer/repositories/waitlist_suggestion_repo.py` (NEW)

```python
"""WaitlistSuggestionRepository — pure SQL I/O for the waitlist_suggestions table."""

from library_layer.repositories.base import BaseRepository


class WaitlistSuggestionRepository(BaseRepository):
    """CRUD operations for the waitlist_suggestions table."""

    def add(self, email: str, suggestion: str) -> None:
        """Insert a suggestion. Always inserts; multiple per email allowed."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO waitlist_suggestions (email, suggestion)
                VALUES (%s, %s)
                """,
                (email, suggestion),
            )
        self.conn.commit()

    def count(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS n FROM waitlist_suggestions", ())
        return int(row["n"]) if row else 0
```

Mirror the existing `WaitlistRepository` style (constructor inherits from `BaseRepository`, uses `self.conn`, commits inside the method).

### 3. Handler — `src/lambda-functions/lambda_functions/api/handler.py`

**a) Add the request model** alongside `WaitlistRequest` at the top of the request-models block (around line 83):

```python
class WaitlistSuggestionRequest(BaseModel):
    email: EmailStr
    suggestion: str
```

Add a length validator on `suggestion` using `pydantic.Field(min_length=1, max_length=2000)` to keep payloads bounded. No `Optional` fields.

**b) Wire the repo singleton** alongside `_waitlist_repo` (around line 67):

```python
from library_layer.repositories.waitlist_suggestion_repo import WaitlistSuggestionRepository
_waitlist_suggestion_repo = WaitlistSuggestionRepository(get_conn)
```

**c) Add the endpoint** directly below the existing `POST /api/waitlist` handler (after line 1030):

```python
@app.post("/api/waitlist/suggestion")
async def submit_waitlist_suggestion(body: WaitlistSuggestionRequest) -> dict:
    """Record a freeform Pro-feature suggestion from a waitlist member."""
    normalized_email = body.email.strip().lower()
    suggestion = body.suggestion.strip()
    if not suggestion:
        raise HTTPException(status_code=400, detail={"error": "Suggestion cannot be empty", "code": "empty_suggestion"})
    _waitlist_suggestion_repo.add(normalized_email, suggestion)
    return {"status": "received"}
```

The endpoint **does not** validate that `email` already exists in `waitlist` — soft coupling per the schema decision above. It returns `{"status": "received"}` on success.

### 4. Frontend API helper — `frontend/lib/api.ts`

Add below the existing `joinWaitlist` (around line 398):

```ts
export async function submitWaitlistSuggestion(
  email: string,
  suggestion: string,
): Promise<{ status: "received" }> {
  return apiFetch("/api/waitlist/suggestion", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, suggestion }),
  });
}
```

### 5. Form success state — `frontend/components/home/WaitlistEmailForm.tsx`

Replace the current success state (the block returned when `status === "registered" || "already_registered"`) with a small interstitial form, then transition to the existing thank-you message after submit-or-skip.

Behavior spec:

1. **State machine extension.** Add two new statuses to the existing `Status` union: `"awaiting_suggestion"` (after waitlist signup succeeds, before the user submits or skips a suggestion) and `"thanked"` (final terminal state). On a successful waitlist submit, set `status` to `"awaiting_suggestion"` instead of `"registered"`/`"already_registered"`. Stash the original waitlist status (registered vs already_registered) in a separate `signupStatus` state so the final thank-you message can still reflect it.

2. **`awaiting_suggestion` UI.** Render:
   - A small heading: `Thanks. One quick thing.` (font-mono, teal, small uppercase eyebrow style — match the existing teal section labels).
   - Subtext: `What would make Pro most useful for you? (Optional.)`
   - A `<textarea>` (rows=3, max 2000 chars) with placeholder `e.g. "track sentiment shifts on competitors", "weekly genre digest", ...`
   - Two buttons side-by-side: primary `Send` (teal, same styling as the existing submit button) and a quiet `Skip` text-button (no background, muted color).
   - Re-entrancy guard: same `if (status === "submitting") return` pattern as the existing handler.
   - On `Send` with empty textarea → treat as Skip (no API call).
   - Plausible event on successful suggestion submit: `Waitlist Suggestion`, props `{ length: <chars> }`. Plausible event on Skip: `Waitlist Suggestion Skipped`.

3. **`thanked` UI.** The existing `You're on the list.` / `You're already on the list.` block, gated on `signupStatus`. Subtext stays the same.

4. **Variant carry-through.** Both `hero` and `repeat` variants get the same flow. Use `data-testid="waitlist-suggestion-form-${variant}"` for the suggestion form and keep the existing `waitlist-success-${variant}` testid on the final thank-you state so existing Playwright tests still find it.

5. **No layout shift surprises.** The interstitial form should fit roughly the same vertical footprint as the eventual thank-you message — keep padding tight. The repeat-CTA section in `frontend/app/page.tsx` does not need changes.

### 6. Tests — `tests/test_api.py`

a) Add an `_MemWaitlistSuggestionRepo` mirroring `_MemWaitlistRepo` and inject it in the autouse `reset_api_state` fixture (around line 143).

b) Add three tests parallel to the existing waitlist cases:
   - `test_suggestion_records_payload` — POST a valid `{email, suggestion}` body, expect `{"status": "received"}`, assert the in-memory repo received one row with the trimmed email and trimmed suggestion.
   - `test_suggestion_rejects_empty_text` — POST with `suggestion=""` (or whitespace-only), expect HTTP 400.
   - `test_suggestion_allows_unknown_email` — POST a `suggestion` for an email that was never added to `_waitlist_repo`. Must succeed (soft coupling).

Per `feedback_test_db.md`: tests run against in-memory mocks, so the live `steampulse_test` DB is not touched. No new DB fixture required.

c) No frontend Playwright test required for v1, but if added later, target `data-testid="waitlist-suggestion-form-hero"` and assert that `Send` with text dispatches to the new endpoint and transitions to `waitlist-success-hero`.

## Constraints

- **Pydantic only.** `WaitlistSuggestionRequest` extends `pydantic.BaseModel`, not a dataclass (per `feedback_always_pydantic`).
- **No `| None` fields.** Both `email` and `suggestion` are required strings; do not introduce `Optional` (per `feedback_avoid_none_types`).
- **No feature flags / dual-path shims** (per `feedback_no_pre_launch_flags`). Just ship the new endpoint and the new success-state UI.
- **No staging schedules / EventBridge involvement.** This feature is request-driven, no scheduled jobs (per `feedback_no_staging_schedules`).
- **Comments are one line max** (per `feedback_terse_comments`).
- **No commit / push** — the user handles staging, committing, pushing (per `feedback_no_commit_push`).
- **No deploys** — the user deploys (per `feedback_no_deploy`).
- **No em-dashes** in any user-facing copy (per `feedback_no_em_dashes`).
- **Lock files.** No new third-party dependencies expected. If pydantic version bumps are needed for `EmailStr` re-import, re-run `poetry lock` for every affected package per `feedback_lock_files` — but the existing handler already imports `EmailStr`, so no new deps.
- **Schema migration is additive.** `CREATE TABLE IF NOT EXISTS` only; do not edit or drop the existing `waitlist` table.

## Verification

1. **Backend tests:**
   - `cd src && poetry run pytest tests/test_api.py -k waitlist -x` — all existing waitlist tests pass plus the three new suggestion tests.
2. **Schema apply:**
   - The migration runner picks up the new `CREATE TABLE IF NOT EXISTS waitlist_suggestions` on next boot. Verify in `steampulse_test` (or a scratch DB) that the table exists with the expected columns.
3. **Manual frontend:**
   - `cd frontend && npm run dev`, open `http://localhost:3000/`.
   - Submit the hero waitlist form with a fresh email. Confirm the form transitions to the suggestion-capture interstitial (textarea + Send + Skip), **not** straight to the thank-you message.
   - Type a suggestion, click `Send`. Confirm the thank-you message renders. Verify the row appeared in `waitlist_suggestions` (`SELECT * FROM waitlist_suggestions ORDER BY id DESC LIMIT 1`).
   - Submit a second fresh email, type nothing, click `Skip`. Confirm thank-you renders. Confirm no row was inserted.
   - Submit an already-registered email. Confirm the suggestion interstitial still appears (so already-registered users can still send a suggestion). After submit, the thank-you should show the `You're already on the list.` variant.
   - Repeat from the bottom-of-page repeat CTA — same flow, different testid suffix.
4. **Plausible:**
   - Confirm `Waitlist Suggestion` and `Waitlist Suggestion Skipped` events fire (network panel → `/api/event`).
5. **Build & types:**
   - `cd frontend && npm run build` — succeeds.
   - `cd frontend && npx tsc -p . --noEmit` — no errors.
6. **Negative path:**
   - `curl -X POST http://localhost:8000/api/waitlist/suggestion -H 'Content-Type: application/json' -d '{"email":"x@y.com","suggestion":"   "}'` returns 400.
   - Same `curl` with a 3000-character `suggestion` returns 422 (pydantic length validation).

## Critical files

- `src/library-layer/library_layer/schema.py` (append migration)
- `src/library-layer/library_layer/repositories/waitlist_suggestion_repo.py` (NEW)
- `src/lambda-functions/lambda_functions/api/handler.py` (add model, repo singleton, endpoint)
- `frontend/lib/api.ts` (add `submitWaitlistSuggestion` helper)
- `frontend/components/home/WaitlistEmailForm.tsx` (extend state machine + UI)
- `tests/test_api.py` (add mock repo + three tests)

## Out of scope (intentional)

- Category enum on suggestions (defer until volume justifies; v1 is a single freeform field).
- Standalone `/feedback` route or marketing-page suggestion form.
- Admin moderation UI or CSV export — query Postgres directly for v1.
- Email confirmation back to the suggester (the waitlist confirmation email already covers initial signup).
- Voting / upvoting on suggestions (Canny/Featurebase territory; not now).
- Rate limiting beyond pydantic's `max_length`. Suggestions only land from converted users; spam pressure is structurally low. Revisit if abuse appears.
