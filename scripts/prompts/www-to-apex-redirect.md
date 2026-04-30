# Add www → apex 301 redirect via CloudFront Function

## Problem

Both `https://steampulse.io/<path>` and `https://www.steampulse.io/<path>`
currently serve the same content directly from the same CloudFront
distribution (`infra/stacks/delivery_stack.py:172`). Apex is the canonical
form — `frontend/app/sitemap.ts:9` sets `BASE_URL = "https://steampulse.io"`,
JSON-LD canonicals in `frontend/app/layout.tsx` use the apex, and per-page
`alternates.canonical` on game/publisher/developer pages all use apex.

Without a real 301 from www → apex, link signals split between two URLs
and the canonical hint alone leaks PageRank. Fix it at the CDN edge so the
redirect is fast (no Lambda invocation) and applies regardless of path.

## Approach

Add a **CloudFront Function** (viewer-request event type) that inspects the
`Host` header and 301-redirects any `www.steampulse.io` request to the apex
equivalent. Path and querystring are preserved.

Why a CloudFront Function (not Lambda@Edge, not Next.js middleware):
- Runs at the edge in <1ms; no cold start, no Lambda billing
- Doesn't require the request to reach the origin (Next.js Lambda)
- Already supported in the existing distribution — single CDK construct add

The function attaches to **every behavior** on the distribution (default
behavior + the `/_next/static/*` and `/static/*` path patterns). Otherwise
a request to `https://www.steampulse.io/_next/static/foo.js` would still
serve the static asset directly without redirecting, defeating the purpose.

Single forward path, no flag.

## Files to modify

### 1. `infra/stacks/delivery_stack.py`

Just before the `distribution = cloudfront.Distribution(...)` block (around
the existing CloudFront construction site near L150-176), add:

```python
www_to_apex_fn = cloudfront.Function(
    self,
    "WwwToApexRedirect",
    code=cloudfront.FunctionCode.from_inline(
        """
function handler(event) {
  var request = event.request;
  var host = request.headers.host && request.headers.host.value;
  if (host !== 'www.steampulse.io') {
    return request;
  }
  var qs = '';
  for (var key in request.querystring) {
    qs += (qs ? '&' : '?') + key + '=' + request.querystring[key].value;
  }
  return {
    statusCode: 301,
    statusDescription: 'Moved Permanently',
    headers: {
      location: { value: 'https://steampulse.io' + request.uri + qs }
    }
  };
}
"""
    ),
    runtime=cloudfront.FunctionRuntime.JS_2_0,
)
```

Then attach it to **the default behavior and each additional behavior**.
For each `BehaviorOptions(...)` constructor (default + the two path-pattern
entries at L166-170 for `/_next/static/*` and `/static/*`), add the kwarg:

```python
function_associations=[
    cloudfront.FunctionAssociation(
        function=www_to_apex_fn,
        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
    ),
],
```

Apex hostname `steampulse.io` is hardcoded inside the function body — fine
because the JS runs on this distribution only and the redirect target is
domain-specific. If a future env needs a different apex, the function code
becomes a small Python f-string interpolation against `DOMAIN`.

### 2. (No frontend or DNS changes)

The CloudFront alternate domain names list (`domain_names=[DOMAIN, f"www.{DOMAIN}"]`
at L172) stays as-is — CloudFront still needs to *accept* www requests at
the edge so the Function can run on them and emit the 301. Removing www from
`domain_names` would cause CloudFront to reject www requests with an SSL
error before the Function ever runs.

The Route 53 `WwwRecord` (L196-204) also stays — it points www at
CloudFront so the request reaches the edge in the first place.

## Out of scope

- Apex → www direction (we picked apex as canonical; not flipping it).
- HSTS / strict-transport-security headers. Already covered by Next.js
  config (`frontend/next.config.ts:22-32`) on responses; not affected by
  this change.
- Status-code redirects between trailing-slash variants. Out of scope —
  Next.js handles this at the app layer.

## Verification

1. **CDK diff** — `cd infra && npx cdk diff SteamPulseDeliveryStack`. Should
   show one new `AWS::CloudFront::Function` resource and three function
   association additions on the existing distribution. No distribution
   recreation.
2. **Deploy**, then:
   ```bash
   curl -I https://www.steampulse.io/
   ```
   Expect `HTTP/2 301` with `location: https://steampulse.io/`.
3. **Path preservation**:
   ```bash
   curl -I https://www.steampulse.io/games/440/team-fortress-2
   ```
   Expect 301 with `location: https://steampulse.io/games/440/team-fortress-2`.
4. **Querystring preservation**:
   ```bash
   curl -I 'https://www.steampulse.io/search?q=balatro'
   ```
   Expect 301 with `location: https://steampulse.io/search?q=balatro`.
5. **Apex unchanged**:
   ```bash
   curl -I https://steampulse.io/
   ```
   Expect `HTTP/2 200` (no redirect loop).
6. **Static asset path** (proves the function is attached to non-default
   behaviors):
   ```bash
   curl -I https://www.steampulse.io/_next/static/some-asset.js
   ```
   Expect 301, not 200.
