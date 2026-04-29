# frontend-static-asset-retention

Stop frontend deploys from breaking already-rendered HTML pages. Adopt the Vercel / OpenNext convention: hashed `_next/static/*` assets coexist across deploys, HTML is invalidated on deploy, orphaned assets age out via S3 lifecycle.

## Why

Production reproduction (2026-04-29): `https://d1mamturmn55fm.cloudfront.net/games/3205380/omelet-you-cook-3205380` renders unstyled. Image at natural size, no Tailwind, no `<GameHero>` overlays, no nav. Browser 404s on the referenced `/_next/static/chunks/<hash>.css`.

Root cause chain:

1. `frontend/next.config.ts:8` pins Next `BUILD_ID` to the git short SHA, so every deploy ships freshly hashed CSS / JS bundle filenames.
2. `infra/stacks/frontend_stack.py:42` runs `BucketDeployment(..., prune=True)`. CDK uploads the new build's assets and **deletes** every object in the bucket that isn't in the new source set. The previous build's CSS hash is gone.
3. HTML responses from the SSR Lambda set `Cache-Control: s-maxage=31536000`, and `app/games/[appid]/[slug]/page.tsx:359` sets `revalidate = 31536000`. CloudFront keeps prerendered HTML for up to a year.
4. Any HTML cached before the latest deploy still references the now-deleted CSS hash. Visitors get a `200 OK` HTML response with a `404` on its stylesheet, and the page renders raw.

The bug self-heals on pages that get re-rendered by `revalidateTag('game-${appid}')` (crawler / analyzer pushes), which is why most reports look fine and a few don't. Pages that haven't been touched since the last deploy stay broken until something invalidates them.

This is a deploy-pipeline bug, not a frontend bug. The frontend's behavior is correct: hashed assets are immutable, HTML is cached aggressively, ISR refreshes on tag pushes. The pipeline violates the contract by deleting referenced immutable assets.

## Goal

After this prompt:
- Two consecutive frontend deploys never break already-cached HTML.
- A user visiting a page that was prerendered against build N still gets a styled page even after build N+1 has shipped.
- Bucket size stays bounded: orphan assets age out after 30 days, plenty of headroom for a year of weekly deploys.
- The deploy pipeline pushes a CloudFront HTML invalidation at the end so newly visible work goes live promptly instead of waiting for tag-based ISR.

## Scope

**In:**
- Flip `BucketDeployment(prune=True)` to `prune=False` for the frontend bucket.
- Add an HTML-only invalidation step at the end of `scripts/deploy.sh` (re-uses existing `scripts/invalidate-cdn.sh`).
- Test plan covers the failure mode end-to-end on staging.

