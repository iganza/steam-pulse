# Implement Yoyo Database Migrations for SteamPulse

## Goal
Replace the ad-hoc `schema.py` migration approach with [yoyo-migrations](https://ollycope.com/software/yoyo/latest/). Migrations should run automatically as part of the CDK pipeline deployment.

## Current state
- `src/library-layer/library_layer/schema.py` contains `CREATE TABLE IF NOT EXISTS` DDL for all tables plus ad-hoc `ALTER TABLE` migrations appended at the bottom
- `create_all(conn)` runs all statements on every Lambda cold start — wasteful and unordered
- No tracking of which migrations have been applied
- `INDEXES` tuple is separate and run manually

## What to build

### 1. Add yoyo-migrations to dependencies
Add `yoyo-migrations` to `pyproject.toml` (main group, not infra). Run `poetry lock` and `poetry install`.

### 2. Create `migrations/` directory at repo root
Convert `schema.py` into numbered SQL migration files:

```
migrations/
  0001_initial_schema.sql         ← all CREATE TABLE statements from schema.py
  0002_add_review_count_english.sql
  0003_add_review_language_and_votes.sql
  0004_add_deck_compatibility.sql
  0005_add_review_cursor.sql
  0006_add_analytics_indexes.sql  ← the INDEXES tuple
```

Each file must have yoyo `-- depends:` header format:
```sql
-- depends: 0001_initial_schema
```

Group the existing `ALTER TABLE` statements from `schema.py` into logical migrations (by feature, not one-per-line). Use the existing `IF NOT EXISTS` guards — yoyo tracks applied migrations in its own `_yoyo_migration` table, but the guards are still good defensive coding.

### 3. Create `scripts/dev/migrate.sh`
A local dev helper to apply pending migrations:
```bash
#!/usr/bin/env bash
# Apply pending yoyo migrations to local dev DB
# Usage: bash scripts/dev/migrate.sh
# For staging: bash scripts/dev/migrate.sh --stage staging  (tunnel must be open)
set -euo pipefail
# Load DATABASE_URL from .env if not set
# Run: yoyo apply --database "$DATABASE_URL" ./migrations
```

Use `DATABASE_URL` from `.env` for local. For staging use the tunnel URL (same pattern as `push-to-staging.sh` — fetch password from Secrets Manager, use `localhost:5433`).

### 4. Create a `MigrationFn` Lambda in `compute_stack.py`
A lightweight Lambda that runs `yoyo apply` against the RDS database:
- Entry: `src/lambda-functions/lambda_functions/admin/migrate_handler.py`
- Handler reads `DATABASE_URL` from Secrets Manager (same `DB_SECRET_NAME` pattern as other Lambdas)
- Runs: `yoyo apply --database url --no-config-file migrations/` where migrations are bundled into the Lambda package
- Runs in VPC (same private subnets + intra_sg as other Lambdas)
- **No SQS trigger** — invoked directly (Event invoke) from CDK pipeline
- Reserved concurrency: 1 (migrations must never run concurrently)
- `migrations/` directory must be included in the Lambda bundle — add it to the Lambda entry path or copy it alongside the handler

### 5. Wire into CDK Pipeline (`pipeline_stack.py`)
Add a post-deployment `ShellStep` after the staging stage and after the production stage that invokes `MigrationFn`:
```python
post=[
    pipelines.ShellStep("ApplyMigrations",
        commands=[
            "aws lambda invoke --function-name <MigrationFn ARN> "
            "--invocation-type RequestResponse "
            "--log-type Tail /tmp/migrate-out.json",
            "cat /tmp/migrate-out.json",
        ]
    )
]
```
Export the Lambda ARN from `ComputeStack` as a CloudFormation output so the pipeline step can reference it.

### 6. Update `schema.py`
Keep `schema.py` as the **source of truth documentation** (human-readable reference) but remove `create_all()` from Lambda cold start paths. Replace all call sites of `create_all(conn)` with a no-op or a comment: "Schema managed by yoyo migrations — see migrations/".

Do NOT delete `schema.py` — keep it as reference.

### 7. Update `scripts/dev/start-local.sh`
After starting Docker Postgres, automatically run `bash scripts/dev/migrate.sh` to apply pending migrations instead of calling `create_all()` directly.

## Constraints
- No SQLAlchemy — yoyo works directly with psycopg2 connection strings
- Migration files are plain SQL — no Python migration files needed
- `yoyo apply` is idempotent — safe to run on every deploy even if no new migrations
- All existing tests must still pass: `poetry run pytest -v`
- Follow the existing 3-layer pattern — the migration Lambda is a pure handler with no business logic
- CLAUDE.md: no mutable default arguments, type hints on all functions, Python 3.12 syntax

## Connection string format for yoyo with psycopg2
```
postgresql://user:password@host:port/dbname
```
Yoyo accepts standard PostgreSQL connection URLs directly.
