# SteamPulse — Frontend Architecture

Canonical decisions for the Next.js frontend. When adding new frontend features,
check here first. When making a decision not covered here, add it.

See also: `ARCHITECTURE.org` for backend system architecture, `CLAUDE.md` for
coding conventions.

---

## Pro/Free feature gating

### Decision: React Context + env var (Phase 1), JWT groups (Phase 2)

**Context:** `frontend/lib/pro.tsx` exports `ProContext`, `ProProvider`, and `usePro()`.
`ProProvider` is mounted at the app root in `layout.tsx` and is the single source
of truth for whether the current session has Pro access.

**Phase 1 (current):** `isPro` is read from `NEXT_PUBLIC_PRO_ENABLED` env var in
`layout.tsx`. Set to `true` in dev/staging, `false` (or omit) in production.

**Phase 2 (when auth is added):** Replace the env-var read in `layout.tsx` with a
server-side session lookup from the chosen auth provider. Auth provider is TBD
(Cognito, Auth0, Okta). The swap is one line — `ProContext`, `ProProvider`, and
`usePro()` are permanent and never change.

```typescript
// Phase 1 — current
const isPro = process.env.NEXT_PUBLIC_PRO_ENABLED === "true";

// Phase 2 — after auth provider is chosen
const session = await getSession(); // provider-specific call
const isPro = session?.user?.groups?.includes("pro") ?? false;
```

**Where pro status lives in the auth provider:** Use a **group or role** named
`"pro"`, not a custom user attribute. Groups surface in the JWT automatically and
are easier to manage operationally (add/remove via admin API, no schema changes).

### Component boundary rules

- **Page-level client components** (e.g. `GameReportClient.tsx`, `TrendsClient.tsx`)
  consume pro status via `const isPro = usePro()` and pass it down as a prop.
- **Leaf components** (e.g. `PlaytimeChart.tsx`, `CompetitiveBenchmark.tsx`)
  accept `isPro?: boolean` as a prop. They do NOT import context directly —
  this keeps them testable in isolation without needing a provider wrapper.
- **Do not** read `NEXT_PUBLIC_PRO_ENABLED` directly in any component — only `layout.tsx`.
- **Do not** add `isPro` as a prop to page components — context exists for this.

### Pro gating UI pattern

When `!isPro`, wrap the gated content:

```tsx
<div className="relative">
  <div className={isPro ? "" : "blur-sm pointer-events-none select-none"}>
    {/* gated content */}
  </div>
  {!isPro && (
    <div className="absolute inset-0 flex items-center justify-center">
      <Link href="/pro">Upgrade to Pro →</Link>
    </div>
  )}
</div>
```

See `CompetitiveBenchmark.tsx` and `PlaytimeChart.tsx` for reference implementations.

---

## Component hierarchy

```
layout.tsx (server component)
  └── ProProvider (client, context root)
        ├── Navbar
        └── {page}
              └── *Client.tsx (client component — calls usePro())
                    └── Leaf components (accept isPro as prop)
```

Server components pass data via props. Client components consume context via hooks.

---

## Charting

**Library:** Recharts (`recharts@3.8.0`) — the only charting library. Do not add
Chart.js, Nivo, Victory, D3, or any other charting dependency.

**Rules:**
- All charts use `ResponsiveContainer` for fluid width
- All charts accept a `height?: number` prop (default 300)
- Return `null` (or an empty-state div) if there are fewer than 2 data points
- Custom HTML bars (as in `PlaytimeChart.tsx`) are acceptable for simple
  single-series bar displays; use Recharts for anything time-series, multi-series,
  or interactive

---

## Styling

- **Tailwind CSS** (v4) for all styling
- **shadcn/ui** primitives (`Card`, `Badge`, `Button`, `Dialog`) for structural components
- **Motion** (`motion@12.36.0`) for transitions and animations
- No CSS Modules, no styled-components, no external CSS frameworks

---

## Data fetching and caching

- **Server components** use `fetch()` with `next: { revalidate, tags }` for ISR
- **Client components** use `useEffect` + the API client functions in `frontend/lib/api.ts`
- Parallel fetches use `Promise.allSettled` so one failure does not block others
- Cache tags follow the pattern `game-{appid}`, `genre-{slug}`, `tag-{slug}`

**Revalidation intervals (current):**
| Data type | Revalidate |
|-----------|-----------|
| Game report | 3600s (1h) |
| Genre / tag lists | 86400s (24h) |
| Game catalog lists | 3600s (1h) |
| Trends data | 3600s (1h) |
