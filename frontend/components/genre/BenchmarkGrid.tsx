import Link from "next/link";
import Image from "next/image";
import type { BenchmarkGame } from "@/lib/types";
import type { GameBasics } from "./gameBasics";

interface Props {
  items: BenchmarkGame[];
  totalCount: number;
  games: Record<number, GameBasics>;
  /** When false, the "X more ... in the PDF →" CTA is hidden — #buy
   * anchors only resolve when the ReportBuyBlock is on the page. */
  hasReport: boolean;
}

function cdnHeader(appid: number): string {
  return `https://cdn.akamai.steamstatic.com/steam/apps/${appid}/header.jpg`;
}

export function BenchmarkGrid({ items, totalCount, games, hasReport }: Props) {
  // Pre-launch: raised from 3 → schema max (10) to review full synthesis content. Restore teaser cap when paywall ships.
  const preview = items.slice(0, 10);
  const remaining = Math.max(0, totalCount - preview.length);

  return (
    <section className="mb-16" data-testid="benchmark-grid">
      <h2 className="font-serif text-2xl md:text-3xl font-bold mb-2" style={{ letterSpacing: "-0.02em" }}>
        Benchmark Games
      </h2>
      <p className="text-sm font-mono mb-8" style={{ color: "var(--muted-foreground)" }}>
        The three games that define the bar in this cohort.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {preview.map((item) => {
          const src = games[item.appid];
          const headerImage = src?.header_image ?? cdnHeader(item.appid);
          const slug = src?.slug;
          const inner = (
            <div
              className="group flex flex-col rounded-xl overflow-hidden h-full transition-all duration-300 hover:scale-[1.02]"
              style={{ background: "var(--card)", border: "1px solid var(--border)" }}
            >
              <div className="relative aspect-[460/215] overflow-hidden bg-secondary">
                <Image
                  src={headerImage}
                  alt={item.name}
                  fill
                  sizes="(max-width: 768px) 100vw, 33vw"
                  className="object-cover transition-transform duration-500 group-hover:scale-105"
                />
              </div>
              <div className="p-4 flex-1 flex flex-col">
                <h3 className="font-serif text-lg font-semibold mb-2 line-clamp-1">{item.name}</h3>
                <p className="text-sm leading-relaxed flex-1" style={{ color: "var(--muted-foreground)" }}>
                  {item.why_benchmark}
                </p>
                {slug && (
                  <span
                    className="mt-4 text-xs font-mono uppercase tracking-widest"
                    style={{ color: "var(--teal)" }}
                  >
                    Read the per-game analysis &rarr;
                  </span>
                )}
              </div>
            </div>
          );
          return slug ? (
            <Link key={item.appid} href={`/games/${item.appid}/${slug}`} className="block h-full">
              {inner}
            </Link>
          ) : (
            <div key={item.appid} className="block h-full">
              {inner}
            </div>
          );
        })}
      </div>

      {remaining > 0 && hasReport && (
        <p className="mt-8 text-sm font-mono" style={{ color: "var(--muted-foreground)" }}>
          <a href="#buy" className="underline underline-offset-2 hover:text-foreground transition-colors">
            {remaining} more benchmark games, with 3&ndash;4 page deep-dives each, are in the PDF &rarr;
          </a>
        </p>
      )}
    </section>
  );
}
