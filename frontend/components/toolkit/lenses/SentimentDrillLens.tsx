"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Search, Loader2 } from "lucide-react";
import { getLens } from "@/lib/lens-registry";
import { LensIcon } from "../LensIcon";
import { getGames } from "@/lib/api";
import type { LensProps } from "@/lib/toolkit-state";
import type { Game } from "@/lib/types";

const def = getLens("sentiment");

export function SentimentDrillLens(_props: LensProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Game[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setResults([]);
      setOpen(false);
      setLoading(false);
      return;
    }
    setLoading(true);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      getGames({ q: query, limit: 6, sort: "review_count" })
        .then((res) => {
          setResults(res.games);
          setOpen(res.games.length > 0);
        })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [query]);

  // Close on outside click
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  function selectGame(game: Game) {
    setOpen(false);
    setQuery("");
    router.push(`/games/${game.appid}/${game.slug}`);
  }

  return (
    <div className="py-16 text-center">
      <LensIcon
        name={def.icon}
        className="w-10 h-10 mx-auto mb-4 text-muted-foreground"
      />
      <h2 className="font-serif text-xl font-semibold mb-2">{def.label}</h2>
      <p className="text-muted-foreground text-sm mb-6">
        Search for a game to see its full sentiment analysis.
      </p>
      <div ref={containerRef} className="relative max-w-sm mx-auto">
        <div className="relative">
          {loading ? (
            <Loader2
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 animate-spin pointer-events-none"
              style={{ color: "var(--teal)" }}
            />
          ) : (
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
          )}
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => {
              if (results.length > 0) setOpen(true);
            }}
            placeholder="Search for a game..."
            autoComplete="off"
            className="w-full pl-9 pr-3 py-2.5 rounded-lg bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 transition-all"
          />
        </div>

        {open && (
          <div
            className="absolute top-full left-0 right-0 mt-1 rounded-xl shadow-lg overflow-hidden z-50"
            style={{
              background: "var(--card)",
              border: "1px solid var(--border)",
            }}
          >
            {results.map((game) => (
              <button
                key={game.appid}
                onMouseDown={(e) => {
                  e.preventDefault();
                  selectGame(game);
                }}
                className="flex items-center gap-3 px-3 py-2 w-full text-left cursor-pointer transition-colors hover:bg-border/50"
              >
                <div className="flex-shrink-0 w-10 h-10 rounded-md overflow-hidden bg-secondary">
                  {game.header_image && (
                    <Image
                      src={game.header_image}
                      alt={game.name}
                      width={40}
                      height={40}
                      sizes="40px"
                      className="object-cover w-full h-full"
                    />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground font-medium truncate">
                    {game.name}
                  </p>
                  <p className="text-xs text-muted-foreground font-mono">
                    {game.developer}
                    {game.review_count != null &&
                      ` · ${game.review_count.toLocaleString()} reviews`}
                  </p>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
