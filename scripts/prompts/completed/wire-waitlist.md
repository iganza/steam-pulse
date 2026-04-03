# Wire Waitlist — Email Capture + Resend Confirmation

## Goal

Add a working waitlist to the `/pro` page. When a visitor submits their email:
1. Store it in PostgreSQL (dedup — no duplicates, no error to user)
2. Enqueue a message on SQS — API returns immediately, no waiting for email delivery
3. A dedicated email Lambda reads from the queue and sends the confirmation via Resend
4. Show a success state in the UI

**Why SQS:** The API endpoint must return immediately. Calling Resend synchronously
would block the response until email delivery completes (or fails). Enqueuing decouples
the two concerns — the user gets instant confirmation, and email delivery happens
asynchronously with retries via SQS.

---

## Changes Required

### 1. Migration: `0010_add_waitlist.sql`

File: `src/lambda-functions/migrations/0010_add_waitlist.sql`

```sql
-- depends: 0009_game_velocity_cache

CREATE TABLE IF NOT EXISTS waitlist (
    id          SERIAL PRIMARY KEY,
    email       TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
```

Also update `schema.py`: add the `waitlist` table definition to the `TABLES` tuple
(after `analysis_jobs`), per CLAUDE.md migration rules.

---

### 2. New abstraction: `src/library-layer/library_layer/utils/email.py`

Provider-agnostic email interface. The only Resend import in the codebase lives here.
Swapping providers means writing a new implementation class — no call site changes.

```python
"""Email sending abstraction — provider-agnostic interface."""

from typing import Protocol

from aws_lambda_powertools import Logger

logger = Logger()


class EmailSender(Protocol):
    """Protocol for sending transactional emails."""

    def send(self, *, to: str, subject: str, html: str, from_addr: str) -> None: ...


class ResendEmailSender:
    """EmailSender implementation backed by Resend."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def send(self, *, to: str, subject: str, html: str, from_addr: str) -> None:
        import resend  # type: ignore[import-untyped]

        resend.api_key = self._api_key
        resend.Emails.send({"from": from_addr, "to": [to], "subject": subject, "html": html})


def send_email_safe(sender: EmailSender, *, to: str, subject: str, html: str, from_addr: str) -> None:
    """Fire-and-forget wrapper — logs warning on failure, never raises."""
    try:
        sender.send(to=to, subject=subject, html=html, from_addr=from_addr)
    except Exception as exc:
        logger.warning("Email send failed", extra={"to": to, "subject": subject, "error": str(exc)})
```

---

### 3. `src/library-layer/library_layer/config.py`

Add two fields following existing conventions:

```python
# ── Secrets Manager names (Lambda calls get_secret_value(SecretId=name)) ──
# (alongside DB_SECRET_NAME and STEAM_API_KEY_SECRET_NAME)
RESEND_API_KEY_SECRET_NAME: str

# ── SSM parameter names (resolved at Lambda cold start via get_parameter()) ─
# (alongside existing _PARAM_NAME fields)
EMAIL_QUEUE_PARAM_NAME: str
```

`RESEND_API_KEY_SECRET_NAME` — holds the Secrets Manager secret name; the email Lambda
resolves the actual key at cold start via `get_secret_value(SecretId=name)`, same
pattern as `DB_SECRET_NAME` in `utils/db.py`.

`EMAIL_QUEUE_PARAM_NAME` — holds the SSM parameter path; resolved at cold start via
Powertools `get_parameter()`, same pattern as `APP_CRAWL_QUEUE_PARAM_NAME`.

No defaults — missing config must crash at cold start.

---

### 4. `src/library-layer/library_layer/repositories/waitlist_repo.py` (new file)

Follow the same pattern as `job_repo.py` — extend `BaseRepository`.

```python
"""WaitlistRepository — email capture for the Pro waitlist."""

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

### 5. `infra/stacks/messaging_stack.py`

Add an email queue + DLQ + SSM param for the queue URL.

```python
# ── Email queue ──────────────────────────────────────────────────────────
self.email_dlq = sqs.Queue(
    self,
    "EmailDlq",
    retention_period=cdk.Duration.days(14),
)
self.email_queue = sqs.Queue(
    self,
    "EmailQueue",
    visibility_timeout=cdk.Duration.minutes(2),
    dead_letter_queue=sqs.DeadLetterQueue(
        max_receive_count=3,
        queue=self.email_dlq,
    ),
)
ssm.StringParameter(
    self,
    "EmailQueueUrlParam",
    parameter_name=f"/steampulse/{env}/messaging/email-queue-url",
    string_value=self.email_queue.queue_url,
)
```

Export `self.email_queue` as a property so `compute_stack.py` can wire it as an
event source for the email Lambda.

---

### 6. `src/lambda-functions/lambda_functions/api/handler.py`

The API endpoint saves to DB and enqueues a message. No email sending here.

#### a. Add module-level wiring

```python
import boto3
from aws_lambda_powertools.utilities.parameters import get_parameter
from library_layer.repositories.waitlist_repo import WaitlistRepository

