# Split the Assets Bucket: Separate Frontend Assets from Pipeline Data

## Problem

`steampulse-assets-{env}` is a single S3 bucket currently used for four different concerns:

1. **Spoke-results pipeline data** — `spoke-results/reviews/*.json.gz` — temporary files written by spoke Lambdas in multiple regions, read by the ingest Lambda, then left in place
2. **OpenNext ISR cache** — `cache/` prefix — used by the Next.js frontend Lambda for ISR
3. **Frontend static assets** — `_next/static/*` and `/static/*` — deployed by CDK `BucketDeployment`, served via CloudFront S3 origin with OAC
4. **DB snapshots/dumps** — `db-snapshots/*`, `db-dumps/*` — produced by the DB loader Lambda

This caused a **production incident**: the CDK `BucketDeployment` custom resource (which has prune=True by default) was deleting live spoke-result files from the bucket during a frontend deploy, because CDK thought it "owned" the entire bucket. The prune is now set to `False` as a stopgap (`infra/stacks/frontend_stack.py`, line 42), but the root fix is to separate the buckets.

## Goal

Create a dedicated `steampulse-frontend-{env}` S3 bucket for frontend-only concerns (static assets + ISR cache). Keep `steampulse-assets-{env}` for pipeline data (spoke-results, db-snapshots, db-dumps).

After the change:
- `steampulse-assets-{env}` — spoke results, db snapshots/dumps only. No CloudFront OAC policy needed on this bucket.
- `steampulse-frontend-{env}` — `_next/static/*`, `/static/*`, `cache/`. CloudFront OAC reads from here. `BucketDeployment` deploys here. `prune=True` is safe here.

## Files to Change

### `infra/stacks/data_stack.py`

- Add a second `s3.Bucket` construct with `bucket_name=f"steampulse-frontend-{env}"`.
- This bucket needs the same CloudFront OAC resource policy (`AllowCloudFrontOac`, `s3:GetObject`, scoped to `AWS:SourceAccount`) that `assets_bucket` currently has — move the policy to `frontend_bucket` and remove it from `assets_bucket`.
- Publish the new bucket name to SSM: `/steampulse/{env}/data/frontend-bucket-name`.
- Keep `steampulse-assets-{env}` as-is (no OAC policy needed, no CloudFront access).
- Expose `self.frontend_bucket` alongside the existing `self.assets_bucket`.

### `infra/stacks/compute_stack.py`

- ComputeStack already looks up `assets_bucket` via `s3.Bucket.from_bucket_name(...)` — add a second `from_bucket_name` lookup for `steampulse-frontend-{env}` → `frontend_bucket` right next to it. Do NOT add a constructor parameter or pass the bucket cross-stack; all bucket references in this repo go through lookup-by-deterministic-name.
- Change `CACHE_BUCKET_NAME` env var on the frontend Lambda to `frontend_bucket.bucket_name`.
- Change `assets_bucket.grant_read_write(frontend_fn)` → `frontend_bucket.grant_read_write(frontend_fn)`.
- Keep `assets_bucket.grant_read_write(crawler_role)` — crawlers still need access to `steampulse-assets-{env}` for spoke-results.
- The DB loader Lambda's S3 permissions at line ~628-629 (`db-snapshots/*`, `db-dumps/*`) should remain on `assets_bucket`.

### `infra/stacks/delivery_stack.py`

- Currently imports `steampulse-assets-{env}` by name and uses it as the CloudFront S3 origin.
- Change the `from_bucket_name` lookup to use `steampulse-frontend-{env}` instead.
- The OAC + `S3BucketOrigin` wiring stays the same — just points at `frontend_bucket`.
- The `self.assets_bucket` field can be removed or renamed to `self.frontend_bucket` for clarity.

### `infra/stacks/frontend_stack.py`

- Currently uses `steampulse-assets-{env}` as the `destination_bucket` in `BucketDeployment`.
- Change it to `steampulse-frontend-{env}`.
- Change `prune=False` (current stopgap) back to `prune=True` — it's now safe because this bucket is only used for frontend assets.

### `infra/application_stage.py`

- Pass `data_stack.frontend_bucket` to `ComputeStack` when constructing it.
- No other wiring changes needed.

## CDK Conventions to Follow

- No physical resource names except for cross-region references. `steampulse-frontend-{env}` IS a cross-region name (delivery stack references it by name cross-stack). The deterministic name is required.
- No env var lookups inside constructs — pass as props.
- `removal_policy=cdk.RemovalPolicy.RETAIN` on the new bucket — frontend assets are rebuildt on every deploy, but don't make it easy to accidentally destroy.
- Tags: `steampulse:service=frontend`, `steampulse:tier=critical`.
- Follow the existing pattern exactly — copy the `assets_bucket` construct and adjust name/tags/policy.

## What NOT to Do

- Do NOT remove `steampulse-assets-{env}`. It's still used by spoke Lambdas, crawlers, db-loader.
- Do NOT change the spoke_stack.py — it already correctly uses `steampulse-assets-{env}` for spoke-results.
- Do NOT add versioning to the frontend bucket — it's not needed for disposable static assets.
- Do NOT change the SSM parameter for `assets-bucket-name` — spokes depend on it.
- Do NOT change how the ingest Lambda reads from `steampulse-assets-{env}`.

## Verification Steps

After implementing:

1. `poetry run cdk synth` — must succeed with no errors.
2. Check the synth output for `SteamPulse-Staging-Data` — should contain two S3 buckets: `steampulse-assets-staging` and `steampulse-frontend-staging`.
3. Check the synth output for `SteamPulse-Staging-Frontend` — `BucketDeployment` should target `steampulse-frontend-staging`, `prune=True`.
4. Check the synth output for `SteamPulse-Staging-Delivery` — CloudFront S3 origin should reference `steampulse-frontend-staging`.
5. Run `poetry run pytest -v` — all tests must pass.
6. Deploy to staging: `bash scripts/deploy.sh --env staging`.
7. Verify the staging frontend loads at the CloudFront URL.
8. Verify that `steampulse-assets-staging/spoke-results/` objects are NOT deleted when re-deploying the frontend.

## Existing Code Reference

Key locations:
- `infra/stacks/data_stack.py` line 144 — current `assets_bucket` definition
- `infra/stacks/data_stack.py` line 159 — CloudFront OAC resource policy (move this to `frontend_bucket`)
- `infra/stacks/compute_stack.py` line 294 — `CACHE_BUCKET_NAME` env var
- `infra/stacks/compute_stack.py` line 303 — `assets_bucket.grant_read_write(frontend_fn)`
- `infra/stacks/delivery_stack.py` line 52 — `from_bucket_name` lookup
- `infra/stacks/frontend_stack.py` line 30 — `from_bucket_name` in `BucketDeployment`
- `infra/stacks/frontend_stack.py` line 41 — `prune=False` stopgap (revert to `True` after fix)
