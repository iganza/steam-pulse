"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { X, Plus, Pin } from "lucide-react";
import type { Genre, Tag } from "@/lib/types";
import type { ToolkitState } from "@/lib/toolkit-state";

interface FilterBarProps {
  state: ToolkitState;
  setState: (updates: Partial<ToolkitState>) => void;
  lockedFilters?: Partial<Record<string, string | number | boolean | number[]>>;
}

const SENTIMENT_LABELS: Record<string, string> = {
  positive: "Positive",
  mixed: "Mixed",
  negative: "Negative",
};

const PRICE_TIER_LABELS: Record<string, string> = {
  free: "Free",
  under_10: "Under $10",
  "10_to_20": "$10\u201320",
  over_20: "$20+",
};

const REVIEW_PRESETS = [
  { value: 50, label: "50+" },
  { value: 200, label: "200+" },
  { value: 1000, label: "1,000+" },
  { value: 10000, label: "10,000+" },
];

export function FilterBar({ state, setState, lockedFilters }: FilterBarProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [gameCount, setGameCount] = useState<number | null>(null);
  const [countLoading, setCountLoading] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const countTimer = useRef<ReturnType<typeof setTimeout>>(null);

  const isLocked = useCallback(
    (key: string) => lockedFilters && key in lockedFilters,
    [lockedFilters],
  );

  // Fetch genres/tags on first popover open
  useEffect(() => {
    if (popoverOpen && genres.length === 0) {
      fetch("/api/genres")
        .then((r) => r.json())
        .then((data) => setGenres(Array.isArray(data) ? data : []))
        .catch(() => {});
      fetch("/api/tags/top?limit=20")
        .then((r) => r.json())
        .then((data) => setTags(Array.isArray(data) ? data : []))
        .catch(() => {});
    }
  }, [popoverOpen, genres.length]);

  // Close popover on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node)
      ) {
        setPopoverOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Debounced game count fetch
  useEffect(() => {
    // If locked to a specific game, show "1 game" statically — no API call needed
    if (
      lockedFilters &&
      "appids" in lockedFilters &&
      Array.isArray(lockedFilters.appids) &&
      lockedFilters.appids.length > 0
    ) {
      setGameCount(lockedFilters.appids.length);
      return;
    }

    if (countTimer.current) clearTimeout(countTimer.current);
    setCountLoading(true);

    countTimer.current = setTimeout(() => {
      const params = new URLSearchParams();
      if (state.genre) params.set("genre", state.genre);
      if (state.tag) params.set("tag", state.tag);
      if (state.q) params.set("q", state.q);
      if (state.developer) params.set("developer", state.developer);
      if (state.sentiment) params.set("sentiment", state.sentiment);
      if (state.price_tier) params.set("price_tier", state.price_tier);
      if (state.min_reviews) params.set("min_reviews", String(state.min_reviews));
      if (state.year_from) params.set("year_from", String(state.year_from));
      if (state.year_to) params.set("year_to", String(state.year_to));
      if (state.deck) params.set("deck", state.deck);
      if (state.has_analysis) params.set("has_analysis", "true");
      if (state.sort) params.set("sort", state.sort);
      params.set("limit", "1");

      fetch(`/api/games?${params.toString()}`)
        .then((r) => r.json())
        .then((data) => {
          if (typeof data.total === "number") setGameCount(data.total);
        })
        .catch(() => {})
        .finally(() => setCountLoading(false));
    }, 300);

    return () => {
      if (countTimer.current) clearTimeout(countTimer.current);
    };
  }, [
    state.genre,
    state.tag,
    state.q,
    state.developer,
    state.sentiment,
    state.price_tier,
    state.min_reviews,
    state.year_from,
    state.year_to,
    state.deck,
    state.has_analysis,
    state.sort,
    state.appids,
  ]);

  // Build active chips
  const chips: { key: string; label: string; value: string; locked: boolean }[] = [];

  // Don't show appids as a chip — the game page URL already identifies the game,
  // and raw app IDs (e.g., "440") are meaningless to users.

  if (state.genre) {
    const genreName =
      genres.find((g) => g.slug === state.genre)?.name ?? state.genre;
    chips.push({
      key: "genre",
      label: "Genre",
      value: genreName,
      locked: !!isLocked("genre"),
    });
  }
  if (state.tag) {
    const tagName = tags.find((t) => t.slug === state.tag)?.name ?? state.tag;
    chips.push({
      key: "tag",
      label: "Tag",
      value: tagName,
      locked: !!isLocked("tag"),
    });
  }
  if (state.q) {
    chips.push({ key: "q", label: "Search", value: state.q, locked: false });
  }
  if (state.developer) {
    chips.push({
      key: "developer",
      label: "Developer",
      value: state.developer,
      locked: !!isLocked("developer"),
    });
  }
  if (state.sentiment) {
    chips.push({
      key: "sentiment",
      label: "Sentiment",
      value: SENTIMENT_LABELS[state.sentiment] ?? state.sentiment,
      locked: false,
    });
  }
  if (state.price_tier) {
    chips.push({
      key: "price_tier",
      label: "Price",
      value: PRICE_TIER_LABELS[state.price_tier] ?? state.price_tier,
      locked: false,
    });
  }
  if (state.min_reviews) {
    chips.push({
      key: "min_reviews",
      label: "Reviews",
      value: `${state.min_reviews.toLocaleString()}+`,
      locked: false,
    });
  }
  if (state.year_from || state.year_to) {
    const from = state.year_from ?? "...";
    const to = state.year_to ?? "...";
    chips.push({
      key: "year_range",
      label: "Released",
      value: `${from}\u2013${to}`,
      locked: false,
    });
  }
  if (state.deck) {
    chips.push({
      key: "deck",
      label: "Deck",
      value: "Compatible",
      locked: false,
    });
  }
  if (state.has_analysis) {
    chips.push({
      key: "has_analysis",
      label: "Analyzed",
      value: "Yes",
      locked: false,
    });
  }

  const hasRemovableFilters = chips.some((c) => !c.locked);

  function removeFilter(key: string) {
    if (key === "year_range") {
      setState({ year_from: null, year_to: null });
    } else {
      setState({ [key]: null } as Partial<ToolkitState>);
    }
  }

  function clearAll() {
    const reset: Partial<ToolkitState> = {};
    for (const chip of chips) {
      if (!chip.locked) {
        if (chip.key === "year_range") {
          reset.year_from = null;
          reset.year_to = null;
        } else {
          (reset as Record<string, null>)[chip.key] = null;
        }
      }
    }
    setState(reset);
  }

  function selectFilter(key: string, value: string | number | boolean) {
    setState({ [key]: value } as Partial<ToolkitState>);
    setPopoverOpen(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 py-3">
      {/* Active chips */}
      {chips.map((chip) => (
        <span
          key={chip.key}
          className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-sm font-mono border transition-colors ${
            chip.locked
              ? "border-[color:var(--teal)]/30 text-foreground/80"
              : "border-border text-foreground/70 hover:text-foreground"
          }`}
        >
          {chip.locked && <Pin className="w-3 h-3 text-muted-foreground" />}
          <span className="text-muted-foreground">{chip.label}:</span>{" "}
          {chip.value}
          {!chip.locked && (
            <button
              onClick={() => removeFilter(chip.key)}
              className="ml-0.5 hover:text-foreground"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </span>
      ))}

      {/* Add Filter button + popover */}
      <div ref={popoverRef} className="relative">
        <button
          onClick={() => setPopoverOpen(!popoverOpen)}
          className="flex items-center gap-1 px-2.5 py-1 rounded-full text-sm font-mono border border-border text-muted-foreground hover:text-foreground transition-colors"
        >
          <Plus className="w-3 h-3" /> Add Filter
        </button>

        {popoverOpen && (
          <div
            className="absolute top-full left-0 mt-1 w-72 rounded-xl p-3 shadow-xl z-50 space-y-3"
            style={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
            }}
          >
            {/* Genre */}
            {!isLocked("genre") && (
              <FilterSection title="Genre">
                <div className="max-h-32 overflow-y-auto space-y-0.5">
                  {genres.map((g) => (
                    <button
                      key={g.id}
                      onClick={() => selectFilter("genre", g.slug)}
                      className={`block w-full text-left text-sm py-0.5 px-1 rounded transition-colors ${
                        state.genre === g.slug
                          ? "text-foreground bg-card"
                          : "text-foreground/70 hover:text-foreground"
                      }`}
                    >
                      {g.name}
                    </button>
                  ))}
                  {genres.length === 0 && (
                    <p className="text-xs text-muted-foreground">Loading...</p>
                  )}
                </div>
              </FilterSection>
            )}

            {/* Tag */}
            {!isLocked("tag") && (
              <FilterSection title="Tag">
                <div className="max-h-32 overflow-y-auto space-y-0.5">
                  {tags.map((t) => (
                    <button
                      key={t.id}
                      onClick={() => selectFilter("tag", t.slug)}
                      className={`block w-full text-left text-sm py-0.5 px-1 rounded transition-colors ${
                        state.tag === t.slug
                          ? "text-foreground bg-card"
                          : "text-foreground/70 hover:text-foreground"
                      }`}
                    >
                      {t.name}
                    </button>
                  ))}
                  {tags.length === 0 && (
                    <p className="text-xs text-muted-foreground">Loading...</p>
                  )}
                </div>
              </FilterSection>
            )}

            {/* Price */}
            <FilterSection title="Price Range">
              <div className="flex flex-wrap gap-1">
                {Object.entries(PRICE_TIER_LABELS).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => selectFilter("price_tier", value)}
                    className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                      state.price_tier === value
                        ? "bg-card text-foreground border border-[color:var(--teal)]/30"
                        : "text-foreground/70 hover:text-foreground border border-border"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </FilterSection>

            {/* Min Reviews */}
            <FilterSection title="Min Reviews">
              <div className="flex flex-wrap gap-1">
                {REVIEW_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    onClick={() => selectFilter("min_reviews", preset.value)}
                    className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                      state.min_reviews === preset.value
                        ? "bg-card text-foreground border border-[color:var(--teal)]/30"
                        : "text-foreground/70 hover:text-foreground border border-border"
                    }`}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </FilterSection>

            {/* Sentiment */}
            <FilterSection title="Sentiment">
              <div className="flex flex-wrap gap-1">
                {Object.entries(SENTIMENT_LABELS).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => selectFilter("sentiment", value)}
                    className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                      state.sentiment === value
                        ? "bg-card text-foreground border border-[color:var(--teal)]/30"
                        : "text-foreground/70 hover:text-foreground border border-border"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </FilterSection>

            {/* Deck */}
            <FilterSection title="Steam Deck">
              <button
                onClick={() => selectFilter("deck", state.deck ? "" : "verified")}
                className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                  state.deck
                    ? "bg-card text-foreground border border-[color:var(--teal)]/30"
                    : "text-foreground/70 hover:text-foreground border border-border"
                }`}
              >
                Deck Compatible
              </button>
            </FilterSection>

            {/* Analyzed Only */}
            <FilterSection title="Analysis">
              <button
                onClick={() =>
                  selectFilter("has_analysis", !state.has_analysis)
                }
                className={`px-2 py-0.5 rounded text-xs font-mono transition-colors ${
                  state.has_analysis
                    ? "bg-card text-foreground border border-[color:var(--teal)]/30"
                    : "text-foreground/70 hover:text-foreground border border-border"
                }`}
              >
                Analyzed Only
              </button>
            </FilterSection>
          </div>
        )}
      </div>

      {/* Clear all */}
      {hasRemovableFilters && (
        <button
          onClick={clearAll}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors font-mono"
        >
          Clear all
        </button>
      )}

      {/* Game count */}
      <span
        className={`ml-auto text-xs font-mono text-muted-foreground transition-opacity ${countLoading ? "opacity-50" : ""}`}
      >
        {gameCount !== null ? `${gameCount.toLocaleString()} games` : "\u00A0"}
      </span>
    </div>
  );
}

function FilterSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-1">
        {title}
      </p>
      {children}
    </div>
  );
}
