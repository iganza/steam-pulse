# Pin Next.js BUILD_ID to the git SHA

## Context

End-to-end testing of the cache-until-changed loop on production
(post-PR #131) revealed `revalidateTag('game-${appid}', 'max')` is
firing successfully but never busts the active page cache. Inspecting
the OpenNext DynamoDB cache table shows the cause:

```
RPdiRMrqB06CQ84Icwy1R/game-3205380   revalidatedAt = NOW       ← route handler writes here
GujzS3UPMbDI47TKZkc50/game-3205380   revalidatedAt = 1         ← page is served from here
yAIvome-u4NlWI3OEIcTC/game-3205380   revalidatedAt = (earlier) ← orphan from a previous deploy
```

OpenNext prefixes every cache entry and tag in DynamoDB with the
Next.js `BUILD_ID`. Today, each `next build` generates a fresh random
`BUILD_ID`, so consecutive deploys leave orphan namespaces in the
table. `revalidateTag` runs inside the freshly-deployed bundle and
writes the invalidation timestamp to that bundle's namespace — but
viewers may still be served entries from the previous bundle's
namespace until the new build's cache fully warms up. Result: tag
invalidation often misses the cache entry the user is actually seeing,
and the page stays stale.

`CACHE_BUCKET_KEY_PREFIX` (the S3 prefix) already uses the git short
SHA via `f"cache/{self.node.try_get_context('build-id') or 'local'}/"`
in `compute_stack.py`. The Next.js `BUILD_ID` is **not** aligned to
that — it's whatever Next assigns. Aligning the two so a deploy of
unchanged code reuses the same namespace eliminates the orphan-tag
problem and makes `revalidateTag` actually correct.

**Goal**: pin `BUILD_ID` to the git short SHA so every deploy of the
same commit shares a namespace, and every recompile of unchanged
frontend code stays in the same DynamoDB tag space.

**Scope**: one-line addition to `next.config.ts`. No infra changes.

**Non-goal**: garbage-collecting old DynamoDB entries (separate
maintenance task; existing entries age out on the table's normal
lifecycle).

## Best-practice foundation

- **Next.js supports `generateBuildId`** as a config function returning
  the BUILD_ID to use. Setting it deterministically is documented and
  standard for self-hosted deployments where ISR cache stability across
  deploys matters.
  ([docs](https://nextjs.org/docs/app/api-reference/config/next-config-js/generateBuildId))
- **Git short SHA is what `CACHE_BUCKET_KEY_PREFIX` already uses** in
  `compute_stack.py` line ~314 (`self.node.try_get_context('build-id')`),
  set by `scripts/deploy.sh` from `git rev-parse --short HEAD`. Aligning
  Next's BUILD_ID to the same value gives one canonical namespace per
  commit.
- **Fallback for local dev**: if the git command fails (no git, detached
  build, etc.), Next falls back to its own ID. Match the
  CDK fallback pattern (`'local'`) to keep dev synth predictable.
- **OpenNext build picks up `generateBuildId`** via the standard Next
  build pipeline — no special handling needed.

## Design

### `frontend/next.config.ts`

Add a `generateBuildId` config function that returns the git short SHA,
falling back to `'local'`:

```ts
import { execSync } from "node:child_process";
import type { NextConfig } from "next";

function gitBuildId(): string {
  try {
    return execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  } catch {
    return "local";
  }
}

const nextConfig: NextConfig = {
  generateBuildId: gitBuildId,
  // ... existing headers / rewrites / images config unchanged ...
};

export default nextConfig;
```

That's it. `next build` (and `open-next build` downstream) will now
emit a `.next/BUILD_ID` containing the git short SHA, OpenNext will
namespace cache + tag entries under that ID, and `revalidateTag` will
write to the same namespace the page is read from.

### Sanity check after change

After local `npm run build`, `cat frontend/.next/BUILD_ID` should equal
`git rev-parse --short HEAD`. Same after `npm run build:open-next`
inside `frontend/.open-next/server-functions/default/.next/BUILD_ID`
and `frontend/.open-next/revalidation-function/.next/BUILD_ID`.

## Critical files

**Edit:**
- `frontend/next.config.ts` — add `generateBuildId` (and the `execSync`
  import + helper).

**No infra edits.** `CACHE_BUCKET_KEY_PREFIX` already uses the same
SHA, so the S3 prefix and Next BUILD_ID stay in lockstep automatically.

## Verification

**Local**:
```sh
cd frontend
npm run build
cat .next/BUILD_ID                    # should equal `git rev-parse --short HEAD`
npm run build:open-next
cat .open-next/server-functions/default/.next/BUILD_ID
cat .open-next/revalidation-function/.next/BUILD_ID
# all three must match each other and the git SHA
```

**Production** (after deploy):
1. Confirm the `BUILD_ID` baked into the deployed bundle matches the
   commit deployed (CodeSha256 won't reveal it, but page response
   `etag` or `x-deploy` header may, otherwise just trust the build).
2. Re-run the proof loop from the PR #131 verification:
   - Hit `/games/3205380/...` once → MISS, then HIT.
   - Invoke `RevalidateFrontendFn` with synthetic SQS event for 3205380.
   - Hit again → expect `x-nextjs-cache: STALE`, which enqueues a
     re-render to `OpenNextRevalidationQueue`.
   - Tail `/steampulse/production/opennext-revalidation` log group →
     expect one invocation.
   - Hit a third time → `x-nextjs-cache: HIT` with the just-rendered
     content.
3. Inspect DynamoDB: tag entries for `game-3205380` should now share a
   single `<git-short-sha>/game-3205380` namespace. New deploys with
   unchanged frontend code reuse the same key. (Old orphan entries from
   prior deploys remain harmless — they're never read.)

**Rollback**: revert the `generateBuildId` line. Next reverts to
random per-build IDs and the orphan-namespace problem returns.

## Why this works

- `generateBuildId` is read at `next build` time → baked into the
  bundle as a constant.
- OpenNext's cache adapter prefixes all cache reads/writes with that
  BUILD_ID.
- `revalidateTag` runs inside the same bundle, uses the same prefix.
- All three Lambda paths (page render, /api/revalidate route handler,
  OpenNextRevalidationFn) load the same bundle → all use the same
  BUILD_ID at runtime.
- Same code → same BUILD_ID → same namespace → invalidations land on
  the entries readers are actually seeing.

## Out of scope

- Garbage-collecting orphan DynamoDB entries from prior deploys.
- Switching from `revalidateTag` to `revalidatePath` (alternative fix
  but loses the multi-fetch shared-tag semantics).
- CloudFront edge invalidation (separate prompt:
  `scripts/prompts/game-report-cloudfront-invalidation.md`).

## Sources

- [Next.js generateBuildId docs](https://nextjs.org/docs/app/api-reference/config/next-config-js/generateBuildId)
- [OpenNext caching internals](https://opennext.js.org/aws/inner_workings/caching)
- [Next.js revalidateTag](https://nextjs.org/docs/app/api-reference/functions/revalidateTag)
