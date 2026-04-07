"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { X, Plus, Search } from "lucide-react";
import { getGames } from "@/lib/api";
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

    // Fetch any unknown ones via getGames.
    const unknown = selectedAppids.filter((id) => !pillCache.get(id));
    if (unknown.length === 0) return;
    const controller = new AbortController();
    (async () => {
      for (const id of unknown) {
        if (controller.signal.aborted) return;
        try {
          // We don't have a by-appid endpoint; try a broad search and match by appid.
          // The compare data loader caches the proper meta. As a fallback, leave as "App {id}".
          const res = await getGames({ q: String(id), limit: 5 }, controller.signal);
          const match = res.games.find((g) => g.appid === id);
          if (match) {
            const p: PillData = {
              appid: id,
              name: match.name,
              header_image: match.header_image ?? null,
            };
            pillCache.set(id, p);
            cacheGameMeta({
              appid: id,
              name: match.name,
              slug: match.slug,
              header_image: match.header_image ?? null,
              positive_pct: match.positive_pct ?? null,
              review_score_desc: match.review_score_desc ?? null,
              review_count: match.review_count ?? null,
              price_usd: match.price_usd ?? null,
              is_free: match.is_free ?? null,
              release_date: match.release_date ?? null,
            });
            if (!controller.signal.aborted) {
              setPills((prev) => prev.map((x) => (x.appid === id ? p : x)));
            }
          }
        } catch {
          // swallow — aborted or network error; the pill stays as "App {id}"
        }
      }
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
