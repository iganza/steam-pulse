"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { X, Plus, Search } from "lucide-react";
import { getGames, getGameReport } from "@/lib/api";
import { cacheGameMeta } from "@/lib/use-compare-data";
import type { Game } from "@/lib/types";

interface GamePickerProps {
  selectedAppids: number[];
  maxGames: number;
  isPro: boolean;
  onAdd: (appid: number) => void;
  onRemove: (appid: number) => void;
  onClear: () => void;
}

/** Minimal pill using data we cached from picker search (or rehydrated from meta cache). */
interface PillData {
  appid: number;
  name: string;
  header_image: string | null;
}

const pillCache = new Map<number, PillData>();

export function GamePicker({
  selectedAppids,
  maxGames,
  isPro,
  onAdd,
  onRemove,
  onClear,
}: GamePickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Game[]>([]);
  const [loading, setLoading] = useState(false);
  const [pills, setPills] = useState<PillData[]>(() =>
    selectedAppids.map((id) => pillCache.get(id) ?? { appid: id, name: `App ${id}`, header_image: null }),
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const canAdd = selectedAppids.length < maxGames;

  // Rehydrate pill labels for appids we don't know yet.
  useEffect(() => {
    const next = selectedAppids.map(
      (id) => pillCache.get(id) ?? { appid: id, name: `App ${id}`, header_image: null },
    );
    setPills(next);

    // Fetch any unknown ones via the per-appid report endpoint.
    const unknown = selectedAppids.filter((id) => !pillCache.get(id));
    if (unknown.length === 0) return;
    const controller = new AbortController();
    (async () => {
      // /api/games/{appid}/report returns the full Steam projection under
      // res.game; pull pill + cache meta straight from there. Fetch in
      // parallel, then commit pillCache + setPills once for the whole batch.
      const settled = await Promise.allSettled(
        unknown.map((id) => getGameReport(id, controller.signal)),
      );
      if (controller.signal.aborted) return;
      const fresh: PillData[] = [];
      settled.forEach((result, idx) => {
        if (result.status !== "fulfilled") return;
        const id = unknown[idx];
        const g = result.value.game;
        if (!g?.name) return;
        const p: PillData = {
          appid: id,
          name: g.name,
          header_image: g.header_image ?? null,
        };
        pillCache.set(id, p);
        // review_count_english stays aligned with positive_pct /
        // review_score_desc; fall back to all-language review_count.
        cacheGameMeta({
          appid: id,
          name: g.name,
          slug: g.slug ?? String(id),
          header_image: g.header_image ?? null,
          positive_pct: g.positive_pct ?? null,
          review_score_desc: g.review_score_desc ?? null,
          review_count: g.review_count_english ?? g.review_count ?? null,
          price_usd: g.price_usd ?? null,
          is_free: g.is_free ?? null,
          release_date: g.release_date ?? null,
        });
        fresh.push(p);
      });
      if (fresh.length === 0) return;
      const byId = new Map(fresh.map((p) => [p.appid, p]));
      setPills((prev) => prev.map((x) => byId.get(x.appid) ?? x));
    })();
    return () => {
      controller.abort();
    };
  }, [selectedAppids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  // Debounced search.
  useEffect(() => {
    if (!open || !query.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const res = await getGames({ q: query, limit: 8 }, controller.signal);
        if (!controller.signal.aborted) setResults(res.games);
      } catch {
        if (!controller.signal.aborted) setResults([]);
      } finally {
        // Always clear loading — even on abort — so it can't get stuck true
        // if the popover closes mid-flight.
        setLoading(false);
      }
    }, 250);
    return () => {
      controller.abort();
      clearTimeout(t);
      setLoading(false);
    };
  }, [query, open]);

  // Close on Escape / outside click.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function onClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("keydown", onKey);
      document.addEventListener("mousedown", onClick);
    }
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  function handleAdd(game: Game) {
    if (selectedAppids.includes(game.appid)) {
      setOpen(false);
      setQuery("");
      return;
    }
    const p: PillData = {
      appid: game.appid,
      name: game.name,
      header_image: game.header_image ?? null,
    };
    pillCache.set(game.appid, p);
    cacheGameMeta({
      appid: game.appid,
      name: game.name,
      slug: game.slug,
      header_image: game.header_image ?? null,
      positive_pct: game.positive_pct ?? null,
      review_score_desc: game.review_score_desc ?? null,
      review_count: game.review_count ?? null,
      price_usd: game.price_usd ?? null,
      is_free: game.is_free ?? null,
      release_date: game.release_date ?? null,
    });
    onAdd(game.appid);
    setOpen(false);
    setQuery("");
  }

  return (
    <div
      ref={containerRef}
      data-testid="compare-picker"
      className="rounded-xl bg-card border border-border p-4"
    >
      <div className="flex items-center gap-3 flex-wrap">
        {pills.map((p) => (
          <div
            key={p.appid}
            data-testid={`compare-pill-${p.appid}`}
            className="flex items-center gap-2 h-9 rounded-full bg-background border border-border pr-2"
          >
            {p.header_image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={p.header_image}
                alt=""
                className="h-9 w-[72px] object-cover rounded-l-full"
              />
            ) : (
              <div className="h-9 w-[72px] rounded-l-full bg-muted" />
            )}
            <span className="text-sm font-medium truncate max-w-[140px]">{p.name}</span>
            <button
              type="button"
              aria-label={`Remove ${p.name}`}
              onClick={() => onRemove(p.appid)}
              className="ml-1 p-1 rounded-full hover:bg-border transition"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        {canAdd ? (
          <div className="relative">
            <button
              type="button"
              data-testid="compare-add-button"
              onClick={() => {
                setOpen((v) => !v);
                setTimeout(() => inputRef.current?.focus(), 0);
              }}
              className="flex items-center gap-2 h-9 px-3 rounded-full border border-dashed border-border hover:border-[color:var(--teal)] text-sm text-muted-foreground hover:text-foreground transition"
            >
              <Plus className="w-4 h-4" />
              Add game
            </button>
            {open && (
              <div
                data-testid="compare-search-popover"
                className="absolute z-50 mt-2 left-0 w-[360px] rounded-xl bg-popover border border-border shadow-xl"
              >
                <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
                  <Search className="w-4 h-4 text-muted-foreground" />
                  <input
                    ref={inputRef}
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search games…"
                    className="flex-1 bg-transparent outline-none text-sm"
                  />
                </div>
                <div className="max-h-72 overflow-y-auto">
                  {loading && (
                    <div className="p-3 space-y-2">
                      {[0, 1, 2].map((i) => (
                        <div key={i} className="h-10 rounded bg-muted animate-pulse" />
                      ))}
                    </div>
                  )}
                  {!loading && query.trim() && results.length === 0 && (
                    <div className="p-4 text-sm text-muted-foreground">
                      No games found for &quot;{query}&quot;
                    </div>
                  )}
                  {!loading &&
                    results.map((g) => {
                      const dup = selectedAppids.includes(g.appid);
                      return (
                        <button
                          key={g.appid}
                          type="button"
                          disabled={dup}
                          onClick={() => handleAdd(g)}
                          className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-background transition ${dup ? "opacity-50" : ""}`}
                        >
                          {g.header_image ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={g.header_image}
                              alt=""
                              className="w-16 h-8 object-cover rounded"
                            />
                          ) : (
                            <div className="w-16 h-8 rounded bg-muted" />
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium truncate">{g.name}</div>
                            {g.positive_pct != null && (
                              <div className="text-xs text-muted-foreground">
                                {Math.round(g.positive_pct)}% positive
                              </div>
                            )}
                          </div>
                        </button>
                      );
                    })}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-xs text-muted-foreground">
            {isPro ? (
              <>Compare up to {maxGames} games</>
            ) : (
              <Link href="/pro" className="text-[color:var(--teal)] hover:underline">
                Add up to 4 games with Pro →
              </Link>
            )}
          </div>
        )}

        {selectedAppids.length >= 2 && (
          <button
            type="button"
            onClick={onClear}
            className="ml-auto text-xs text-muted-foreground hover:text-foreground"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
