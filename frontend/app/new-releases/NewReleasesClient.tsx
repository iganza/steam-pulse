"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { ChevronLeft, ChevronRight, Clock, Sparkles, Calendar, X } from "lucide-react";
import {
  getNewReleasesReleased,
  getNewReleasesUpcoming,
  getNewReleasesAdded,
  type NewReleaseEntry,
  type NewReleasesWindow,
} from "@/lib/api";
import type { Genre, Tag } from "@/lib/types";
import { relativeTime as sharedRelativeTime, slugify } from "@/lib/format";

type Lens = "released" | "upcoming" | "added";

const LENSES: { key: Lens; label: string }[] = [
  { key: "released", label: "Released" },
  { key: "upcoming", label: "Coming Soon" },
  { key: "added", label: "Just Added" },
];

const WINDOWS: { key: NewReleasesWindow; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "week", label: "This Week" },
  { key: "month", label: "This Month" },
  { key: "quarter", label: "This Quarter" },
];

const DEFAULT_LENS: Lens = "released";
const DEFAULT_WINDOW: NewReleasesWindow = "week";
const VALID_LENSES = new Set<string>(LENSES.map((l) => l.key));
const VALID_WINDOWS = new Set<string>(WINDOWS.map((w) => w.key));

function parseLens(raw: string | null): Lens {
  return raw && VALID_LENSES.has(raw) ? (raw as Lens) : DEFAULT_LENS;
}
function parseWindow(raw: string | null): NewReleasesWindow {
  return raw && VALID_WINDOWS.has(raw) ? (raw as NewReleasesWindow) : DEFAULT_WINDOW;
}

const PER_PAGE = 24;

interface FeedState {
  items: NewReleaseEntry[];
  total: number;
  counts: { today: number; week: number; month: number; quarter: number } | null;
  buckets: { this_week: number; this_month: number; this_quarter: number; tba: number } | null;
  loading: boolean;
}

const INITIAL: FeedState = {
  items: [],
  total: 0,
  counts: null,
  buckets: null,
  loading: true,
};

// Thin wrapper around the shared `relativeTime` helper from @/lib/format so
// callers can treat the result as non-null (our entries always have a
// `discovered_at` TIMESTAMPTZ, so the shared helper's `null` branch is
// unreachable here).
function relativeTime(iso: string): string {
  return sharedRelativeTime(iso) ?? "";
}

