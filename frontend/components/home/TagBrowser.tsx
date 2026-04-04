"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import type { TagGroup } from "@/lib/types";

const DEFAULT_VISIBLE = 7;
const DEFAULT_EXPANDED = new Set(["Genre", "Sub-Genre", "Theme & Setting"]);

export function TagBrowser({ groups }: { groups: TagGroup[] }) {
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    () => new Set(DEFAULT_EXPANDED),
  );
  const [showAllMap, setShowAllMap] = useState<Record<string, boolean>>({});
  const [searchQuery, setSearchQuery] = useState("");

  const isSearching = searchQuery.trim().length > 0;
  const query = searchQuery.trim().toLowerCase();

  const filteredGroups = useMemo(() => {
    if (!isSearching) return groups;
    return groups
      .map((g) => ({
        ...g,
        tags: g.tags.filter((t) => t.name.toLowerCase().includes(query)),
      }))
      .filter((g) => g.tags.length > 0);
  }, [groups, query, isSearching]);

  function toggleCategory(category: string) {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) {
        next.delete(category);
      } else {
        next.add(category);
      }
      return next;
    });
  }

  function toggleShowAll(category: string) {
    setShowAllMap((prev) => ({ ...prev, [category]: !prev[category] }));
  }

  return (
    <section>
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-serif text-xl font-semibold">Browse by Tag</h2>
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search tags..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring w-48"
          />
        </div>
      </div>

      {filteredGroups.length === 0 && isSearching && (
        <p className="text-sm text-muted-foreground">
          No tags matching &ldquo;{searchQuery.trim()}&rdquo;
        </p>
      )}

      <div className="space-y-3">
        {filteredGroups.map((group) => {
          const isOpen = isSearching || expandedCategories.has(group.category);
          const showAll = showAllMap[group.category] || isSearching;
          const visibleTags = showAll
            ? group.tags
            : group.tags.slice(0, DEFAULT_VISIBLE);
          const hasMore = group.tags.length > DEFAULT_VISIBLE;

          return (
            <div key={group.category}>
              <button
                onClick={() => toggleCategory(group.category)}
                className="flex items-center gap-2 text-sm font-semibold text-foreground hover:text-foreground/80 transition-colors mb-2"
              >
                {isOpen ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
                {group.category}
                <span className="text-xs font-normal text-muted-foreground">
                  ({group.total_count})
                </span>
              </button>

              {isOpen && (
                <div className="flex flex-wrap gap-2 ml-6">
                  {visibleTags.map((tag) => (
                    <Link
                      key={tag.id}
                      href={`/tag/${tag.slug}`}
                      className="text-sm px-3 py-1.5 rounded-full font-mono transition-colors hover:text-foreground"
                      style={{
                        background: "rgba(45,185,212,0.06)",
                        border: "1px solid rgba(45,185,212,0.15)",
                        color: "var(--teal)",
                      }}
                    >
                      {tag.name}
                      {tag.game_count != null && (
                        <span className="text-muted-foreground ml-1">
                          {tag.game_count.toLocaleString()}
                        </span>
                      )}
                    </Link>
                  ))}
                  {hasMore && !showAll && (
                    <button
                      onClick={() => toggleShowAll(group.category)}
                      className="text-sm px-3 py-1.5 font-mono transition-colors"
                      style={{ color: "var(--teal)" }}
                    >
                      Show all {group.total_count} &rarr;
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
