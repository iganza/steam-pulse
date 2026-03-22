# Wire Waitlist — Email Capture + Resend Confirmation

## Goal

Add a working waitlist to the `/pro` page. When a visitor submits their email:
1. Store it in PostgreSQL (dedup — no duplicates, no error to user)
2. Send a confirmation email via Resend ("You're on the list")
3. Show a success state in the UI

---

## Changes Required

### 1. `src/library-layer/library_layer/schema.py`

Add the waitlist table to `TABLES` and `RESEND_API_KEY` to `SteamPulseConfig`.

#### a. Add to `TABLES` tuple (after `analysis_jobs`):

```python
"""
CREATE TABLE IF NOT EXISTS waitlist (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
)
""",
```

#### b. Add migration (idempotent, append at end of migrations list):

```python
"CREATE TABLE IF NOT EXISTS waitlist (id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW())",
```

---

### 2. `src/library-layer/library_layer/config.py`

Add `RESEND_API_KEY` as a required field (no default — must be set in env files):

```python
# ── Email (required — set in .env.staging / .env.production) ─────────────
RESEND_API_KEY: str
```

---

### 3. `src/library-layer/library_layer/repositories/waitlist_repo.py` (new file)

Follow the same pattern as `job_repo.py` — extend `BaseRepository`.

```python
"""WaitlistRepository — email capture for the Pro waitlist."""

from __future__ import annotations

from library_layer.repositories.base import BaseRepository


class WaitlistRepository(BaseRepository):
    """INSERT/query operations for the waitlist table."""

    def insert(self, email: str) -> bool:
        """Insert email into waitlist. Returns True if new, False if duplicate.

        Uses ON CONFLICT DO NOTHING so a duplicate email is silently ignored —
        the user gets a success response either way (no leaking whether they
        were already on the list).
        """
        cur = self._execute(
            """
            INSERT INTO waitlist (email)
            VALUES (%s)
            ON CONFLICT (email) DO NOTHING
            """,
            (email,),
        )
        self.conn.commit()
        return cur.rowcount == 1  # True = new signup, False = duplicate

    def count(self) -> int:
        """Return total number of waitlist signups."""
        row = self._fetchone("SELECT COUNT(*) AS n FROM waitlist")
        return int(row["n"]) if row else 0
```

---

### 4. `src/lambda-functions/lambda_functions/api/handler.py`

#### a. Add import and wire up `WaitlistRepository` alongside the other repos:

```python
from library_layer.repositories.waitlist_repo import WaitlistRepository

# add with the other module-level repo singletons:
_waitlist_repo = WaitlistRepository(_conn)
```

#### b. Add Pydantic request model:

```python
class WaitlistRequest(BaseModel):
    email: str
```

#### c. Add the endpoint (after the `/api/validate-key` route):

```python
@app.post("/api/waitlist")
async def join_waitlist(body: WaitlistRequest) -> dict:
    """Store email on the Pro waitlist and send a Resend confirmation."""
    email = body.email.strip().lower()

    # Basic format guard — FastAPI/Pydantic doesn't validate email format by default
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=422,
            detail={"error": "Invalid email address", "code": "invalid_email"},
        )

    is_new = _waitlist_repo.insert(email)

    # Always send confirmation — even duplicates get it (they may have lost the first)
    await _send_waitlist_confirmation(email)

    return {"status": "ok", "new": is_new}
```

#### d. Add `_send_waitlist_confirmation()` helper (alongside existing `_send_confirmation_email`):

```python
async def _send_waitlist_confirmation(to_email: str) -> None:
    """Send Pro waitlist confirmation email via Resend. Fire-and-forget."""
    try:
        import resend  # type: ignore[import-untyped]

        from library_layer.config import SteamPulseConfig
        _cfg = SteamPulseConfig()
        resend.api_key = _cfg.RESEND_API_KEY

        resend.Emails.send({
            "from": "SteamPulse <hello@steampulse.io>",
            "to": [to_email],
            "subject": "You're on the SteamPulse Pro waitlist",
            "html": """
                <p>Hi,</p>
                <p>You're on the list. We'll email you once when <strong>SteamPulse Pro</strong> launches.</p>
                <p>Pro will include: custom prompts, fresher analysis, no ads, and export —
                built for indie developers doing competitive research.</p>
                <p>— The SteamPulse team</p>
                <hr>
                <p><small>You're receiving this because you signed up at steampulse.io.
                If this was a mistake, just ignore it.</small></p>
            """,
        })
    except Exception:
        logger.warning("Waitlist confirmation email failed for %s", to_email)
```

