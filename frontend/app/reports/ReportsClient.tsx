"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { ChevronLeft, ChevronRight, FileText, Clock, Gem } from "lucide-react";
import { getCatalogReports, getComingSoon } from "@/lib/api";
import type { CatalogReportEntry, AnalysisCandidateEntry, CatalogReportsResponse, ComingSoonResponse } from "@/lib/types";
import { RequestAnalysis } from "@/components/game/RequestAnalysis";

type Tab = "reports" | "coming-soon";

const TABS: { key: Tab; label: string }[] = [
  { key: "reports", label: "Available Reports" },
  { key: "coming-soon", label: "Coming Soon" },
];

const REPORT_SORTS = [
  { key: "last_analyzed", label: "Recently Analyzed" },
  { key: "review_count", label: "Most Reviewed" },
  { key: "positive_pct", label: "Best on Steam" },
  { key: "hidden_gem_score", label: "Hidden Gems" },
];

const CANDIDATE_SORTS = [
  { key: "request_count", label: "Most Requested" },
  { key: "review_count", label: "Most Reviews" },
];

const PER_PAGE = 24;
const VALID_TABS = new Set<string>(TABS.map((t) => t.key));

function parseTab(raw: string | null): Tab {
  return raw && VALID_TABS.has(raw) ? (raw as Tab) : "reports";
}

function scoreColor(pct: number): string {
  return pct >= 75 ? "#22c55e" : pct >= 50 ? "#f59e0b" : "#ef4444";
}

function ReportCard({ entry }: { entry: CatalogReportEntry }) {
  const href = entry.slug ? `/games/${entry.appid}/${entry.slug}` : null;
  if (!href) return null;

  const score = entry.positive_pct;
  const color = scoreColor(score ?? 0);
  const analyzed = entry.last_analyzed
    ? new Date(entry.last_analyzed).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : null;

  return (
    <Link
      href={href}
      className="group flex flex-col rounded-xl overflow-hidden transition-all duration-300 hover:scale-[1.02]"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <div className="relative aspect-[460/215] overflow-hidden bg-secondary">
        {entry.header_image && (
          <Image
            src={entry.header_image}
            alt={entry.name}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
            className="object-cover transition-transform duration-500 group-hover:scale-105"
          />
        )}
        {Math.round((entry.hidden_gem_score ?? 0) * 100) >= 70 && (
          <div
            className="absolute top-2 right-2 flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-mono uppercase tracking-widest"
            style={{ background: "rgba(201,151,60,0.85)", color: "#0c0c0f" }}
          >
            <Gem className="w-2.5 h-2.5" />
            Gem
          </div>
        )}
      </div>
      <div className="p-4 flex-1 flex flex-col">
        <h3 className="font-serif text-base font-semibold text-foreground line-clamp-1 mb-1">
          {entry.name}
        </h3>
        {entry.developer && (
          <p className="text-sm text-muted-foreground font-mono mb-2 truncate">
            {entry.developer}
          </p>
        )}
        {entry.top_tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            {entry.top_tags.slice(0, 3).map((tag) => (
              <span key={tag} className="px-1.5 py-0.5 rounded text-xs font-mono text-muted-foreground" style={{ background: "var(--secondary)" }}>
                {tag}
              </span>
            ))}
          </div>
        )}
        <div className="mt-auto flex items-center gap-2">
          {score != null && (
            <>
              <div className="flex-1 h-1 rounded-full bg-secondary overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
              </div>
              <span className="font-mono text-sm tabular-nums" style={{ color }}>{score}</span>
            </>
          )}
        </div>
        {analyzed && (
          <p className="mt-2 text-xs text-muted-foreground font-mono flex items-center gap-1">
            <Clock className="w-3 h-3" /> Analyzed {analyzed}
          </p>
        )}
      </div>
    </Link>
  );
}

function CandidateCard({ entry }: { entry: AnalysisCandidateEntry }) {
  const score = entry.positive_pct;
  const color = scoreColor(score ?? 0);

  return (
    <div
      className="flex flex-col rounded-xl overflow-hidden"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <div className="relative aspect-[460/215] overflow-hidden bg-secondary">
        {entry.header_image && (
          <Image
            src={entry.header_image}
            alt={entry.game_name}
            fill
            sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 25vw"
            className="object-cover"
          />
        )}
      </div>
      <div className="p-4 flex-1 flex flex-col">
        <h3 className="font-serif text-base font-semibold text-foreground line-clamp-1 mb-1">
          {entry.game_name}
        </h3>
        {entry.developer && (
          <p className="text-sm text-muted-foreground font-mono mb-2 truncate">
            {entry.developer}
          </p>
        )}
        <div className="flex items-center gap-2 mb-3">
          {score != null && (
            <>
              <div className="flex-1 h-1 rounded-full bg-secondary overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
              </div>
              <span className="font-mono text-sm tabular-nums" style={{ color }}>{score}</span>
            </>
          )}
        </div>
        {entry.review_count != null && (
          <p className="text-xs text-muted-foreground font-mono mb-3">
            {entry.review_count.toLocaleString()} reviews
          </p>
        )}
        <div className="mt-auto">
          <RequestAnalysis
            appid={entry.appid}
            initialRequestCount={entry.request_count}
            compact
          />
        </div>
      </div>
    </div>
  );
}