function FeedCard({ entry, lens }: { entry: NewReleaseEntry; lens: Lens }) {
  const href = entry.slug ? `/games/${entry.appid}/${entry.slug}` : null;

  // Pending-metadata skeleton card.
  if (entry.metadata_pending || !href) {
    return (
      <div
        className="flex flex-col rounded-xl overflow-hidden p-4"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
        data-testid="pending-metadata-card"
      >
        <div className="aspect-[460/215] rounded-md bg-secondary mb-3" />
        <h3 className="font-serif text-base font-semibold line-clamp-1 mb-1">
          {entry.name}
        </h3>
        <span className="text-xs font-mono uppercase tracking-widest text-muted-foreground">
          metadata pending · added {relativeTime(entry.discovered_at)}
        </span>
      </div>
    );
  }

  const reviewCount = entry.review_count_english ?? entry.review_count ?? 0;
  const hasReviews = reviewCount >= 10 && entry.positive_pct != null;
  const score = entry.positive_pct ?? 0;
  const scoreColor = score >= 75 ? "#22c55e" : score >= 50 ? "#f59e0b" : "#ef4444";

  // Mirror GameHero: hide publisher when it matches developer (self-published).
  const showPublisher = Boolean(
    entry.publisher &&
      (entry.publisher_slug
        ? entry.publisher_slug !== entry.developer_slug
        : entry.publisher !== entry.developer),
  );

  return (
    <div
      className="group flex flex-col rounded-xl overflow-hidden transition-all duration-300 hover:scale-[1.02]"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <Link href={href} className="relative block aspect-[460/215] overflow-hidden bg-secondary">
        {entry.header_image && (
          <Image
            src={entry.header_image}
            alt={entry.name}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
            className="object-cover transition-transform duration-500 group-hover:scale-105"
          />
        )}
        {entry.has_analysis && (
          <div
            className="absolute top-2 right-2 px-2 py-0.5 rounded-full text-xs font-mono uppercase tracking-widest"
            style={{ background: "rgba(34,197,94,0.85)", color: "#0c0c0f" }}
          >
            Analyzed
          </div>
        )}
      </Link>
      <div className="p-4 flex-1 flex flex-col">
        <h3 className="font-serif text-base font-semibold line-clamp-1 mb-1">
          <Link href={href} className="hover:underline">
            {entry.name}
          </Link>
        </h3>
        {(entry.developer || entry.publisher) && (
          <p className="text-xs text-muted-foreground font-mono mb-2 truncate">
            {entry.developer && (
              <>
                by{" "}
                <Link
                  href={`/developer/${entry.developer_slug ?? slugify(entry.developer)}`}
                  className="hover:underline"
                  style={{ color: "var(--teal)" }}
                >
                  {entry.developer}
                </Link>
              </>
            )}
            {showPublisher && entry.publisher && (
              <>
                {entry.developer && <span className="mx-1.5">·</span>}
                <Link
                  href={`/publisher/${entry.publisher_slug ?? slugify(entry.publisher)}`}
                  className="hover:underline"
                  style={{ color: "var(--teal)" }}
                >
                  {entry.publisher}
                </Link>
              </>
            )}
          </p>
        )}

        {entry.top_tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {entry.top_tags.slice(0, 3).map((t) => (
              <span
                key={t}
                className="text-[10px] uppercase tracking-widest font-mono px-1.5 py-0.5 rounded"
                style={{ background: "var(--secondary)", color: "var(--muted-foreground)" }}
              >
                {t}
              </span>
            ))}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between gap-2 text-xs font-mono text-muted-foreground">
          {lens === "released" && entry.days_since_release != null && (
            <span>
              {entry.days_since_release === 0
                ? "Released today"
                : `${entry.days_since_release}d ago`}
            </span>
          )}
          {lens === "upcoming" && entry.release_date && (
            <span>{new Date(entry.release_date).toLocaleDateString()}</span>
          )}
          {lens === "upcoming" && !entry.release_date && <span>Date TBA</span>}
          {lens === "added" && (
            <span>added {relativeTime(entry.discovered_at)}</span>
          )}

          {lens !== "upcoming" && (
            <span data-testid="review-status">
              {hasReviews ? (
                <span style={{ color: scoreColor }}>{score}%</span>
              ) : reviewCount > 0 ? (
                <span>Reviews coming in · {reviewCount}</span>
              ) : (
                <span>No reviews yet</span>
              )}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export function NewReleasesClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Validate URL params against the allowed sets so an invalid/stale deep link
  // falls back to sensible defaults rather than rendering no active tab or
  // pushing `window=foo` to the API (which would 400 and leave an empty grid).
  const lens = parseLens(searchParams.get("lens"));
  const window = parseWindow(searchParams.get("window"));
  // Clamp page to a positive integer. `Number("foo")` is NaN, `Number("0")` is
  // 0, `Number("-1")` is -1 — all of which would 422 on the API. Normalize
  // before we use it anywhere.
  const pageRaw = Number(searchParams.get("page") ?? "1");
  const page = Number.isFinite(pageRaw) && pageRaw >= 1 ? Math.floor(pageRaw) : 1;
  const genre = searchParams.get("genre") || "";
  const tag = searchParams.get("tag") || "";

  const [state, setState] = useState<FeedState>(INITIAL);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);

  // Fetch genre/tag option lists once on mount.
  useEffect(() => {
    fetch("/api/genres")
      .then((r) => r.json())
      .then((data) => setGenres(Array.isArray(data) ? data : []))
      .catch(() => {});
    fetch("/api/tags/top?limit=40")
      .then((r) => r.json())
      .then((data) => setTags(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  const updateParams = useCallback(
    (updates: Record<string, string | undefined>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(updates)) {
        if (v) params.set(k, v);
        else params.delete(k);
      }
      if (!("page" in updates)) params.delete("page");
      router.push(`?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    const opts = { page, pageSize: PER_PAGE, genre: genre || null, tag: tag || null };
    (async () => {
      try {
        if (lens === "released") {
          const data = await getNewReleasesReleased(window, opts);
          if (!cancelled)
            setState({ items: data.items, total: data.total, counts: data.counts, buckets: null, loading: false });
        } else if (lens === "upcoming") {
          const data = await getNewReleasesUpcoming(opts);
          if (!cancelled)
            setState({ items: data.items, total: data.total, counts: null, buckets: data.buckets, loading: false });
        } else {
          const data = await getNewReleasesAdded(window, opts);
          if (!cancelled)
            setState({ items: data.items, total: data.total, counts: data.counts, buckets: null, loading: false });
        }
      } catch {
        if (!cancelled) setState({ ...INITIAL, loading: false });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [lens, window, page, genre, tag]);

  const totalPages = Math.max(1, Math.ceil(state.total / PER_PAGE));

  const activeGenreName = genres.find((g) => g.slug === genre)?.name ?? genre;
  const activeTagName = tags.find((t) => t.slug === tag)?.name ?? tag;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <h1
          className="font-serif text-4xl font-bold mb-2"
          style={{ letterSpacing: "-0.03em" }}
        >
          New Releases
        </h1>
        <p className="text-sm text-muted-foreground font-mono mb-8">
          Fresh from Steam — what just shipped, what&apos;s coming, what&apos;s new.
        </p>

        {/* Lens tabs */}
        <div className="flex gap-1 mb-6 border-b border-border" data-testid="lens-tabs">
          {LENSES.map((l) => {
            const active = lens === l.key;
            const Icon = l.key === "released" ? Sparkles : l.key === "upcoming" ? Calendar : Clock;
            return (
              <button
                key={l.key}
                onClick={() => updateParams({ lens: l.key })}
                data-testid={`lens-${l.key}`}
                aria-pressed={active}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-mono uppercase tracking-widest transition-colors -mb-px border-b-2 ${
                  active
                    ? "text-foreground border-foreground"
                    : "text-muted-foreground hover:text-foreground border-transparent"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {l.label}
              </button>
            );
          })}
        </div>

        {/* Window pills (Released + Just Added) */}
        {lens !== "upcoming" && (
          <div className="flex flex-wrap gap-2 mb-4" data-testid="window-pills">
            {WINDOWS.map((w) => {
              const active = window === w.key;
              const count = state.counts?.[w.key] ?? null;
              return (
                <button
                  key={w.key}
                  onClick={() => updateParams({ window: w.key })}
                  data-testid={`window-${w.key}`}
                  aria-pressed={active}
                  className={`px-3 py-1.5 rounded-full text-xs font-mono uppercase tracking-widest transition-colors ${
                    active ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                  }`}
                  style={{
                    background: active ? "var(--card)" : "transparent",
                    border: `1px solid ${active ? "var(--foreground)" : "var(--border)"}`,
                  }}
                >
                  {w.label}
                  {count != null && (
                    <span className="ml-1.5 tabular-nums opacity-70">{count}</span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {/* Filter row: genre + tag selects, result count */}
        <div className="flex flex-wrap items-center gap-2 mb-6" data-testid="filter-row">
          <select
            data-testid="genre-filter"
            value={genre}
            onChange={(e) => updateParams({ genre: e.target.value || undefined })}
            className="px-3 py-1.5 rounded-full text-xs font-mono bg-transparent text-foreground/80 hover:text-foreground transition-colors"
            style={{ border: "1px solid var(--border)" }}
          >
            <option value="">All genres</option>
            {genres.map((g) => (
              <option key={g.id} value={g.slug}>{g.name}</option>
            ))}
          </select>

          <select
            data-testid="tag-filter"
            value={tag}
            onChange={(e) => updateParams({ tag: e.target.value || undefined })}
            className="px-3 py-1.5 rounded-full text-xs font-mono bg-transparent text-foreground/80 hover:text-foreground transition-colors"
            style={{ border: "1px solid var(--border)" }}
          >
            <option value="">All tags</option>
            {tags.map((t) => (
              <option key={t.id} value={t.slug}>{t.name}</option>
            ))}
          </select>

          {(genre || tag) && (
            <button
              onClick={() => updateParams({ genre: undefined, tag: undefined })}
              data-testid="clear-filters"
              className="flex items-center gap-1 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-3 h-3" /> Clear filters
            </button>
          )}

          <span
            className="ml-auto text-xs font-mono text-muted-foreground tabular-nums"
            data-testid="result-count"
          >
            {state.loading ? " " : `${state.total.toLocaleString()} games`}
          </span>
        </div>

        {/* Active filter summary chips */}
        {(genre || tag) && (
          <div className="flex flex-wrap gap-2 mb-4 text-xs font-mono text-muted-foreground">
            {genre && (
              <span className="px-2 py-0.5 rounded-full" style={{ border: "1px solid var(--border)" }}>
                Genre: <span className="text-foreground">{activeGenreName}</span>
              </span>
            )}
            {tag && (
              <span className="px-2 py-0.5 rounded-full" style={{ border: "1px solid var(--border)" }}>
                Tag: <span className="text-foreground">{activeTagName}</span>
              </span>
            )}
          </div>
        )}

        {/* Upcoming buckets */}
        {lens === "upcoming" && state.buckets && (
          <div className="flex gap-2 mb-6 text-xs font-mono text-muted-foreground" data-testid="upcoming-buckets">
            <span>This week: <strong>{state.buckets.this_week}</strong></span>
            <span>·</span>
            <span>This month: <strong>{state.buckets.this_month}</strong></span>
            <span>·</span>
            <span>Later: <strong>{state.buckets.this_quarter}</strong></span>
            <span>·</span>
            <span>TBA: <strong>{state.buckets.tba}</strong></span>
          </div>
        )}

        {/* Grid */}
        {state.loading ? (
          <div className="text-center py-20" data-testid="loading">
            <p className="text-base text-muted-foreground font-mono">Loading...</p>
          </div>
        ) : state.items.length === 0 ? (
          <div className="text-center py-20" data-testid="empty-state">
            <p className="text-base text-muted-foreground mb-2">
              No games match these filters.
            </p>
            {(genre || tag) && (
              <button
                onClick={() => updateParams({ genre: undefined, tag: undefined })}
                className="text-sm font-mono text-foreground underline mr-3"
              >
                Clear filters
              </button>
            )}
            {lens !== "upcoming" && window !== "quarter" && (
              <button
                onClick={() => updateParams({ window: "quarter" })}
                className="text-sm font-mono text-foreground underline mr-3"
              >
                Try This Quarter →
              </button>
            )}
            <Link
              href="/search"
              className="text-sm font-mono text-foreground underline"
            >
              Browse the full catalog →
            </Link>
          </div>
        ) : (
          <div
            className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4"
            data-testid="feed-grid"
          >
            {state.items.map((it) => (
              <FeedCard key={it.appid} entry={it} lens={lens} />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-8">
            <button
              onClick={() => updateParams({ page: String(page - 1) })}
              disabled={page <= 1}
              className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
            >
              <ChevronLeft className="w-3 h-3" /> Prev
            </button>
            <span className="text-sm font-mono text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => updateParams({ page: String(page + 1) })}
              disabled={page >= totalPages}
              className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
            >
              Next <ChevronRight className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
