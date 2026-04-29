# waitlist-confirmation-email-idempotency

Diagnose why production waitlist signups aren't receiving confirmation emails, then add a `confirmation_email_sent_at` timestamp to the `waitlist` table so the email is sent **at most once** per address but can still be re-attempted if a prior send failed.

## Why

Production was tested with a real signup and no confirmation email arrived. The pipeline is fully wired in code (FastAPI → SQS → Email Lambda → Resend), so the failure is either in environment config (Resend domain unverified, SSM param empty) or silent inside the Resend API call.

Separately, the `waitlist` table has no record of whether the confirmation was actually delivered. That means:

- An SQS retry (DLQ policy is 3 retries, 5-min visibility) re-runs the handler and sends a duplicate Resend email.
- If the very first send failed, there's no DB state we can use to drive a re-send when the user re-submits.

Recording a timestamp solves both problems with one column. The atomic conditional UPDATE pattern (set timestamp WHERE email = ? AND timestamp IS NULL) is the lock that prevents double-sends from concurrent Lambda invocations without needing a Redis or per-message dedup table.

## Scope

**In:**
- A diagnostic checklist (read-only AWS CLI commands) to identify the production root cause before any code changes ship.
- Migration adding `confirmation_email_sent_at TIMESTAMPTZ` to the `waitlist` table.
- Two new repo methods (`needs_confirmation`, `claim_confirmation_send`).
- Email Lambda handler change: atomic claim before Resend call, rollback timestamp on Resend failure so SQS retry can re-attempt.
- API handler change: re-enqueue confirmation when an `already_registered` signup has a NULL timestamp (recovers users who signed up while Resend was misconfigured).
- Tests for all four idempotency paths.

**Out:**
- No CDK/infra changes. Email Lambda already has the SSM permissions and SQS event source it needs.
- No new "feedback form" — what looked like one is the existing optional Pro-suggestion field in `WaitlistEmailForm.tsx` success state, which already saves to `waitlist_suggestions` (migration `0056`).
- No DLQ alarm or admin re-send tool (separate prompt if useful).
- No commits/pushes/deploys — the user handles staging, committing, pushing, and deploying.

## Phase 1: Diagnose the missing prod email (no code changes)

These commands are all **read-only** (`aws ssm get-parameter`, `aws logs tail`, `aws sqs get-queue-attributes`, `aws logs/sqs describe-*`/`list-*`) — Claude can run them directly during implementation to determine the production state before touching code. No state is mutated; nothing in this phase needs user pre-approval beyond the standard AWS CLI permission prompt.

Run from a shell with production AWS creds. Stop at the first failure.

```bash
# 1. SSM params populated?
aws ssm get-parameter \
  --name /steampulse/production/api-keys/resend \
  --with-decryption --query 'Parameter.Value' --output text | head -c 4 && echo "..."
# expect "re_..."  (Resend API keys start with re_)

aws ssm get-parameter \
  --name /steampulse/production/messaging/email-queue-url \
  --query 'Parameter.Value' --output text
# expect an https://sqs.<region>.amazonaws.com/... URL

# 2. Did the API Lambda enqueue your test signup?
aws logs tail /aws/lambda/SteamPulse-Production-Compute-ApiFn --since 1d \
  --filter-pattern '"Waitlist confirmation"'

# 3. Did the Email Lambda run? Look for the success log line and any errors.
aws logs tail /aws/lambda/SteamPulse-Production-Compute-EmailFn --since 1d
aws logs tail /aws/lambda/SteamPulse-Production-Compute-EmailFn --since 1d --filter-pattern 'ERROR'

# 4. Anything stuck in DLQ after 3 retries?
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/SteamPulse-Production
aws sqs list-queues --queue-name-prefix SteamPulse-Production
# Then for the *-dlq queue:
aws sqs get-queue-attributes --queue-url <DLQ_URL> --attribute-names ApproximateNumberOfMessages
```