---

### 5. `.env.staging` and `.env.production`

Add the Resend API key (get it from resend.com → API Keys):

```bash
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
```

Also add to `.env.example`:

```bash
RESEND_API_KEY=re_your_api_key_here
```

---

### 6. `infra/stacks/compute_stack.py`

Pass `RESEND_API_KEY` as a Lambda environment variable to the web Lambda.
Find the section where web Lambda env vars are defined and add:

```python
"RESEND_API_KEY": config.RESEND_API_KEY,
```

---

### 7. `frontend/app/pro/page.tsx`

Wire the form. The current form has an `<input>` and a `<button>` with no
state or event handlers. Add state and a submit handler.

Make this a Client Component (add `"use client"` at top). Add:

```tsx
"use client";

import { useState } from "react";

// Inside the component:
const [email, setEmail] = useState("");
const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");

async function handleSubmit() {
  if (!email || status === "loading") return;
  setStatus("loading");
  try {
    const res = await fetch("/api/waitlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    setStatus(res.ok ? "success" : "error");
  } catch {
    setStatus("error");
  }
}
```

Update the input to bind `value` and `onChange`:

```tsx
<input
  type="email"
  value={email}
  onChange={(e) => setEmail(e.target.value)}
  onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
  placeholder="your@email.com"
  disabled={status === "loading" || status === "success"}
  className="..." // keep existing className
/>
```

Update the button:

```tsx
<button
  type="button"
  onClick={handleSubmit}
  disabled={status === "loading" || status === "success"}
  className="..." // keep existing className
  style={{ background: "var(--teal)", color: "#0c0c0f" }}
>
  {status === "loading" ? "..." : status === "success" ? "You're in ✓" : "Notify me"}
</button>
```

Add success/error message below the form:

```tsx
{status === "success" && (
  <p className="text-sm text-teal-400 mt-3">
    You're on the list — check your email for confirmation.
  </p>
)}
{status === "error" && (
  <p className="text-sm text-red-400 mt-3">
    Something went wrong. Please try again.
  </p>
)}
```

Replace the existing static message (`No spam...`) with the above conditional block.

---

### 8. Tests

Add to `tests/test_api.py` (follow the existing pattern for route tests):

```python
def test_waitlist_join_new_email(client):
    """POST /api/waitlist stores a new email and returns ok."""
    res = client.post("/api/waitlist", json={"email": "test@example.com"})
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["new"] is True


def test_waitlist_duplicate_email_is_ok(client):
    """Duplicate email returns 200 (not an error) with new=False."""
    client.post("/api/waitlist", json={"email": "dupe@example.com"})
    res = client.post("/api/waitlist", json={"email": "dupe@example.com"})
    assert res.status_code == 200
    assert res.json()["new"] is False


def test_waitlist_invalid_email(client):
    """Malformed email returns 422."""
    res = client.post("/api/waitlist", json={"email": "notanemail"})
    assert res.status_code == 422
```

Note: the Resend call will fail silently in tests (no API key set) — this is
intentional. The endpoint catches all email exceptions and logs a warning.

---

## Verification

```bash
# Tests pass
poetry run pytest tests/test_api.py -x -q

# Manual smoke test (local dev, no Resend needed)
curl -X POST http://localhost:8000/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
# → {"status": "ok", "new": true}

# Duplicate
curl -X POST http://localhost:8000/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
# → {"status": "ok", "new": false}

# Bad email
curl -X POST http://localhost:8000/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email": "bademail"}'
# → 422
```