_waitlist_repo = WaitlistRepository(_conn)

# Resolve email queue URL from SSM at cold start (Lambda only).
if _is_lambda:
    _email_queue_url: str = get_parameter(_api_config.EMAIL_QUEUE_PARAM_NAME)
    _sqs_client = boto3.client("sqs")
else:
    _email_queue_url = os.getenv("EMAIL_QUEUE_URL", "")
    _sqs_client = None  # type: ignore[assignment]
```

#### b. Add Pydantic request model

```python
class WaitlistRequest(BaseModel):
    email: str
```

#### c. Add the endpoint

```python
@app.post("/api/waitlist")
def join_waitlist(body: WaitlistRequest) -> dict:
    """Store email on the Pro waitlist and enqueue a confirmation email."""
    email = body.email.strip().lower()

    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=422,
            detail={"error": "Invalid email address", "code": "invalid_email"},
        )

    is_new = _waitlist_repo.insert(email)

    if _sqs_client and _email_queue_url:
        try:
            import json
            _sqs_client.send_message(
                QueueUrl=_email_queue_url,
                MessageBody=json.dumps({"type": "waitlist_confirmation", "email": email}),
            )
        except Exception as exc:
            logger.warning("Failed to enqueue waitlist email", extra={"email": email, "error": str(exc)})

    return {"status": "ok", "new": is_new}
```

Email enqueue failure is logged and swallowed — the record is already saved, and the
user getting a success response is more important than the confirmation email.

Route is plain `def`, not `async def` — psycopg2 and boto3 are both synchronous.

---

### 7. New Lambda: `src/lambda-functions/lambda_functions/email/handler.py`

SQS-triggered Lambda. Reads the queue, resolves the Resend key from Secrets Manager,
sends the email.

```python
"""Email Lambda — SQS-triggered transactional email sender."""

import json

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext
from library_layer.config import SteamPulseConfig
from library_layer.utils.email import ResendEmailSender, send_email_safe

logger = Logger(service="email")
tracer = Tracer(service="email")

_config = SteamPulseConfig()
_sm = boto3.client("secretsmanager")
_resend_api_key: str = json.loads(
    _sm.get_secret_value(SecretId=_config.RESEND_API_KEY_SECRET_NAME)["SecretString"]
)
_email_sender = ResendEmailSender(_resend_api_key)


@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        msg_type: str = body.get("type", "")
        email: str = body.get("email", "")

        if not email:
            logger.warning("Missing email in SQS message", extra={"body": body})
            continue

        match msg_type:
            case "waitlist_confirmation":
                _send_waitlist_confirmation(email)
            case _:
                logger.warning("Unknown message type", extra={"type": msg_type, "email": email})


def _send_waitlist_confirmation(email: str) -> None:
    send_email_safe(
        _email_sender,
        to=email,
        subject="You're on the SteamPulse Pro waitlist",
        html="""
            <p>Hi,</p>
            <p>You're on the list. We'll email you once when <strong>SteamPulse Pro</strong> launches.</p>
            <p>Pro will include: custom prompts, fresher analysis, no ads, and export —
            built for indie developers doing competitive research.</p>
            <p>— The SteamPulse team</p>
            <hr>
            <p><small>You're receiving this because you signed up at steampulse.io.
            If this was a mistake, just ignore it.</small></p>
        """,
        from_addr="SteamPulse <hello@steampulse.io>",
    )
    logger.info("Waitlist confirmation sent", extra={"email": email})
```

Designed for future extension: new email types are added as new `match` cases and
`_send_*` helpers without changing the handler structure.

---

### 8. `infra/stacks/compute_stack.py`

Add the email Lambda with SQS event source, Secrets Manager permission, and SQS
send permission on the API Lambda.

```python
from aws_cdk.aws_lambda_event_sources import SqsEventSource

# Email Lambda
email_fn = PythonFunction(
    self,
    "EmailFn",
    entry="src/lambda-functions",
    index="lambda_functions/email/handler.py",
    handler="handler",
    runtime=lambda_.Runtime.PYTHON_3_12,
    layers=[library_layer],
    timeout=cdk.Duration.seconds(30),
    tracing=lambda_.Tracing.ACTIVE,
    environment=config.to_lambda_env(
        POWERTOOLS_SERVICE_NAME="email",
        POWERTOOLS_METRICS_NAMESPACE="SteamPulse",
    ),
)