Then check **Resend dashboard** (outside the repo): is `steampulse.io` verified as a sending domain? Most likely root cause — Resend rejects unverified domains with a 4xx that the Email Lambda logs as ERROR but does not crash on (the Lambda's exception handler returns the message to SQS, then it lands on DLQ after 3 tries).

## Changes

### 1. Migration — `src/lambda-functions/migrations/0057_waitlist_confirmation_sent_at.sql` (NEW)

```sql
-- 0057_waitlist_confirmation_sent_at.sql
-- Track when the Resend confirmation email was successfully sent for each waitlist member.
-- NULL = not yet sent (or send failed and was rolled back); non-NULL = delivered to Resend successfully.
ALTER TABLE waitlist
ADD COLUMN confirmation_email_sent_at TIMESTAMPTZ;
```

Per project convention, any record produced by an external API call gets a `*_sent_at` / `*_crawled_at` timestamp for freshness/audit tracking.

### 2. Repository — `src/library-layer/library_layer/repositories/waitlist_repo.py`

Add two methods to `WaitlistRepository`:

```python
def needs_confirmation(self, email: str) -> bool:
    """True if the row exists and confirmation_email_sent_at IS NULL."""
    row = self._fetchone(
        "SELECT 1 FROM waitlist WHERE email = %s AND confirmation_email_sent_at IS NULL",
        (email,),
    )
    return row is not None

def claim_confirmation_send(self, email: str) -> bool:
    """Atomically claim the right to send the confirmation. Returns True if claimed.

    The conditional UPDATE is the lock: only one concurrent caller can flip NULL to NOW().
    Caller MUST send the email after claiming; on failure, call release_confirmation_claim
    so SQS retry can re-attempt.
    """
    with self.conn.cursor() as cur:
        cur.execute(
            """
            UPDATE waitlist
            SET confirmation_email_sent_at = NOW()
            WHERE email = %s AND confirmation_email_sent_at IS NULL
            """,
            (email,),
        )
        claimed = cur.rowcount > 0
    self.conn.commit()
    return claimed

def release_confirmation_claim(self, email: str) -> None:
    """Roll back a claim after a Resend failure so SQS retry can try again."""
    with self.conn.cursor() as cur:
        cur.execute(
            "UPDATE waitlist SET confirmation_email_sent_at = NULL WHERE email = %s",
            (email,),
        )
    self.conn.commit()
```

### 3. Email Lambda handler — `src/lambda-functions/lambda_functions/email/handler.py`

Instantiate a `WaitlistRepository` at module scope (same pattern as the API Lambda at `src/lambda-functions/lambda_functions/api/handler.py:68`). Wrap the existing `_handle_waitlist_confirmation`:

```python
def _handle_waitlist_confirmation(email: str) -> None:
    if not _waitlist_repo.claim_confirmation_send(email):
        logger.info("Waitlist confirmation already sent — skipping", extra={"email": email})
        return
    try:
        _sender.send(
            to=email,
            subject="You're on the SteamPulse waitlist",
            html=(
                "<p>Thanks for your interest in SteamPulse Pro!</p>"
                "<p>We'll let you know as soon as early access opens.</p>"
                "<hr><p><small>SteamPulse, steampulse.io</small></p>"
            ),
            from_addr=_FROM_ADDR,
        )
    except Exception:
        _waitlist_repo.release_confirmation_claim(email)
        raise
    logger.info("Waitlist confirmation sent", extra={"email": email})
```

The outer `handler()` already catches the re-raised exception and adds the message to `batchItemFailures`, so SQS will retry up to maxReceiveCount.

(Replace the em-dash in the existing HTML body — the project ban on em-dashes applies to user-visible copy too.)

### 4. API handler — `src/lambda-functions/lambda_functions/api/handler.py:1008-1037`

Extend `join_waitlist` so a duplicate signup re-enqueues when the prior send never landed:

```python
@app.post("/api/waitlist")
async def join_waitlist(body: WaitlistRequest) -> dict:
    normalized_email = body.email.strip().lower()
    inserted = _waitlist_repo.add(normalized_email)

    should_enqueue = inserted or _waitlist_repo.needs_confirmation(normalized_email)
    if should_enqueue and _email_queue_url:
        msg = WaitlistConfirmationMessage(email=normalized_email)
        try:
            _sqs_client.send_message(QueueUrl=_email_queue_url, MessageBody=msg.model_dump_json())
            logger.info("Waitlist confirmation queued", extra={"email": normalized_email})
        except Exception:
            logger.exception("Failed to enqueue waitlist confirmation", extra={"email": normalized_email})
    elif should_enqueue:
        logger.warning("EMAIL_QUEUE_URL not set, skipping confirmation email", extra={"email": normalized_email})

    return {"status": "registered" if inserted else "already_registered"}
```

UI response shape unchanged.

### 5. Tests — `tests/test_api.py`

Update `_MemWaitlistRepo` (line 82) with the new methods backed by an in-memory dict tracking timestamps. Add cases:

- **First signup → enqueues + handler sends + timestamp set.**
- **Duplicate signup, timestamp set → no re-enqueue, no second send.**
- **Duplicate signup, timestamp NULL (prior failure) → re-enqueues; handler sends once.**
- **Email handler invoked twice for same email (simulated SQS retry) → only one Resend call (second short-circuits at `claim_confirmation_send`).**
- **Resend raises → handler re-raises and timestamp is rolled back to NULL.**

Tests run against `steampulse_test`, never the live dev DB.

## Files modified

| File | Change |
|------|--------|
| `src/lambda-functions/migrations/0057_waitlist_confirmation_sent_at.sql` | New |
| `src/library-layer/library_layer/repositories/waitlist_repo.py` | + `needs_confirmation`, `claim_confirmation_send`, `release_confirmation_claim` |
| `src/lambda-functions/lambda_functions/email/handler.py` | Atomic claim + rollback on Resend error; module-level `WaitlistRepository` |
| `src/lambda-functions/lambda_functions/api/handler.py` | Re-enqueue when `already_registered` AND `needs_confirmation` |
| `tests/test_api.py` | Extend `_MemWaitlistRepo`; add idempotency tests |

## Verification

1. Apply migration locally against `steampulse_test`: `\d waitlist` shows `confirmation_email_sent_at | timestamp with time zone`.
2. `pytest tests/test_api.py -k waitlist -v` — all five cases above pass.
3. **Local end-to-end** (if running the API + an Email Lambda harness with a Resend test key):
   - POST `/api/waitlist` with a fresh email. Row inserted, `confirmation_email_sent_at` set after handler runs, one Resend test call observed.
   - POST again with the same email. Response `already_registered`, no second Resend call.
   - `UPDATE waitlist SET confirmation_email_sent_at = NULL WHERE email = '…'`, POST again. Re-enqueues, sends once.
4. **Production verification (after Phase 1 root cause is fixed and this change is deployed):**
   - Submit your real email to the live form.
   - CloudWatch shows exactly one `Waitlist confirmation sent` log line.
   - `SELECT email, confirmation_email_sent_at FROM waitlist WHERE email = 'you@…'` shows a non-null timestamp.
   - Re-submit and confirm only one email arrives in your inbox.
