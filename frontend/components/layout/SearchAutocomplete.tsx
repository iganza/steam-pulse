"use client";

import { useState, useEffect, useRef, useCallback, useId } from "react";
import { useRouter, usePathname } from "next/navigation";
import Image from "next/image";
import { Search, Loader2 } from "lucide-react";
import type { Game } from "@/lib/types";
import { getGames } from "@/lib/api";

// ── Debounce hook ─────────────────────────────────────────────────────────────

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setDebounced(value), delay);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [value, delay]);
  return debounced;
}

// ── Sentiment helpers ─────────────────────────────────────────────────────────
//
// Steam's positive_pct is the only sentiment number we render in autocomplete.
// Prefer Steam's own `review_score_desc` label when present (e.g. "Very Positive"),
// fall back to the Steam-pct-derived label otherwise. The legacy AI sentiment_score
// path used to call sentimentLabel(undefined) for unanalysed games and crash —
// the explicit null-check below makes the row degrade gracefully instead.

function sentimentLabel(pct: number | undefined): string {
  if (pct == null) return "";
  if (pct >= 95) return "Overwhelmingly Positive";
  if (pct >= 80) return "Very Positive";
  if (pct >= 70) return "Mostly Positive";
  if (pct >= 50) return "Mixed";
  if (pct >= 30) return "Mostly Negative";
  return "Overwhelmingly Negative";
}

function sentimentColor(pct: number | undefined): string {
  if (pct == null) return "var(--muted-foreground)";
  if (pct >= 70) return "#22c55e";
  if (pct >= 50) return "#f59e0b";
  return "#ef4444";
}

