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
  const [devInput, setDevInput] = useState("");
  const [yearFromInput, setYearFromInput] = useState("");
  const [yearToInput, setYearToInput] = useState("");
  const popoverRef = useRef<HTMLDivElement>(null);
  const countTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isLocked = useCallback(
    (key: string) => lockedFilters && key in lockedFilters,
    [lockedFilters],
  );

  // Fetch genres/tags on first popover open (independently so one failure doesn't block the other)
  useEffect(() => {
    if (!popoverOpen) return;
    if (genres.length === 0) {
      fetch("/api/genres")
        .then((r) => r.json())
        .then((data) => setGenres(Array.isArray(data) ? data : []))
        .catch(() => {});
    }
    if (tags.length === 0) {
      fetch("/api/tags/top?limit=20")
        .then((r) => r.json())
        .then((data) => setTags(Array.isArray(data) ? data : []))
        .catch(() => {});
    }
  }, [popoverOpen, genres.length, tags.length]);

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
      setCountLoading(false);
      return;
    }

    if (countTimer.current) clearTimeout(countTimer.current);
    setCountLoading(true);

    countTimer.current = setTimeout(() => {
      // Merge URL state with locked filters for accurate count
      const genre = state.genre || (lockedFilters?.genre as string) || "";
      const tag = state.tag || (lockedFilters?.tag as string) || "";

      const params = new URLSearchParams();
      if (genre) params.set("genre", genre);
      if (tag) params.set("tag", tag);
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

  // Build active chips from effective values (URL state + locked filters)
  const chips: { key: string; label: string; value: string; locked: boolean }[] = [];

  // Helper: get effective value for a filter key (locked takes precedence)
  function effective<K extends keyof typeof state>(key: K) {
    if (isLocked(key) && lockedFilters![key] !== undefined && lockedFilters![key] !== "") {
      return lockedFilters![key];
    }
    return state[key];
  }

  // Don't show appids as a chip — the game page URL already identifies the game

  const effGenre = effective("genre") as string;
  if (effGenre) {
    const genreName = genres.find((g) => g.slug === effGenre)?.name ?? effGenre;
    chips.push({
      key: "genre",
      label: "Genre",
      value: genreName,
      locked: !!isLocked("genre"),
    });
  }
  const effTag = effective("tag") as string;
  if (effTag) {
    const tagName = tags.find((t) => t.slug === effTag)?.name ?? effTag;
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
  const effDeveloper = effective("developer") as string;
  if (effDeveloper) {
    chips.push({
      key: "developer",
      label: "Developer",
      value: effDeveloper,
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
    // Reset all filter keys to null/defaults, preserving only locked filters
    const lockedKeys = lockedFilters ? Object.keys(lockedFilters) : [];
    const reset: Partial<ToolkitState> = {};
    const filterKeys = [
      "genre", "tag", "q", "developer", "sentiment", "price_tier",
      "min_reviews", "year_from", "year_to", "deck", "has_analysis",
      "sort", "appids",
    ] as const;
    for (const key of filterKeys) {
      if (!lockedKeys.includes(key)) {
        (reset as Record<string, null>)[key] = null;
      }
    }
    setState(reset);
  }

  function selectFilter(key: string, value: string | number | boolean | null) {
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

            {/* Developer */}
            {!isLocked("developer") && (
              <FilterSection title="Developer">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (devInput.trim()) {
                      selectFilter("developer", devInput.trim());
                      setDevInput("");
                    }
                  }}
                >
                  <input
                    type="text"
                    value={devInput}
                    onChange={(e) => setDevInput(e.target.value)}
                    placeholder="Developer name..."
                    className="w-full px-2 py-1 rounded text-sm bg-card border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
                  />
                </form>
              </FilterSection>
            )}

            {/* Release Year */}
            <FilterSection title="Release Year">
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const from = yearFromInput ? Number(yearFromInput) : null;
                  const to = yearToInput ? Number(yearToInput) : null;
                  if (from) setState({ year_from: from } as Partial<ToolkitState>);
                  if (to) setState({ year_to: to } as Partial<ToolkitState>);
                  if (from || to) setPopoverOpen(false);
                }}
              >
                <input
                  type="number"
                  value={yearFromInput}
                  onChange={(e) => setYearFromInput(e.target.value)}
                  placeholder="From"
                  min="1990"
                  max="2030"
                  className="w-20 px-2 py-1 rounded text-sm bg-card border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
                />
                <span className="text-muted-foreground text-xs">&ndash;</span>
                <input
                  type="number"
                  value={yearToInput}
                  onChange={(e) => setYearToInput(e.target.value)}
                  placeholder="To"
                  min="1990"
                  max="2030"
                  className="w-20 px-2 py-1 rounded text-sm bg-card border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
                />
                <button
                  type="submit"
                  className="px-2 py-1 rounded text-xs font-mono border border-border text-foreground/70 hover:text-foreground transition-colors"
                >
                  Apply
                </button>
              </form>
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
                  selectFilter("has_analysis", state.has_analysis ? null : true)
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
