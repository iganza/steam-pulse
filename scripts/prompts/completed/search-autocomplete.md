# Search Autocomplete (Typeahead) Prompt

## Goal

Add a typeahead/combobox dropdown to the search input in the Navbar so users
see up to 6 game suggestions as they type, with keyboard navigation and
accessible markup. This is the single search input used site-wide — no new
endpoints needed.

---

## Existing setup

- **Navbar**: `frontend/components/layout/Navbar.tsx`
  - Has a desktop search `<input>` and a mobile search `<input>` (separate
    markup but same `query` state and `handleSearch` submit handler)
  - On submit, navigates to `/search?q=...`
- **API**: `GET /api/games?q={term}&limit=6&sort=review_count`
  - Returns `{ games: [{ appid, name, slug, header_image, overall_sentiment,
    sentiment_score, review_count, short_desc }], total }` — no new endpoint needed
- **Types**: `frontend/lib/types.ts` has `GameSummary` interface
- **API client**: `frontend/lib/api.ts` has `getGames(params)` — use it

---

## What to build

### 1. `SearchAutocomplete` component

Create `frontend/components/layout/SearchAutocomplete.tsx`.

**Behaviour:**
- Debounce input by **300ms** before firing the API call
- Fire `GET /api/games?q={term}&limit=6` when `term.length >= 2`
- Clear suggestions when input is empty or term < 2 chars
- Show a loading spinner (small, inline) while fetching
- Show dropdown with up to 6 results
- Keyboard navigation: `↑`/`↓` move highlight, `Enter` navigates to the
  highlighted game (or submits search if none highlighted), `Escape` closes
- Click on a suggestion navigates to `/games/{appid}/{slug}`
- Close dropdown on outside click (use `useRef` + `mousedown` listener)
- Close dropdown on route change (use `usePathname` from `next/navigation`)
- On mobile the behaviour is identical — same component, same keyboard nav

**Each suggestion row shows:**
- Game thumbnail (`header_image`, 40×40 cropped, use Next.js `<Image>` with
  `sizes="40px"` — these are small capsule images from Steam CDN)
- Game name (truncate with `text-ellipsis overflow-hidden whitespace-nowrap`)
- Sentiment badge — a small coloured dot + label (Overwhelmingly Positive /
  Mostly Positive / Mixed / etc.) using the same colour mapping already used
  in `GameReportClient.tsx`
- Review count in muted text (`1.2k reviews`)

**Footer row** (always shown when dropdown is open):
  `See all results for "{term}" →` — clicking navigates to `/search?q={term}`

**Accessibility (WCAG 2.1 AA):**
- `role="combobox"` on the input wrapper
- `aria-expanded`, `aria-activedescendant`, `aria-autocomplete="list"` on the
  input
- `role="listbox"` on the dropdown, `role="option"` on each row
- `aria-selected` on the highlighted option

### 2. Replace the two inputs in Navbar

Replace both the desktop and mobile plain `<input>` elements in `Navbar.tsx`
with the new `<SearchAutocomplete>` component. It should accept:
- `value` / `onChange` — controlled from Navbar's existing `query` state
- `onSubmit` — the existing `handleSearch` function
- `className` — for layout/width styling

Keep the existing `handleSearch` (push to `/search?q=...`) as the form submit
path. The autocomplete is additive — it doesn't replace the submit behaviour.

### 3. Styling

Match the existing card/border design system (`var(--card)`, `var(--border)`,
`var(--foreground)`, `var(--teal)`).

- Dropdown: rounded-xl, `shadow-lg`, `z-50`, positioned absolutely below the
  input with a small gap (4px)
- Highlighted row: `var(--card)` background slightly lighter / use
  `bg-accent` or `background: var(--border)`
- Suggestion rows: `p-3`, `flex items-center gap-3`, `cursor-pointer`
- Thumbnail: `rounded-md`, `object-cover`, `flex-shrink-0`
- Loading: a small spinning `Loader2` icon from `lucide-react` inline in the
  input's right side (replace the static search icon while loading)

---

## Error handling

- On API error, silently clear suggestions (don't show an error state — the
  user can still submit the full search)
- On network timeout (>3s), clear suggestions

---

## Do NOT

- Add a new backend API endpoint — `/api/games?q=...&limit=6` is sufficient
- Install a third-party autocomplete library (Downshift, react-select, etc.)
  — implement natively; it's ~120 lines
- Use `useEffect` with a raw `setTimeout` for debounce — use a proper
  `useMemo`/`useCallback` + `useRef` cancellation pattern or a simple custom
  `useDebounce` hook (inline it in the component file, ~10 lines)
- Cache results across sessions (in-memory per-render is fine — the API is
  fast and results change)

---

## Files to touch

| File | Change |
|---|---|
| `frontend/components/layout/SearchAutocomplete.tsx` | **Create** |
| `frontend/components/layout/Navbar.tsx` | Replace two `<input>` elements with `<SearchAutocomplete>` |
| `frontend/lib/api.ts` | Add `searchSuggestions(q: string)` thin wrapper calling `getGames({ q, limit: 6 })` if it makes the component cleaner |

---

## Acceptance criteria

1. Typing "half" shows suggestions including "Half-Life 2" within 300ms of
   stopping
2. Arrow keys highlight rows, Enter navigates to the highlighted game page
3. Clicking outside closes the dropdown
4. Escape closes the dropdown without navigating
5. Submitting the form (Enter with no highlight, or click search icon) still
   navigates to `/search?q=...`
6. Mobile search input behaves identically
7. Screen reader announces `role="combobox"` and option count
8. No layout shift — the input size does not change when the dropdown opens