function formatReviewCount(n: number | undefined): string {
  if (n == null) return "";
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k reviews`;
  return `${n} reviews`;
}

// ── Component ─────────────────────────────────────────────────────────────────

interface SearchAutocompleteProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  className?: string;
  inputClassName?: string;
  placeholder?: string;
}

export function SearchAutocomplete({
  value,
  onChange,
  onSubmit,
  className,
  inputClassName,
  placeholder = "Search games...",
}: SearchAutocompleteProps) {
  const router = useRouter();
  const pathname = usePathname();
  const listboxId = useId();
  const inputId = useId();

  const [suggestions, setSuggestions] = useState<Game[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const containerRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const cacheRef = useRef<Map<string, Game[]>>(new Map());

  const debouncedQuery = useDebounce(value, 300);

  // Prior list stays visible behind the spinner so the dropdown never flashes empty during refetch.
  useEffect(() => {
    const normalized = debouncedQuery.toLowerCase().trim();
    if (normalized.length < 2) {
      setSuggestions([]);
      setOpen(false);
      setLoading(false);
      return;
    }

    const cached = cacheRef.current.get(normalized);
    if (cached) {
      setSuggestions(cached);
      setOpen(cached.length > 0);
      setLoading(false);
      setActiveIndex(-1);
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);

    getGames(
      { q: normalized, limit: 6, sort: "review_count", fields: "compact" },
      controller.signal,
    )
      .then((res) => {
        if (controller.signal.aborted) return;
        cacheRef.current.set(normalized, res.games);
        if (cacheRef.current.size > 20) {
          const oldest = cacheRef.current.keys().next().value;
          if (oldest !== undefined) cacheRef.current.delete(oldest);
        }
        setSuggestions(res.games);
        setOpen(res.games.length > 0);
        setLoading(false);
        setActiveIndex(-1);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setSuggestions([]);
        setOpen(false);
        setLoading(false);
        setActiveIndex(-1);
      });

    return () => controller.abort();
  }, [debouncedQuery]);

  // Close on route change
  useEffect(() => {
    setOpen(false);
    setSuggestions([]);
    setActiveIndex(-1);
  }, [pathname]);

  // Close on outside click
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  const navigateToGame = useCallback((game: Game) => {
    setOpen(false);
    setSuggestions([]);
    onChange("");
    router.push(`/games/${game.appid}/${game.slug}`);
  }, [router, onChange]);

  const navigateToSearch = useCallback(() => {
    setOpen(false);
    router.push(`/search?q=${encodeURIComponent(value.trim())}`);
  }, [router, value]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // Always handle Enter — even when dropdown is closed
    if (e.key === "Enter") {
      e.preventDefault();
      if (open && activeIndex >= 0 && activeIndex < suggestions.length) {
        navigateToGame(suggestions[activeIndex]);
      } else if (open && activeIndex === suggestions.length) {
        navigateToSearch();
      } else {
        onSubmit(e as unknown as React.FormEvent);
      }
      return;
    }

    if (!open) return;

    // total items = suggestions + footer "See all" row
    const total = suggestions.length + 1;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % total);
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + total) % total);
        break;
      case "Escape":
        e.preventDefault();
        setOpen(false);
        setActiveIndex(-1);
        break;
    }
  }

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    onChange(e.target.value);
    if (e.target.value.length >= 2) setLoading(true);
  }

  const activeDescendant =
    activeIndex >= 0 && activeIndex < suggestions.length
      ? `${listboxId}-option-${activeIndex}`
      : activeIndex === suggestions.length
      ? `${listboxId}-footer`
      : undefined;

  return (
    <div ref={containerRef} className={`relative ${className ?? ""}`}>
      {/* Input wrapper with combobox role */}
      <div
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-owns={listboxId}
        className="relative w-full"
      >
        {loading ? (
          <Loader2
            className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 animate-spin pointer-events-none"
            style={{ color: "var(--teal)" }}
          />
        ) : (
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
        )}
        <input
          id={inputId}
          type="text"
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (suggestions.length > 0) setOpen(true);
          }}
          placeholder={placeholder}
          autoComplete="off"
          aria-autocomplete="list"
          aria-controls={listboxId}
          aria-activedescendant={activeDescendant}
          className={inputClassName}
        />
      </div>

      {/* Dropdown */}
      {open && (
        <ul
          id={listboxId}
          role="listbox"
          aria-label={`Search suggestions for ${value}`}
          className="absolute top-full left-0 right-0 mt-1 rounded-xl shadow-lg overflow-hidden z-50"
          style={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            marginTop: "4px",
          }}
        >
          {suggestions.map((game, i) => {
            const isActive = i === activeIndex;
            const label = game.review_score_desc ?? sentimentLabel(game.positive_pct);
            const color = sentimentColor(game.positive_pct);

            return (
              <li
                key={game.appid}
                id={`${listboxId}-option-${i}`}
                role="option"
                aria-selected={isActive}
                onMouseDown={(e) => {
                  e.preventDefault();
                  navigateToGame(game);
                }}
                onMouseEnter={() => setActiveIndex(i)}
                className="flex items-center gap-3 px-3 py-2 cursor-pointer transition-colors"
                style={{
                  background: isActive ? "var(--border)" : "transparent",
                }}
              >
                {/* Thumbnail */}
                <div className="flex-shrink-0 w-10 h-10 rounded-md overflow-hidden bg-secondary">
                  {game.header_image ? (
                    <Image
                      src={game.header_image}
                      alt={game.name}
                      width={40}
                      height={40}
                      sizes="40px"
                      className="object-cover w-full h-full"
                    />
                  ) : (
                    <div className="w-10 h-10" />
                  )}
                </div>

                {/* Name + meta */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground font-medium truncate">{game.name}</p>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    {label && (
                      <>
                        <span
                          className="inline-block w-1.5 h-1.5 rounded-full flex-shrink-0"
                          style={{ background: color }}
                        />
                        <span className="text-xs font-mono" style={{ color }}>
                          {label}
                        </span>
                      </>
                    )}
                    {game.review_count != null && (
                      <span className="text-xs font-mono text-muted-foreground">
                        · {formatReviewCount(game.review_count)}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            );
          })}

          {/* Footer */}
          <li
            id={`${listboxId}-footer`}
            role="option"
            aria-selected={activeIndex === suggestions.length}
            onMouseDown={(e) => {
              e.preventDefault();
              navigateToSearch();
            }}
            onMouseEnter={() => setActiveIndex(suggestions.length)}
            className="flex items-center justify-center px-3 py-2 cursor-pointer text-sm font-mono transition-colors"
            style={{
              borderTop: "1px solid var(--border)",
              background: activeIndex === suggestions.length ? "var(--border)" : "transparent",
              color: "var(--teal)",
            }}
          >
            See all results for &ldquo;{value}&rdquo; →
          </li>
        </ul>
      )}
    </div>
  );
}