export function ReportsClient() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const tab = parseTab(searchParams.get("tab"));
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const sort = searchParams.get("sort") ?? (tab === "reports" ? "last_analyzed" : "request_count");
  const genre = searchParams.get("genre") ?? undefined;
  const tag = searchParams.get("tag") ?? undefined;

  const [reportsData, setReportsData] = useState<CatalogReportsResponse | null>(null);
  const [comingSoonData, setComingSoonData] = useState<ComingSoonResponse | null>(null);
  const [loading, setLoading] = useState(true);

  const updateUrl = useCallback((params: Record<string, string | undefined>) => {
    const sp = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(params)) {
      if (v != null && v !== "") sp.set(k, v);
      else sp.delete(k);
    }
    // Reset page when changing filters
    if ("sort" in params || "genre" in params || "tag" in params || "tab" in params) {
      sp.delete("page");
    }
    router.push(`/reports?${sp.toString()}`, { scroll: false });
  }, [searchParams, router]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    if (tab === "reports") {
      getCatalogReports({ sort, page, genre, tag }).then((data) => {
        if (!cancelled) { setReportsData(data); setLoading(false); }
      }).catch(() => { if (!cancelled) setLoading(false); });
    } else {
      getComingSoon({ sort, page }).then((data) => {
        if (!cancelled) { setComingSoonData(data); setLoading(false); }
      }).catch(() => { if (!cancelled) setLoading(false); });
    }

    return () => { cancelled = true; };
  }, [tab, sort, page, genre, tag]);

  const data = tab === "reports" ? reportsData : comingSoonData;
  const total = data?.total ?? 0;
  const pageSize = data?.page_size ?? PER_PAGE;
  const totalPages = Math.ceil(total / pageSize);
  const sortOptions = tab === "reports" ? REPORT_SORTS : CANDIDATE_SORTS;

  return (
    <main className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-serif font-bold text-foreground mb-2 flex items-center gap-3">
            <FileText className="w-7 h-7" style={{ color: "var(--teal)" }} />
            Reports
          </h1>
          <p className="text-muted-foreground font-mono text-sm">
            In-depth review analysis for Steam games
          </p>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b" style={{ borderColor: "var(--border)" }}>
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => updateUrl({ tab: t.key, sort: undefined })}
              className={`px-4 py-2 text-sm font-mono uppercase tracking-widest transition-colors border-b-2 -mb-px ${
                tab === t.key
                  ? "text-foreground border-current"
                  : "text-muted-foreground border-transparent hover:text-foreground"
              }`}
              style={tab === t.key ? { borderColor: "var(--teal)" } : undefined}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <select
            value={sort}
            onChange={(e) => updateUrl({ sort: e.target.value })}
            className="px-3 py-1.5 rounded-lg bg-card border border-border text-sm font-mono text-foreground"
          >
            {sortOptions.map((s) => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>

          {tab === "reports" && (
            <>
              {genre && (
                <button
                  onClick={() => updateUrl({ genre: undefined })}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-mono bg-secondary text-foreground"
                >
                  Genre: {genre} <span className="opacity-50">x</span>
                </button>
              )}
              {tag && (
                <button
                  onClick={() => updateUrl({ tag: undefined })}
                  className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-mono bg-secondary text-foreground"
                >
                  Tag: {tag} <span className="opacity-50">x</span>
                </button>
              )}
            </>
          )}

          <span className="ml-auto text-xs text-muted-foreground font-mono">
            {total.toLocaleString()} {tab === "reports" ? "reports" : "games awaiting analysis"}
          </span>
        </div>

        {/* Grid */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="rounded-xl animate-pulse" style={{ background: "var(--card)", border: "1px solid var(--border)", height: 280 }} />
            ))}
          </div>
        ) : tab === "reports" && reportsData ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {reportsData.items.map((entry) => (
              <ReportCard key={entry.appid} entry={entry} />
            ))}
          </div>
        ) : tab === "coming-soon" && comingSoonData ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {comingSoonData.items.map((entry) => (
              <CandidateCard key={entry.appid} entry={entry} />
            ))}
          </div>
        ) : (
          <p className="text-center text-muted-foreground font-mono py-12">No results found.</p>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-4 mt-8">
            <button
              onClick={() => updateUrl({ page: String(page - 1) })}
              disabled={page <= 1}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
            >
              <ChevronLeft className="w-4 h-4" /> Prev
            </button>
            <span className="text-sm font-mono text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => updateUrl({ page: String(page + 1) })}
              disabled={page >= totalPages}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 transition-colors"
            >
              Next <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