# SQS trigger
email_fn.add_event_source(
    SqsEventSource(messaging.email_queue, batch_size=10)
)

# Resolve Resend key from Secrets Manager
email_fn.add_to_role_policy(
    iam.PolicyStatement(
        actions=["secretsmanager:GetSecretValue"],
        resources=[
            f"arn:aws:secretsmanager:{self.region}:{self.account}"
            f":secret:steampulse/*/resend-api-key*"
        ],
    )
)

# API Lambda — grant SQS send permission
api_fn.add_to_role_policy(
    iam.PolicyStatement(
        actions=["sqs:SendMessage"],
        resources=[messaging.email_queue.queue_arn],
    )
)
```

Also publish the email queue URL to SSM (already done in `messaging_stack.py` above).

---

### 9. `.env.staging` and `.env.production`

```bash
RESEND_API_KEY_SECRET_NAME=/steampulse/staging/resend-api-key
EMAIL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/email-queue-url
```

```bash
RESEND_API_KEY_SECRET_NAME=/steampulse/production/resend-api-key
EMAIL_QUEUE_PARAM_NAME=/steampulse/production/messaging/email-queue-url
```

Also add to `.env.example`:

```bash
RESEND_API_KEY_SECRET_NAME=/steampulse/staging/resend-api-key
EMAIL_QUEUE_PARAM_NAME=/steampulse/staging/messaging/email-queue-url
```

For local dev, set `EMAIL_QUEUE_URL` directly in your local `.env` if you want to
test the SQS path. If unset, the enqueue step is skipped silently — the record is
still saved.

---

### 10. `frontend/app/pro/page.tsx`

Make this a Client Component (add `"use client"` at top). Add state and a submit
handler:

```tsx
"use client";

import { useState } from "react";

const [email, setEmail] = useState("");
const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");

function handleSubmit() {
  if (!email || status === "loading") return;
  setStatus("loading");
  fetch("/api/waitlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  })
    .then((res) => setStatus(res.ok ? "success" : "error"))
    .catch(() => setStatus("error"));
}
```

Update the input:

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

Add success/error message below the form, replacing the existing static `No spam...`
message:

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

---

### 11. Tests

Add to `tests/test_api.py`:

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

SQS enqueue is skipped in tests (`_sqs_client` is `None` when not on Lambda) — no
mocking needed. Email sending is in the separate email Lambda.

---

## Verification

```bash
# Apply migration
bash scripts/dev/migrate.sh

# Run tests
poetry run pytest tests/test_api.py -x -q

# CDK synth — confirm EmailFn and EmailQueue appear in template
poetry run cdk synth | grep -i email

# Manual smoke test (local dev)
curl -X POST http://localhost:8000/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'
# → {"status": "ok", "new": true}
```

---

## Files to create / modify

| File                                                            | Action                                                                    |
|-----------------------------------------------------------------|---------------------------------------------------------------------------|
| `src/lambda-functions/migrations/0010_add_waitlist.sql`         | Create — waitlist table                                                   |
| `src/library-layer/library_layer/schema.py`                     | Add waitlist table to `TABLES`                                            |
| `src/library-layer/library_layer/utils/email.py`                | Create — `EmailSender` protocol + `ResendEmailSender` + `send_email_safe` |
| `src/library-layer/library_layer/config.py`                     | Add `RESEND_API_KEY_SECRET_NAME` + `EMAIL_QUEUE_PARAM_NAME`               |
| `src/library-layer/library_layer/repositories/waitlist_repo.py` | Create — `WaitlistRepository`                                             |
| `src/lambda-functions/lambda_functions/api/handler.py`          | Add `WaitlistRequest`, `join_waitlist` endpoint, SQS enqueue              |
| `src/lambda-functions/lambda_functions/email/handler.py`        | Create — SQS-triggered email sender                                       |
| `infra/stacks/messaging_stack.py`                               | Add `email_queue` + DLQ + SSM param                                       |
| `infra/stacks/compute_stack.py`                                 | Add `EmailFn` + SQS event source + IAM grants                             |
| `.env.staging`, `.env.production`, `.env.example`               | Add `RESEND_API_KEY_SECRET_NAME`, `EMAIL_QUEUE_PARAM_NAME`                |
| `frontend/app/pro/page.tsx`                                     | Wire form — add state, submit handler, success/error UI                   |
| `tests/test_api.py`                                             | Add 3 waitlist endpoint tests                                             |
