import Link from "next/link";
import type { FrictionPoint } from "@/lib/types";
import { slugifyName } from "./slugify";

interface Props {
  items: FrictionPoint[];
  inputCount: number;
  appidToName?: Record<number, string>;
}

export function FrictionPoints({ items, inputCount, appidToName }: Props) {
  return (
    <section aria-labelledby="friction-heading" className="mb-14">
      <h2
        id="friction-heading"
        className="font-serif text-2xl md:text-3xl font-semibold mb-2"
        style={{ letterSpacing: "-0.02em" }}
      >
        Top {items.length} Friction Points
      </h2>
      <p className="text-sm text-muted-foreground font-mono mb-6">
        Shared complaints surfacing in at least 3 games across the cohort.
      </p>
      <ol className="space-y-8 list-none p-0">
        {items.map((item, i) => {
          const sourceName = appidToName?.[item.source_appid];
          const sourceSlug = sourceName ? slugifyName(sourceName) : "game";
          const sourceHref = `/games/${item.source_appid}/${sourceSlug}`;
          return (
            <li key={`${item.title}-${i}`} className="grid grid-cols-[2.5rem_1fr] gap-4">
              <span
                className="font-mono text-xl text-muted-foreground tabular-nums pt-0.5"
                aria-hidden
              >
                {String(i + 1).padStart(2, "0")}
              </span>
              <div>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-2">
                  <h3 className="font-serif text-lg md:text-xl font-semibold">
                    {item.title}
                  </h3>
                  <span
                    className="text-xs font-mono px-2 py-0.5 rounded-full border border-border text-muted-foreground tabular-nums"
                    aria-label={`${item.mention_count} of ${inputCount} games`}
                  >
                    {item.mention_count} of {inputCount} games
                  </span>
                </div>
                <p className="text-sm md:text-base text-foreground/80 mb-3 max-w-[62ch]">
                  {item.description}
                </p>
                <blockquote
                  className="pl-4 border-l-2 border-foreground/20 text-sm md:text-base italic text-foreground/70"
                >
                  &ldquo;{item.representative_quote}&rdquo;
                  <footer className="not-italic mt-1 text-xs font-mono text-muted-foreground">
                    {sourceName ? (
                      <>
                        —{" "}
                        <Link href={sourceHref} className="underline hover:text-foreground">
                          {sourceName}
                        </Link>
                      </>
                    ) : (
                      <Link href={sourceHref} className="underline hover:text-foreground">
                        source game →
                      </Link>
                    )}
                  </footer>
                </blockquote>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
