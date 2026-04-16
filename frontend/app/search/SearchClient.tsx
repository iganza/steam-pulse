"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { Search, X, Grid3X3, List, ChevronLeft, ChevronRight, SlidersHorizontal } from "lucide-react";
import { GameCard } from "@/components/game/GameCard";
import { displayedReview } from "@/lib/review-display";
import type { Game, Genre, Tag } from "@/lib/types";
import type { GamesResponse } from "@/lib/api";

interface SearchClientProps {
  initialParams: Record<string, string>;
  initialFilters?: Record<string, string>;
  hideGenreFilter?: boolean;
  hideTagFilter?: boolean;
}

const SORT_OPTIONS = [
  { value: "review_count", label: "Most Reviewed" },
  // Wire value stays "sentiment_score" for bookmark compatibility — the API
  // handler maps it to ORDER BY positive_pct DESC server-side.
  { value: "sentiment_score", label: "Best on Steam" },
  { value: "hidden_gem_score", label: "Hidden Gem Score" },
  { value: "release_date", label: "Recently Released" },
  { value: "last_analyzed", label: "Recently Analyzed" },
  { value: "name", label: "Alphabetical A\u2013Z" },
];

const REVIEW_PRESETS = [
  { value: "", label: "Any" },
  { value: "50", label: "50+" },
  { value: "200", label: "200+" },
  { value: "1000", label: "1,000+" },
  { value: "10000", label: "10,000+" },
];

const SENTIMENT_OPTIONS = [
  { value: "", label: "All" },
  { value: "positive", label: "Positive" },
  { value: "mixed", label: "Mixed" },
  { value: "negative", label: "Negative" },
];

const PRICE_OPTIONS = [
  { value: "", label: "All" },
  { value: "free", label: "Free" },
  { value: "under_10", label: "Under $10" },
  { value: "10_to_20", label: "$10\u2013$20" },
  { value: "over_20", label: "$20+" },
];

const PER_PAGE_OPTIONS = [24, 48, 96];

