"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown, FileText, Gem, TrendingUp, Sparkles, Compass, Swords, X, Menu } from "lucide-react";
import type { Genre, TagGroup } from "@/lib/types";
import { SearchAutocomplete } from "./SearchAutocomplete";

export function Navbar() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [browseOpen, setBrowseOpen] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [genres, setGenres] = useState<Genre[]>([]);
  const [tagGroups, setTagGroups] = useState<TagGroup[]>([]);
  const browseRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (browseRef.current && !browseRef.current.contains(e.target as Node)) {
        setBrowseOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    if (!browseOpen) return;
    if (genres.length === 0) {
      fetch("/api/genres")
        .then((r) => r.json())
        .then((data) => setGenres(Array.isArray(data) ? data.slice(0, 10) : []))
        .catch(() => {});
    }
    if (tagGroups.length === 0) {
      fetch("/api/tags/grouped?limit_per_category=5")
        .then((r) => r.json())
        .then((data: TagGroup[]) => {
          if (!Array.isArray(data)) return;
          const show = ["Sub-Genre", "Theme & Setting", "Gameplay"];
          setTagGroups(data.filter((g) => show.includes(g.category)));
        })
        .catch(() => {});
    }
  }, [browseOpen, genres.length, tagGroups.length]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (query.trim()) {
      router.push(`/search?q=${encodeURIComponent(query.trim())}`);
      setQuery("");
      setMobileMenuOpen(false);
    }
  }

  return (
    <nav
      aria-label="Main navigation"
      className="sticky top-0 z-50 border-b"
      style={{
        background: "rgba(12, 12, 15, 0.92)",
        backdropFilter: "blur(12px)",
        borderColor: "var(--border)",
      }}
    >
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
        {/* Logo */}
        <Link
          href="/"
          className="font-mono text-sm font-bold tracking-widest uppercase flex-shrink-0"
          style={{ color: "var(--teal)" }}
        >
          SteamPulse
        </Link>

        {/* Desktop nav links */}
        <div className="hidden md:flex items-center gap-1 flex-shrink-0">
          {/* Browse dropdown */}
          <div ref={browseRef} className="relative">
            <button
              onClick={() => setBrowseOpen(!browseOpen)}
              className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
            >
              Browse <ChevronDown className="w-3 h-3" />
            </button>
            {browseOpen && (
              <div
                className="absolute top-full left-0 mt-1 w-[600px] rounded-xl p-4 shadow-xl"
                style={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                }}
              >
                <div className="grid grid-cols-4 gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">
                      Genres
                    </p>
                    <div className="space-y-1">
                      {genres.map((g) => (
                        <Link
                          key={g.id}
                          href={`/genre/${g.slug}`}
                          onClick={() => setBrowseOpen(false)}
                          className="block text-sm text-foreground/70 hover:text-foreground py-0.5 transition-colors"
                        >
                          {g.name}
                          {g.game_count != null && (
                            <span className="text-muted-foreground ml-1">
                              ({g.game_count.toLocaleString()})
                            </span>
                          )}
                        </Link>
                      ))}
                    </div>
                  </div>
                  {tagGroups.map((group) => (
                    <div key={group.category}>
                      <p className="text-xs uppercase tracking-widest font-mono text-muted-foreground mb-2">
                        {group.category}
                      </p>
                      <div className="space-y-1">
                        {group.tags.map((t) => (
                          <Link
                            key={t.id}
                            href={`/tag/${t.slug}`}
                            onClick={() => setBrowseOpen(false)}
                            className="block text-sm text-foreground/70 hover:text-foreground py-0.5 transition-colors"
                          >
                            {t.name}
                          </Link>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 pt-3 border-t border-border flex items-center gap-4">
                  <Link
                    href="/#browse-by-tag"
                    onClick={() => setBrowseOpen(false)}
                    className="text-xs font-mono transition-colors"
                    style={{ color: "var(--teal)" }}
                  >
                    See all tags &rarr;
                  </Link>
                  <Link
                    href="/search?sort=hidden_gem_score"
                    onClick={() => setBrowseOpen(false)}
                    className="text-xs font-mono transition-colors flex items-center gap-1"
                    style={{ color: "var(--gem)" }}
                  >
                    <Gem className="w-3 h-3" /> Hidden Gems
                  </Link>
                </div>
              </div>
            )}
          </div>

          <Link
            href="/reports"
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          >
            <FileText className="w-3 h-3" /> Reports
          </Link>
          <Link
            href="/new-releases"
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          >
            <Sparkles className="w-3 h-3" /> New Releases
          </Link>
          <Link
            href="/trending"
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          >
            <TrendingUp className="w-3 h-3" /> Trending
          </Link>
          <Link
            href="/explore"
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          >
            <Compass className="w-3 h-3" /> Explore
          </Link>
          <Link
            href="/compare"
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm font-mono uppercase tracking-widest text-muted-foreground hover:text-foreground transition-colors"
          >
            <Swords className="w-3 h-3" /> Compare
          </Link>
        </div>

        {/* Search bar — desktop */}
        <form onSubmit={handleSearch} className="hidden md:flex flex-1 max-w-xs ml-auto">
          <SearchAutocomplete
            value={query}
            onChange={setQuery}
            onSubmit={handleSearch}
            className="w-full"
            inputClassName="w-full pl-8 pr-3 py-1.5 rounded-lg bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 transition-all"
          />
        </form>

        {/* For Developers */}
        <Link
          href="/pro"
          className="hidden md:block flex-shrink-0 text-sm font-mono tracking-widest hover:text-foreground transition-colors"
          style={{ color: "var(--teal)" }}
        >
          For Developers &rarr;
        </Link>

        {/* Mobile menu toggle */}
        <button
          className="md:hidden ml-auto text-muted-foreground hover:text-foreground"
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        >
          {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Mobile menu */}
      {mobileMenuOpen && (
        <div
          className="md:hidden px-4 pb-4 space-y-3 border-t"
          style={{ borderColor: "var(--border)" }}
        >
          <form onSubmit={handleSearch} className="mt-3">
            <SearchAutocomplete
              value={query}
              onChange={setQuery}
              onSubmit={handleSearch}
              className="w-full"
              inputClassName="w-full pl-8 pr-3 py-2.5 rounded-lg bg-card border border-border text-base text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30"
            />
          </form>
          <div className="space-y-1">
            <Link href="/search" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">Browse All Games</Link>
            <Link href="/reports" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">Reports</Link>
            <Link href="/new-releases" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">New Releases</Link>
            <Link href="/trending" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">Trending</Link>
            <Link href="/explore" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">Explore</Link>
            <Link href="/compare" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base text-foreground/70 hover:text-foreground">Compare</Link>
            <Link href="/pro" onClick={() => setMobileMenuOpen(false)} className="block py-2 text-base" style={{ color: "var(--teal)" }}>For Developers &rarr;</Link>
          </div>
        </div>
      )}
    </nav>
  );
}