**Out:**
- *No S3 lifecycle rule.* Age-based expiration would re-introduce the same failure mode whenever the deploy cadence is longer than the retention window (e.g. 30+ days idle then the live build's CSS gets aged out from under the cached HTML). Hashed assets are tiny (single-digit MB per build), so accumulation cost is negligible until the catalog is much larger. A retain-last-N-build-IDs cleanup script is the right long-term hygiene; tracked in `steam-pulse.org` Standalone TODOs for a future prompt.
- No Next.js app code changes.
- No CloudFront cache-policy / behavior changes (`infra/stacks/delivery_stack.py` stays as-is).
- No new bucket, no OAC change. Single-bucket layout from `split-assets-bucket.md` is fine.
- No invalidation of `/_next/static/*`. Hashed assets are content-addressed; invalidation would be wasted spend.
- No commits / pushes / deploys. The user handles staging, committing, pushing, and deploying.

## Changes

### 1. `infra/stacks/frontend_stack.py:37-43`

Flip `prune` to `False` and document why:

```python
s3deploy.BucketDeployment(
    self,
    "AssetsDeployment",
    sources=[s3deploy.Source.asset(_OPEN_NEXT_ASSETS)],
    destination_bucket=frontend_bucket,
    # Hashed _next/static/* assets are content-addressed; old hashes must
    # outlive the deploy that replaces them so HTML cached in CloudFront
    # before this deploy keeps resolving its CSS/JS. Lifecycle rule on the
    # bucket sweeps orphans after 30d.
    prune=False,
)
```

### 2. `scripts/deploy.sh:192-203`

Replace the "this script does NOT invalidate CloudFront" stanza with an actual invalidation. Hand-rolled path list, not `/*`, so `/_next/static/*` stays untouched:

```bash
echo "▶ Step 4/4 — Invalidating HTML paths in CloudFront"
bash scripts/invalidate-cdn.sh --env "$ENV" --paths \
  "/" \
  "/games/*" \
  "/genre/*" \
  "/tag/*" \
  "/developer/*" \
  "/publisher/*" \
  "/reports" \
  "/reports/*" \
  "/about" \
  "/search"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Deploy complete → ${ENV}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next: warm pages with"
echo "  poetry run python scripts/warm_game_pages.py"
```

`scripts/invalidate-cdn.sh` already accepts `--paths`. No changes needed in that script.

### 3. (Optional) Tests / synth check

Per project convention, no unit tests for operator scripts. CDK synth output is the verification surface.

## Files Modified

| File | Change |
|------|--------|
| `infra/stacks/frontend_stack.py` | `prune=False` on `BucketDeployment` + comment explaining why |
| `scripts/deploy.sh` | Add HTML-path invalidation step before the final summary |

## Verification

1. `poetry run cdk synth SteamPulse-Production-Frontend` succeeds and shows `Prune: False` on the asset deployment custom resource.
2. Deploy to staging once, capture the asset hash list:
   ```bash
   aws s3 ls s3://steampulse-frontend-staging/_next/static/chunks/ | awk '{print $4}' | sort > /tmp/hashes-before.txt
   ```
3. Make a trivial frontend change (whitespace edit in `globals.css`), redeploy.
4. Re-list:
   ```bash
   aws s3 ls s3://steampulse-frontend-staging/_next/static/chunks/ | awk '{print $4}' | sort > /tmp/hashes-after.txt
   diff /tmp/hashes-before.txt /tmp/hashes-after.txt
   ```
   `hashes-after.txt` MUST be a strict superset of `hashes-before.txt`. Old hashes still present = fix works.
5. Reproduce the original failure mode on staging (before fix would fail, after fix passes):
   - Visit a staging page that was prerendered before the latest deploy and isn't being touched by the analyzer right now.
   - DevTools → Network → confirm the referenced `/_next/static/chunks/*.css` returns `200`, not `404`.
   - Page renders styled.
6. Confirm the deploy script's invalidation step ran:
   ```bash
   aws cloudfront list-invalidations --distribution-id $(aws ssm get-parameter --name /steampulse/staging/delivery/distribution-id --query 'Parameter.Value' --output text) --max-items 1
   ```
   Most recent invalidation should list the HTML paths from `deploy.sh`.

## What NOT To Do

- Do NOT invalidate `/_next/static/*`. The whole point of content-hashed assets is that they're immutable and don't need invalidation; doing so just burns CloudFront invalidation quota.
- Do NOT remove the BUILD_ID pin in `next.config.ts`. It's load-bearing for OpenNext's ISR cache namespacing; without it, ISR keys collide across deploys.
- Do NOT shorten the HTML `s-maxage`. The fix is to make stale HTML *safe*, not to expire it sooner. Shortening would just multiply origin load without fixing the broken-render symptom on still-cached pages.
- Do NOT delete the `cache/` prefix. OpenNext ISR cache lives there and is namespaced by BUILD_ID; staleness is handled by the namespace, not by deletion.
- Do NOT add an S3 lifecycle rule that expires `_next/static/*` by age. Age-based expiration would re-create the original failure mode on any deploy gap longer than the retention window. The right hygiene is a retain-last-N-build-IDs cleanup script (separate prompt, tracked in `steam-pulse.org`).

## Existing Code Reference

- `frontend/next.config.ts:8` - `gitBuildId()` defines `BUILD_ID`
- `infra/stacks/frontend_stack.py:37-43` - current `BucketDeployment`
- `infra/stacks/delivery_stack.py:74-91` - HTML `CachePolicy` (no change needed; correct as-is)
- `infra/stacks/delivery_stack.py:142-148` - default behavior wires `html_cache_policy` to the SSR origin
- `app/games/[appid]/[slug]/page.tsx:359` - `revalidate = 31536000` (intentional; tag-based invalidation is the real signal)
- `scripts/deploy.sh:192-203` - current "no invalidation" stanza
- `scripts/invalidate-cdn.sh` - existing invalidation helper, supports `--paths`