export function SearchClient({ initialParams, initialFilters, hideGenreFilter, hideTagFilter }: SearchClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Read state from URL
  const q = searchParams.get("q") ?? initialFilters?.q ?? "";
  const genre = searchParams.get("genre") ?? initialFilters?.genre ?? "";
  const tag = searchParams.get("tag") ?? initialFilters?.tag ?? "";
  const developer = searchParams.get("developer") ?? initialFilters?.developer ?? "";
  const sort = searchParams.get("sort") ?? initialFilters?.sort ?? "review_count";
  const page = Number(searchParams.get("page") ?? "1");
  const perPage = Number(searchParams.get("per_page") ?? "24");
  const viewParam = searchParams.get("view");
  const minReviews = searchParams.get("min_reviews") ?? "";
  const sentiment = searchParams.get("sentiment") ?? "";
  const priceTier = searchParams.get("price_tier") ?? "";
  const hasAnalysis = searchParams.get("has_analysis") ?? "";
  const yearFrom = searchParams.get("year_from") ?? "";
  const yearTo = searchParams.get("year_to") ?? "";

  const [savedView, setSavedView] = useState<string>("grid");
  const view = viewParam ?? savedView;

  const [games, setGames] = useState<Game[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [mobileFilters, setMobileFilters] = useState(false);
  const [searchInput, setSearchInput] = useState(q);

  // Load saved view preference
  useEffect(() => {
    try {
      const saved = localStorage.getItem("sp_view_pref");
      if (saved === "list" || saved === "grid") setSavedView(saved);
    } catch { /* noop */ }
  }, []);

  // Fetch genres and tags for filters
  useEffect(() => {
    fetch("/api/genres")
      .then((r) => r.json())
      .then((data) => setGenres(Array.isArray(data) ? data : []))
      .catch(() => {});
    fetch("/api/tags/top?limit=30")
      .then((r) => r.json())
      .then((data) => setTags(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  // Fetch games when params change
  const fetchGames = useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams();
    if (q) qs.set("q", q);
    if (genre) qs.set("genre", genre);
    if (tag) qs.set("tag", tag);
    if (developer) qs.set("developer", developer);
    if (minReviews) qs.set("min_reviews", minReviews);
    if (sentiment) qs.set("sentiment", sentiment);
    if (priceTier) qs.set("price_tier", priceTier);
    if (hasAnalysis === "true") qs.set("has_analysis", "true");
    if (yearFrom) qs.set("year_from", yearFrom);
    if (yearTo) qs.set("year_to", yearTo);
    qs.set("sort", sort);
    qs.set("limit", String(perPage));
    qs.set("offset", String((page - 1) * perPage));

    try {
      const res = await fetch(`/api/games?${qs.toString()}`);
      const data: GamesResponse = await res.json();
      // Handle old-format (array) or new format ({ total, games })
      if (Array.isArray(data)) {
        setGames(data);
        setTotal(data.length);
      } else {
        setGames(data.games ?? []);
        setTotal(data.total ?? 0);
      }
    } catch {
      setGames([]);
      setTotal(0);
    }
    setLoading(false);
  }, [q, genre, tag, developer, sort, page, perPage, minReviews, sentiment, priceTier, hasAnalysis, yearFrom, yearTo]);

  useEffect(() => {
    fetchGames();
  }, [fetchGames]);

  function updateParams(updates: Record<string, string>) {
    const params = new URLSearchParams(searchParams.toString());
    // Apply initial filters that are fixed (e.g., genre from genre page)
    if (initialFilters) {
      for (const [k, v] of Object.entries(initialFilters)) {
        if (!(k in updates) && !params.has(k)) params.set(k, v);
      }
    }
    for (const [k, v] of Object.entries(updates)) {
      if (v) params.set(k, v);
      else params.delete(k);
    }
    // Reset to page 1 when filters change (unless page is being set explicitly)
    if (!("page" in updates)) params.delete("page");
    router.push(`?${params.toString()}`, { scroll: false });
  }

  function toggleView(v: "grid" | "list") {
    try { localStorage.setItem("sp_view_pref", v); } catch { /* noop */ }
    setSavedView(v);
    updateParams({ view: v });
  }

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    updateParams({ q: searchInput });
  }

  function removeFilter(key: string) {
    updateParams({ [key]: "" });
    if (key === "q") setSearchInput("");
  }

  function clearAllFilters() {
    setSearchInput("");
    const params = new URLSearchParams();
    if (initialFilters) {
      for (const [k, v] of Object.entries(initialFilters)) params.set(k, v);
    }
    router.push(`?${params.toString()}`, { scroll: false });
  }

  // Active filter chips
  const activeFilters: { key: string; label: string }[] = [];
  if (q) activeFilters.push({ key: "q", label: `Search: ${q}` });
  if (genre && !initialFilters?.genre) activeFilters.push({ key: "genre", label: `Genre: ${genre}` });
  if (tag && !initialFilters?.tag) activeFilters.push({ key: "tag", label: `Tag: ${tag}` });
  if (developer) activeFilters.push({ key: "developer", label: `Developer: ${developer}` });
  if (minReviews) activeFilters.push({ key: "min_reviews", label: `Min Reviews: ${minReviews}+` });
  if (sentiment) activeFilters.push({ key: "sentiment", label: `Sentiment: ${sentiment}` });
  if (priceTier) activeFilters.push({ key: "price_tier", label: `Price: ${priceTier.replace(/_/g, " ")}` });
  if (hasAnalysis === "true") activeFilters.push({ key: "has_analysis", label: "Analyzed only" });
  if (yearFrom) activeFilters.push({ key: "year_from", label: `From: ${yearFrom}` });
  if (yearTo) activeFilters.push({ key: "year_to", label: `To: ${yearTo}` });

  const totalPages = Math.ceil(total / perPage);
  const startItem = (page - 1) * perPage + 1;
  const endItem = Math.min(page * perPage, total);

  // Page numbers to show
  const pageNumbers: (number | "...")[] = [];
  if (totalPages <= 7) {
    for (let i = 1; i <= totalPages; i++) pageNumbers.push(i);
  } else {
    pageNumbers.push(1);
    if (page > 3) pageNumbers.push("...");
    for (let i = Math.max(2, page - 1); i <= Math.min(totalPages - 1, page + 1); i++) {
      pageNumbers.push(i);
    }
    if (page < totalPages - 2) pageNumbers.push("...");
    pageNumbers.push(totalPages);
  }

  const filterSidebar = (
    <div className="space-y-6">
      {/* Search */}
      <div>
        <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Search</p>
        <form onSubmit={handleSearch}>
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Game name..."
              className="w-full pl-8 pr-3 py-2 rounded-lg bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
            />
          </div>
        </form>
      </div>

      {/* Genres */}
      {!hideGenreFilter && genres.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Genre</p>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {genres.slice(0, 20).map((g) => (
              <label key={g.id} className="flex items-center gap-2 text-sm cursor-pointer hover:text-foreground text-foreground/70">
                <input
                  type="radio"
                  name="genre"
                  checked={genre === g.slug}
                  onChange={() => updateParams({ genre: genre === g.slug ? "" : g.slug })}
                  className="accent-teal-400 w-3 h-3"
                />
                {g.name}
                {g.game_count != null && <span className="text-muted-foreground ml-auto">{g.game_count.toLocaleString()}</span>}
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Tags */}
      {!hideTagFilter && tags.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Tags</p>
          <div className="space-y-1 max-h-48 overflow-y-auto">
            {tags.slice(0, 20).map((t) => (
              <label key={t.id} className="flex items-center gap-2 text-sm cursor-pointer hover:text-foreground text-foreground/70">
                <input
                  type="radio"
                  name="tag"
                  checked={tag === t.slug}
                  onChange={() => updateParams({ tag: tag === t.slug ? "" : t.slug })}
                  className="accent-teal-400 w-3 h-3"
                />
                {t.name}
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Min Reviews */}
      <div>
        <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Min Reviews</p>
        <div className="space-y-1">
          {REVIEW_PRESETS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer hover:text-foreground text-foreground/70">
              <input
                type="radio"
                name="min_reviews"
                checked={minReviews === opt.value}
                onChange={() => updateParams({ min_reviews: opt.value })}
                className="accent-teal-400 w-3 h-3"
              />
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      {/* Sentiment */}
      <div>
        <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Sentiment</p>
        <div className="space-y-1">
          {SENTIMENT_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer hover:text-foreground text-foreground/70">
              <input
                type="radio"
                name="sentiment"
                checked={sentiment === opt.value}
                onChange={() => updateParams({ sentiment: opt.value })}
                className="accent-teal-400 w-3 h-3"
              />
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      {/* Analysis status */}
      <div>
        <label className="flex items-center gap-2 text-sm cursor-pointer hover:text-foreground text-foreground/70">
          <input
            type="checkbox"
            checked={hasAnalysis === "true"}
            onChange={(e) => updateParams({ has_analysis: e.target.checked ? "true" : "" })}
            className="accent-teal-400 w-3 h-3"
          />
          Analyzed only
        </label>
      </div>

      {/* Price */}
      <div>
        <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Price</p>
        <div className="space-y-1">
          {PRICE_OPTIONS.map((opt) => (
            <label key={opt.value} className="flex items-center gap-2 text-sm cursor-pointer hover:text-foreground text-foreground/70">
              <input
                type="radio"
                name="price_tier"
                checked={priceTier === opt.value}
                onChange={() => updateParams({ price_tier: opt.value })}
                className="accent-teal-400 w-3 h-3"
              />
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      {/* Year Range */}
      <div>
        <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">Release Year</p>
        <div className="flex gap-2">
          <input
            type="number"
            placeholder="From"
            value={yearFrom}
            onChange={(e) => updateParams({ year_from: e.target.value })}
            className="w-full px-2 py-1.5 rounded bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
          />
          <input
            type="number"
            placeholder="To"
            value={yearTo}
            onChange={(e) => updateParams({ year_to: e.target.value })}
            className="w-full px-2 py-1.5 rounded bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
          />
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex gap-8">
          {/* Desktop filter sidebar */}
          <aside className="hidden md:block w-64 flex-shrink-0">
            <div className="sticky top-20">{filterSidebar}</div>
          </aside>

          {/* Results area */}
          <div className="flex-1 min-w-0">
            {/* Mobile filter button */}
            <div className="md:hidden mb-4">
              <button
                onClick={() => setMobileFilters(true)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-mono border border-border text-muted-foreground hover:text-foreground"
              >
                <SlidersHorizontal className="w-4 h-4" /> Filters
              </button>
            </div>

            {/* Sort bar + view toggle + results count */}
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <div className="flex items-center gap-3">
                <select
                  value={sort}
                  onChange={(e) => updateParams({ sort: e.target.value })}
                  className="bg-card border border-border rounded-lg px-3 py-1.5 text-sm font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
                >
                  {SORT_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
                {total > 0 && (
                  <span className="text-sm text-muted-foreground font-mono">
                    Showing {startItem}\u2013{endItem} of {total.toLocaleString()} games
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => toggleView("grid")}
                  className={`p-1.5 rounded ${view === "grid" ? "text-foreground" : "text-muted-foreground"}`}
                >
                  <Grid3X3 className="w-4 h-4" />
                </button>
                <button
                  onClick={() => toggleView("list")}
                  className={`p-1.5 rounded ${view === "list" ? "text-foreground" : "text-muted-foreground"}`}
                >
                  <List className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Active filter chips */}
            {activeFilters.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 mb-4">
                {activeFilters.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => removeFilter(f.key)}
                    className="flex items-center gap-1 px-2.5 py-1 rounded-full text-sm font-mono border border-border text-foreground/70 hover:text-foreground transition-colors"
                  >
                    {f.label} <X className="w-3 h-3" />
                  </button>
                ))}
                <button
                  onClick={clearAllFilters}
                  className="text-sm font-mono text-muted-foreground hover:text-foreground transition-colors"
                >
                  Clear all filters
                </button>
              </div>
            )}

            {/* Results */}
            {loading ? (
              <div className="text-center py-20">
                <p className="text-base text-muted-foreground font-mono">Loading...</p>
              </div>
            ) : games.length === 0 ? (
              <div className="text-center py-20">
                <p className="text-base text-muted-foreground mb-4">No games match your filters.</p>
                <button
                  onClick={clearAllFilters}
                  className="text-sm font-mono px-4 py-2 rounded-lg border border-border text-muted-foreground hover:text-foreground"
                >
                  Clear filters
                </button>
              </div>
            ) : view === "grid" ? (
              <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
                {games.map((game) => (
                  <GameCard key={game.appid} game={game} />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {/* Table header */}
                <div className="hidden sm:grid grid-cols-12 gap-2 px-4 py-2 text-xs uppercase tracking-widest font-mono text-muted-foreground">
                  <div className="col-span-5">Game</div>
                  <div className="col-span-2">Genre</div>
                  <div className="col-span-1 text-right">Reviews</div>
                  <div className="col-span-2 text-right">Sentiment</div>
                  <div className="col-span-2 text-right">Released</div>
                </div>
                {games.map((game) => {
                  const displayed = displayedReview(game);
                  const score = displayed.count > 0 ? displayed.positivePct : null;
                  const scoreColor = (score ?? 0) >= 75 ? "#22c55e" : (score ?? 0) >= 50 ? "#f59e0b" : "#ef4444";
                  return (
                    <Link
                      key={game.appid}
                      href={`/games/${game.appid}/${game.slug}`}
                      className="group grid grid-cols-12 gap-2 items-center p-3 rounded-lg transition-all hover:scale-[1.005]"
                      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
                    >
                      <div className="col-span-5 flex items-center gap-3 min-w-0">
                        {game.header_image && (
                          <div className="relative w-16 h-[34px] rounded overflow-hidden flex-shrink-0">
                            <Image src={game.header_image} alt={game.name} fill sizes="64px" className="object-cover" />
                          </div>
                        )}
                        <div className="min-w-0">
                          <p className="text-sm font-semibold truncate group-hover:text-teal-300 transition-colors">{game.name}</p>
                          {game.developer && <p className="text-xs text-muted-foreground truncate">{game.developer}</p>}
                        </div>
                      </div>
                      <div className="col-span-2 text-xs text-muted-foreground truncate">
                        {game.genres?.[0] ?? "\u2014"}
                      </div>
                      <div className="col-span-1 text-right text-xs font-mono text-muted-foreground">
                        {displayed.count > 0 ? displayed.count.toLocaleString() : "\u2014"}
                      </div>
                      <div className="col-span-2 text-right">
                        {score != null ? (
                          <span className="font-mono text-xs" style={{ color: scoreColor }}>{score}</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">\u2014</span>
                        )}
                      </div>
                      <div className="col-span-2 text-right text-xs font-mono text-muted-foreground">
                        {game.release_date ? new Date(game.release_date).getFullYear() : "\u2014"}
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <nav aria-label="Pagination" className="flex items-center justify-center gap-1 mt-8">
                <button
                  onClick={() => updateParams({ page: String(page - 1) })}
                  disabled={page <= 1}
                  className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
                >
                  <ChevronLeft className="w-3 h-3" /> Prev
                </button>
                {pageNumbers.map((pn, i) =>
                  pn === "..." ? (
                    <span key={`dots-${i}`} className="px-2 text-muted-foreground text-sm">\u2026</span>
                  ) : (
                    <button
                      key={pn}
                      onClick={() => updateParams({ page: String(pn) })}
                      className={`px-3 py-1.5 rounded text-sm font-mono ${pn === page ? "text-foreground border border-border" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {pn}
                    </button>
                  ),
                )}
                <button
                  onClick={() => updateParams({ page: String(page + 1) })}
                  disabled={page >= totalPages}
                  className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
                >
                  Next <ChevronRight className="w-3 h-3" />
                </button>
                <select
                  value={perPage}
                  onChange={(e) => updateParams({ per_page: e.target.value })}
                  className="ml-4 bg-card border border-border rounded px-2 py-1 text-sm font-mono text-foreground focus:outline-none"
                >
                  {PER_PAGE_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n} per page</option>
                  ))}
                </select>
              </nav>
            )}
          </div>
        </div>
      </div>

      {/* Mobile filter drawer */}
      {mobileFilters && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileFilters(false)} />
          <div
            className="absolute bottom-0 left-0 right-0 max-h-[85vh] overflow-y-auto rounded-t-2xl p-6"
            style={{ background: "var(--background)" }}
          >
            <div className="flex items-center justify-between mb-6">
              <p className="text-base font-mono font-medium">Filters</p>
              <button onClick={() => setMobileFilters(false)} className="text-muted-foreground hover:text-foreground">
                <X className="w-5 h-5" />
              </button>
            </div>
            {filterSidebar}
            <button
              onClick={() => setMobileFilters(false)}
              className="w-full mt-6 py-3 rounded-lg text-base font-mono font-medium"
              style={{ background: "var(--teal)", color: "#0c0c0f" }}
            >
              Apply Filters
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
