# Pause pre-revenue scheduled refreshes

## Context

Site is in soft launch with ~0 traffic. Per `monetization-direction.md` Phases A-D, the next 10 weeks are about distribution (newsletter + audience) before the paid surface ships. During this window, continuously refreshing review and metadata is paying for data freshness that no one is reading.

Operator's current run-cost is ~$60-80/mo. The fixed serving floor (RDS, Lambda, CloudFront, Plausible, DNS) is ~$30-40/mo and stays. The remaining ~$20-35/mo is recurring data-refresh spend that can be paused without affecting the funnel: the homepage, the showcase pages, and the existing Phase 4 RDB synthesis are already correct and don't depend on weekly refreshes.

Reactivation criterion: re-enable everything in Phase E (when 10 founding members are on the books and paid surface ships).

## Scope

Disable scheduled refresh and the inline review-crawl dispatch. Keep all serving infrastructure untouched. No feature flags or dual-path shims; flip directly via CDK `enabled=False` and an env-var kill switch.

### What this prompt changes

1. `infra/stacks/compute_stack.py:1086-1103` — `RefreshMetaRule` (hourly metadata refresh dispatcher). Set `enabled=False`.
2. `infra/stacks/compute_stack.py:1073-1079` — `CatalogRefreshRule` (daily 06:15 UTC catalog full refresh). Set `enabled=False`.
3. Lambda env var `REFRESH_REVIEWS_ENABLED` on `CrawlerFn` (and any other Lambda reading it) — set to `"false"` so the inline review-crawl dispatch from `CrawlService._maybe_dispatch_review_crawl` becomes a no-op.

### What this prompt does NOT change

- `RDS instance` — keep running.
- `ApiFn`, `FrontendFn`, `OpenNextRevalidationFn` — keep, they serve traffic.
- `CrawlerFn` itself — keep deployed; only disable the scheduled rules and the inline dispatch kill switch. Operator-triggered runs still work.
- `SpokeIngestFn` — keep, it ingests on-demand crawls if any are manually triggered.
- `EmailFn` — keep; the SQS event source mapping costs nothing when no messages flow.
- `MatviewTriggerFn` and the matview refresh SFN — already gated on the daily catalog rule firing; once that rule is disabled, the SFN won't be invoked. No additional change needed.
- `AnalysisFn` — keep; serves the on-demand `/api/preview` endpoint. Pre-revenue traffic is ~0 so cost is ~0.
- `BatchAnalysisStack` SFN — manual-trigger-only already; no change. Operator just won't invoke it during this window.
- `messaging_stack.py:266-273` (`Top500RecrawlRule`) — already `enabled=False`. No change.
- CloudFront, S3 buckets, SQS queues — fixed costs, not worth touching.

## Implementation

### 1. Disable the two production schedules in `infra/stacks/compute_stack.py`

For both `RefreshMetaRule` (hourly meta refresh) and `CatalogRefreshRule` (daily catalog refresh), change the `enabled=` argument from `config.is_production` (or whatever it currently is) to `False`.

Confirmation rule: after the edit, `enabled` must be the literal `False`, not a config-driven expression. We want this OFF in production until Phase E.

### 2. Add `REFRESH_REVIEWS_ENABLED=false` to `CrawlerFn` env

Find where `CrawlerFn` (the dispatcher Lambda) sets its environment variables in `compute_stack.py`. Add or update `REFRESH_REVIEWS_ENABLED="false"`. If the env var is already wired to a config value, override it to the literal string `"false"`.

If any other Lambda reads `REFRESH_REVIEWS_ENABLED` (grep the codebase), set the same value there too. This kills the inline `CrawlService._maybe_dispatch_review_crawl` path.

### 3. Verify with `cdk diff`

Run `cdk diff SteamPulse-Production` (or the appropriate stack name) and confirm:
- Two EventBridge rules show `Enabled: false` instead of `true`.
- `CrawlerFn` environment shows `REFRESH_REVIEWS_ENABLED: false`.
- No other resources change.

If the diff includes anything beyond these three items, stop and investigate before deploying. The change should be surgical.

### 4. Operator deploys

Operator runs `cdk deploy SteamPulse-Production`. Claude does not deploy.

### 5. Post-deploy verification

After deploy, confirm in AWS console:
- EventBridge → Rules: `RefreshMetaRule` and `CatalogRefreshRule` show `State: DISABLED`.
- Lambda → `CrawlerFn` → Configuration → Environment variables: `REFRESH_REVIEWS_ENABLED=false`.
- CloudWatch metrics on `CrawlerFn`: invocation count drops to ~0/hour over the next 24 hours (was ~486/hour previously).
- CloudWatch metrics on `SpokeIngestFn`: also drops, since no review-crawl SQS messages are being dispatched.

### 6. Reactivation (Phase E, week 10+)

When Phase D produces 10 founding members and the paid surface is being built:

1. Revert `enabled=False` back to `enabled=config.is_production` for both rules.
2. Remove the `REFRESH_REVIEWS_ENABLED="false"` override from `CrawlerFn` env, or set it to `"true"`.
3. Deploy.
4. First refresh cycle will catch up gradually; metadata staleness will burn down over a few days.

## Expected savings

| Item | Estimated monthly savings |
|---|---|
| Hourly meta refresh dispatch (~486/hr → 0) | $8-12 |
| Daily catalog refresh + matview cascade | $2-4 |
| Inline review crawl dispatch (~402/hr → 0) | $4-8 |
| Matview refresh RDS write IOPS | $1-3 |
| Total | ~$15-27/mo |

Plus: lower Anthropic LLM bill since the Phase 3 chunk + merge work that was implicitly riding on review-crawl-triggered analyzer flows stops firing.

## Anti-patterns to avoid

1. Do not delete the EventBridge rules or remove the dispatchers. We want to flip them back on quickly in Phase E. `enabled=False` is the right granularity.
2. Do not introduce a feature flag or dual-path shim around the inline review dispatch. Per `feedback_no_pre_launch_flags`, just flip the env var and ship the new path forward.
3. Do not pause `RDS`, `ApiFn`, or `FrontendFn`. These serve the funnel and are the fixed-cost floor.
4. Do not touch the `BatchAnalysisStack` infrastructure. It's manual-trigger-only and costs $0 when not invoked. Disabling adds cleanup work for Phase E.
5. Do not commit or deploy from this prompt. The operator handles staging and deployment.

## Verification (acceptance criteria)

- [ ] `cdk diff` shows exactly three changes: two `Enabled: false` flips and one Lambda env var.
- [ ] After operator deploys, AWS console confirms both rules show `DISABLED` and the env var is `false`.
- [ ] CloudWatch shows `CrawlerFn` invocations drop from ~486/hr to ~0/hr within 1 hour of deploy.
- [ ] CloudWatch shows `SpokeIngestFn` invocations drop accordingly.
- [ ] Site at https://steampulse.io continues to serve normally; per-game pages still render; homepage still loads. (Stale data is expected and intentional.)
- [ ] AWS Cost Explorer in 7 days shows daily run-rate dropped by ~$0.50-1.00/day from the baseline.

## Files referenced

- `infra/stacks/compute_stack.py` (`RefreshMetaRule`, `CatalogRefreshRule`, `CrawlerFn` env)
- `infra/stacks/messaging_stack.py` (already-disabled `Top500RecrawlRule`, no change)
- `src/lambda-functions/lambda_functions/crawler/handler.py` (`CrawlService._maybe_dispatch_review_crawl`, reads `REFRESH_REVIEWS_ENABLED`)
- `tiered-refresh-schedule.org` (cadence reference)
- `ARCHITECTURE.org` (component registry)
