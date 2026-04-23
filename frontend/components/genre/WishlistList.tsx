import Link from "next/link";
import type { WishlistItem } from "@/lib/types";
import type { GameBasics } from "./gameBasics";

interface Props {
  items: WishlistItem[];
  gameCount: number;
  games: Record<number, GameBasics>;
  /** When false, the "X more ... in the PDF →" CTA is hidden — #buy
   * anchors only resolve when the ReportBuyBlock is on the page. */
  hasReport: boolean;
}

export function WishlistList({ items, gameCount, games, hasReport }: Props) {
  // Pre-launch: raised from 3 → schema max (10) to review full synthesis content. Restore teaser cap when paywall ships.
  const preview = items.slice(0, 10);
  // Remaining = wishlist clusters beyond the preview, not games in the cohort.
  const remaining = Math.max(0, items.length - preview.length);

  return (
    <section className="mb-16" data-testid="wishlist-list">
      <h2 className="font-serif text-2xl md:text-3xl font-bold mb-2" style={{ letterSpacing: "-0.02em" }}>
        Top 3 Wishlist Features
      </h2>
      <p className="text-sm font-mono mb-8" style={{ color: "var(--muted-foreground)" }}>
        Gaps players keep asking for — the genre&rsquo;s open opportunities.
      </p>

      <ol className="space-y-8">
        {preview.map((item, idx) => {
          const src = games[item.source_appid];
          return (
            <li key={idx} className="flex gap-4">
              <span className="shrink-0 font-mono text-xs pt-1" style={{ color: "var(--teal)" }}>
                {String(idx + 1).padStart(2, "0")}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-3 mb-2 flex-wrap">
                  <h3 className="font-serif text-lg font-semibold">{item.title}</h3>
                  <span className="text-xs font-mono whitespace-nowrap" style={{ color: "var(--muted-foreground)" }}>
                    {item.mention_count} of {gameCount} games
                  </span>
                </div>
                <p className="text-base mb-3 leading-relaxed">{item.description}</p>
                <blockquote
                  className="pl-4 border-l-2 text-sm italic"
                  style={{ borderColor: "var(--teal)", color: "var(--muted-foreground)" }}
                >
                  &ldquo;{item.representative_quote}&rdquo;
                  {src && (
                    <>
                      {" — "}
                      <Link
                        href={`/games/${item.source_appid}/${src.slug}`}
                        className="not-italic underline underline-offset-2 hover:text-foreground transition-colors"
                      >
                        {src.name}
                      </Link>
                    </>
                  )}
                </blockquote>
              </div>
            </li>
          );
        })}
      </ol>

      {remaining > 0 && hasReport && (
        <p className="mt-8 text-sm font-mono" style={{ color: "var(--muted-foreground)" }}>
          <a href="#buy" className="underline underline-offset-2 hover:text-foreground transition-colors">
            {remaining} more wishlist items are in the PDF &rarr;
          </a>
        </p>
      )}
    </section>
  );
}
