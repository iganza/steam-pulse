import Link from "next/link";
import type { FrictionPoint } from "@/lib/types";
import type { GameBasics } from "./gameBasics";

interface Props {
  items: FrictionPoint[];
  totalCount: number;
  games: Record<number, GameBasics>;
}

export function FrictionList({ items, totalCount, games }: Props) {
  const preview = items.slice(0, 5);
  const remaining = Math.max(0, totalCount - preview.length);

  return (
    <section className="mb-16" data-testid="friction-list">
      <h2 className="font-serif text-2xl md:text-3xl font-bold mb-2" style={{ letterSpacing: "-0.02em" }}>
        Top 5 Friction Points
      </h2>
      <p className="text-sm font-mono mb-8" style={{ color: "var(--muted-foreground)" }}>
        Patterns appearing across multiple games in the cohort.
      </p>

      <ol className="space-y-8">
        {preview.map((item, idx) => {
          const src = games[item.source_appid];
          return (
            <li key={idx} className="flex gap-4">
              <span
                className="shrink-0 font-mono text-xs pt-1"
                style={{ color: "var(--teal)" }}
              >
                {String(idx + 1).padStart(2, "0")}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline justify-between gap-3 mb-2 flex-wrap">
                  <h3 className="font-serif text-lg font-semibold">{item.title}</h3>
                  <span
                    className="text-xs font-mono whitespace-nowrap"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    {item.mention_count} of {totalCount} games
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

      {remaining > 0 && (
        <p className="mt-8 text-sm font-mono" style={{ color: "var(--muted-foreground)" }}>
          <a href="#buy" className="underline underline-offset-2 hover:text-foreground transition-colors">
            {remaining} more friction clusters, with full quote sets, are in the PDF &rarr;
          </a>
        </p>
      )}
    </section>
  );
}
