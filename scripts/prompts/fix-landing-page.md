# Fix the landing page (focus + conversion hygiene)

*Drop-in prompt for Claude Code in the SteamPulse project repo.*

---

## Context

The SteamPulse landing page (example URL: https://d1mamturmn55fm.cloudfront.net/) currently tries to be three things simultaneously — a Steam catalog browser, a product showcase, and a developer tool landing — without committing to any. Visitors land with no clear path forward. This task converges the page on **one primary audience (indie Steam developers) and two primary actions** (read a sample report, join the newsletter).

Positioning reference (locked, use verbatim where specified):

- **Tagline:** "Steam, decoded."
- **Sub-line:** "Game intelligence for indie Steam devs. Per-game deep-dives and cross-genre reports — cited, and priced for a solo budget."
- **Mission:** "Know before you commit. Game intelligence for indie Steam devs."
- **Artifact name:** a SteamPulse report (no separate brand name).
- **Primary audience:** solo and small-indie Steam game developers deciding what to build next.
- **Not the audience:** Steam enthusiasts / players, AAA studios, publishers, mobile devs.

## Why this matters

The site has real strengths — the per-game report artifact (e.g. the Baldur's Gate 3 page) is genuinely differentiated. But the landing page dilutes that signal with enthusiast-shaped catalog feeds (Most Popular, Trending, New Releases, Hidden Gems) that a dev doesn't care about and that visibly duplicate SteamDB. Every element on the page should either (a) prove the product's unique value or (b) drive a conversion action. Anything that does neither is noise.

## Goals (measurable)

After this work, the landing page should:

1. Have **one unambiguous primary action** above the fold (read a sample report), with **one secondary action** (newsletter signup).
2. **Remove all AAA / multiplayer / enthusiast-browsing content** from the homepage.
3. Make **"built for indie Steam devs"** explicit and visible in the hero.
4. Feature **at least one complete sample SteamPulse report** prominently as proof.
5. Preserve **SEO-valuable navigation** (genre / tag browsers) below the fold without letting them compete for hero attention.
6. Reflect the locked brand voice — cited, peer-to-peer, anti-hype.

---

## The four specific change buckets

### Bucket 1 — KILL (remove entirely)

These are enthusiast-shaped features that conflict with the dev-tool positioning. Delete their landing-page appearances (underlying routes can survive internally if useful for SEO, but they should NOT be linked from the homepage).

1. **"Most Popular" list** (typically surfaces AAA multiplayer titles like CS2, Dota 2, PUBG). Zero indie-dev relevance. Remove.
2. **"Top Rated" list** as currently composed (obscure games with scoring artifacts). Noise. Remove.
3. **"Hidden Gems" list** in its current player-discovery framing. Remove (may return reframed in Bucket 4 as "Opportunity niches" — a different artifact).
4. **"New on Steam" list of recently-released games with no analysis yet.** Showing un-analyzed games isn't what SteamPulse IS. Remove.
5. **"Just Analyzed" feed.** Internal admin signal masquerading as content. Remove.
6. **Top nav links: "Trending", "New Releases"** — enthusiast verbs. Remove from primary nav.
7. **Top nav link: "Compare"** — either remove entirely, or reframe as "Competitive analysis" (dev-framed) in Bucket 2. Default: remove.

**Acceptance:** none of the above appear anywhere on the landing page. If the underlying routes still serve SEO value, they're reachable from a sitemap or deep links but not from the nav or homepage surface.

### Bucket 2 — REFRAME (keep concept, rewrite copy)

1. **Hero sub-line** — currently player-facing ("Player intelligence across 100,000+ Steam games. What players love. What they hate. What they want next.")
   - **Replace with verbatim:** *"Game intelligence for indie Steam devs. Per-game deep-dives and cross-genre reports — cited, and priced for a solo budget."*
2. **"Explore" nav link** — rename to **"Find underserved genres"** OR remove. Current label is enthusiast-speak.
3. **"For Developers →" nav label** — now that the entire site is for devs, this is redundant. Rename to **"Pricing"** (if a pricing page exists or is being added) OR **"Pro"** OR **"Get early access"**. Pick whichever matches the waitlist flow.
4. **"Built for the people who make games" section** — keep the content, **move it up** to appear immediately after the hero. This is the strongest dev-tool signal on the site and it's currently buried. Also rename the section header to **"Built for indie Steam devs"** — more specific, better positioning discipline.
5. **Game library / recent reports section** — replace the four current lists (Most Popular, Top Rated, Hidden Gems, New on Steam) with **a single section** titled **"Recent SteamPulse reports"** showing **6-8 indie games that have full LLM reports generated.** Examples to seed: Hollow Knight, Stardew Valley, Balatro, Vampire Survivors, Hades II, Dredge, Pizza Tower, Celeste. No AAA / multiplayer titles. This collapses four weak sections into one strong section.

### Bucket 3 — KEEP (working, minor polish only)

1. **Hero headline "Steam, decoded."** — locked, stays as-is.
2. **"What You Get" 4-card section** (Player Sentiment, Competitive Intelligence, Market Intelligence, Deep Review Reports). Conceptually strong. Audit the copy for voice-rule compliance (see guardrails below) but the section structure stays.
3. **Baldur's Gate 3 expanded deep-dive card** — the proof artifact embedded on the landing page. Critical. Keep. Consider pairing with one indie example (e.g., Balatro or Hollow Knight) so the proof spans audience ranges.
4. **Sentiment Over Time chart** on the sample. Keep — dense, visual, proves the synthesis.
5. **Audience Overlap block** on the sample. Differentiator — keep.
6. **Market Trends section** (positively-rated releases over time). Keep — dev-relevant, not enthusiast noise.
7. **"Join the Pro waitlist" CTA** — keep. Ensure it survives the restructure.
8. **Browse by Genre + Browse by Tag** browsers at the bottom of the page. Keep as programmatic-SEO navigation. Below the fold — do not promote into hero territory.

### Bucket 4 — ADD (missing)

1. **Primary hero CTA: "Read a sample report →"** — links to a representative full SteamPulse report (e.g. `/games/{appid}/{slug}`). First, most visible button. Visitor should be able to see the artifact in one click.

2. **Secondary hero CTA: newsletter signup (email capture).** Short form. Copy:
   > *Weekly "Week in Genre" newsletter. Sub-genre sentiment movements and indie market signals, every Friday.*
   > [email input] [Subscribe]
   > *No spam. Unsubscribe anytime.*
   Store submissions; fire a conversion analytics event. This is the dev-tool equivalent of GameDiscoverCo's single conversion path — the canonical adjacent brand.

3. **"Know before you commit." mission line** — place as a visual break between the hero and the "Built for indie Steam devs" section. One sentence, large type, centered, no other chrome. Reinforces the brand directive.

4. **"Who this is for" explicit callout** — one sentence near the top of the "Built for indie Steam devs" section:
   > *Made for solo and indie Steam developers deciding what to build, launch, or patch next.*
   Self-selection filter. Enthusiasts read it and leave. Devs read it and stay. That's correct.

5. **"Who made this" founder signal** — avatar + one-sentence bio near the bottom of the page:
   > *Built by a Steam dev on break from their own game. You can find me at [handle].*
   Massive trust signal for the Marcus persona. Founder-led brand presence is a brand requirement, not a nice-to-have.

6. **Indie pairing on the proof artifact** — if only the BG3 deep-dive is shown currently, add one indie title (Balatro, Hollow Knight, Vampire Survivors) as a toggled or side-by-side second example. Proves the artifact works for games an indie dev would actually try to learn from.

---

## Proposed new page structure (top to bottom)

```
1. HERO
   Steam, decoded.
   Game intelligence for indie Steam devs. Per-game deep-dives and
   cross-genre reports — cited, and priced for a solo budget.
   [Read a sample report →]   [Get the weekly newsletter →]

2. "Know before you commit." — 1-line mission statement, visual break

3. BUILT FOR INDIE STEAM DEVS (formerly "Built for the people who make games")
   Made for solo and indie Steam developers deciding what to build,
   launch, or patch next.
   · Understand your players
   · Know your competition
   · Read the market
   [Join the Pro waitlist →]

4. WHAT A STEAMPULSE REPORT LOOKS LIKE
   Expanded deep-dive card (BG3 + one indie toggle)
   Sentiment chart · Audience overlap · "Explore this game →"

5. WHAT YOU GET (4-card section from current page, audited for voice)

6. RECENT STEAMPULSE REPORTS
   6-8 indie games with full LLM reports
   (replaces Most Popular, Top Rated, Hidden Gems, New on Steam)

7. MARKET TRENDS chart (kept from current page)

8. WHO MADE THIS
   Founder bio, one sentence, avatar

9. DUAL CTA
   Newsletter signup + Pro waitlist

10. BROWSE BY GENRE (SEO navigation)

11. BROWSE BY TAG (SEO navigation)

12. FOOTER
```

---

## Voice + tone guardrails (apply to all copy on the page)

- **Never use:** AI-powered, AI-generated, AI-suggested, intelligent (as adjective), smart (as adjective), unlock, leverage, disrupt, revolutionize, game-changer, next-gen, empower, transform, actionable insights, seamless, cutting-edge, deep-dive (overused), ideate.
- **Prefer:** research, synthesis, cited, data-backed, LLM-synthesized (only when technical transparency is required), pattern, signal, delta, cluster, methodology, benchmark, review mining.
- **Register:** peer-to-peer. Marcus is a solo Steam dev. Write for him, not at him. No vendor-to-customer register.
- **Tone:** cited, understated, honest under-claim. Anti-hype is a brand asset.
- **No exclamation points. No stacked em dashes.**

---

## Non-goals (don't do these in this task)

- Do not redesign the per-game report page (`/games/[appid]/[slug]`). That page is working. See the separate `fix-unanalyzed-page.md` task for the un-analyzed per-game tier.
- Do not build the newsletter generation pipeline. This task only surfaces a signup form; pipeline implementation is a separate concern.
- Do not add e-commerce / checkout. Pro tier remains a waitlist only at this stage.
- Do not add login / user accounts.
- Do not remove underlying backend routes (e.g. `/explore`, `/trending`) — only remove them from the landing page nav + surface. Deep links may survive for SEO if the team decides they're valuable.
- Do not add comparison to competitors on the landing page (SteamDB / Gamalytic / GameDiscoverCo). The brand is understated, not confrontational.

## Verification

After the changes, a cold visitor landing on the page should:

1. Understand in **under 8 seconds** that this is a tool for indie Steam developers (not for players, not for AAA).
2. See two clear action buttons above the fold: read a sample report, and subscribe to the newsletter.
3. Encounter **zero** AAA multiplayer game listings anywhere on the page.
4. Be able to reach a full SteamPulse report with one click.
5. See the founder's name somewhere on the page before leaving.
6. See genre / tag browsers if they scroll to the bottom (SEO navigation preserved).

Additional checks:

- **Voice-rule lint:** zero instances of the forbidden vocabulary list anywhere in page copy.
- **Mobile (375px width):** all sections stack cleanly, CTAs remain visible, no overflow.
- **Analytics events fire** on both primary CTAs (sample-report click, newsletter subscribe).
- **Automated HTML check:** verify the four removed lists (Most Popular, Top Rated, Hidden Gems, New on Steam) do not render any game cards on the homepage.

## Rollout

- Ship behind a feature flag `landing_page_v2` if the team wants to A/B the change. Otherwise direct deploy is acceptable — the current page has near-zero traffic pre-marketing.
- The old sub-line and four lists can be removed immediately; no migration risk since none of them have accumulated external links or SEO weight yet.

## Why each change matters (for the PR description)

- **Kill enthusiast feeds:** page converges on one audience. Removes ~70% of surface area that was competing with the product's real value proposition.
- **Reframe sub-line + nav labels:** explicit dev positioning. Enthusiasts self-filter out; devs self-filter in.
- **Add dual CTA in hero:** collapses ambiguity. Every visitor has two clear actions instead of a page of drifting options.
- **Move "Built for indie Steam devs" up:** strongest positioning content gets earned attention instead of being buried under catalog widgets.
- **Collapse four lists into one "Recent reports":** replaces noise with proof. Quality of surface area goes up; quantity goes down.
- **Add founder signal:** peer-to-peer brand is not a choice — it's structural. The brand depends on a visible human.
