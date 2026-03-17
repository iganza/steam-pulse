"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { GameCard } from "@/components/game/GameCard";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Game } from "@/lib/types";
import type { GamesResponse } from "@/lib/api";

const TABS = [
  { key: "new", label: "New on Steam", sort: "release_date" },
  { key: "analyzed", label: "Just Analyzed", sort: "last_analyzed" },
] as const;

export function NewReleasesClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") ?? "new";
  const page = Number(searchParams.get("page") ?? "1");
  const perPage = 24;

  const [games, setGames] = useState<Game[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  const activeTab = TABS.find((t) => t.key === tab) ?? TABS[0];

  const fetchGames = useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams();
    qs.set("sort", activeTab.sort);
    qs.set("limit", String(perPage));
    qs.set("offset", String((page - 1) * perPage));
    try {
      const res = await fetch(`/api/games?${qs.toString()}`);
      const data: GamesResponse = await res.json();
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
  }, [activeTab.sort, page, perPage]);

  useEffect(() => { fetchGames(); }, [fetchGames]);

  function updateParams(updates: Record<string, string>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v) params.set(k, v);
      else params.delete(k);
    }
    if (!("page" in updates)) params.delete("page");
    router.push(`?${params.toString()}`, { scroll: false });
  }

  const totalPages = Math.ceil(total / perPage);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <h1 className="font-serif text-4xl font-bold mb-6" style={{ letterSpacing: "-0.03em" }}>
          New Releases
        </h1>

        {/* Tabs */}
        <div className="flex gap-1 mb-8">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => updateParams({ tab: t.key })}
              className={`px-4 py-2 rounded-lg text-xs font-mono uppercase tracking-widest transition-colors ${
                tab === t.key
                  ? "text-foreground border border-border"
                  : "text-muted-foreground hover:text-foreground"
              }`}
              style={tab === t.key ? { background: "var(--card)" } : {}}
            >
              {t.label}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="text-center py-20">
            <p className="text-sm text-muted-foreground font-mono">Loading...</p>
          </div>
        ) : games.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-sm text-muted-foreground">No games found.</p>
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
            {games.map((game) => (
              <GameCard key={game.appid} game={game} />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-8">
            <button
              onClick={() => updateParams({ page: String(page - 1) })}
              disabled={page <= 1}
              className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
            >
              <ChevronLeft className="w-3 h-3" /> Prev
            </button>
            <span className="text-xs font-mono text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            <button
              onClick={() => updateParams({ page: String(page + 1) })}
              disabled={page >= totalPages}
              className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-mono text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
            >
              Next <ChevronRight className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
