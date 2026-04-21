import Link from "next/link";
import type { ChurnInsight } from "@/lib/types";
import { slugifyName } from "./slugify";

interface Props {
  churn: ChurnInsight;
  appidToName?: Record<number, string>;
}

function formatHour(h: number): string {
  if (h < 1) {
    const mins = Math.round(h * 60);
    return `~${mins} minutes`;
  }
  const rounded = h < 10 ? Math.round(h * 2) / 2 : Math.round(h);
  return `~${rounded} hours`;
}

export function ChurnWall({ churn, appidToName }: Props) {
  const sourceName = appidToName?.[churn.source_appid];
  const sourceSlug = sourceName ? slugifyName(sourceName) : "game";
  const sourceHref = `/games/${churn.source_appid}/${sourceSlug}`;

  return (
    <section aria-labelledby="churn-heading" className="mb-14">
      <h2
        id="churn-heading"
        className="font-serif text-2xl md:text-3xl font-semibold mb-6"
        style={{ letterSpacing: "-0.02em" }}
      >
        The Churn Wall
      </h2>
      <div
        className="rounded-xl p-6 md:p-8"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        <div className="flex flex-col md:flex-row md:items-center gap-4 md:gap-8 mb-5">
          <div>
            <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-1">
              Typical drop-off
            </p>
            <p
              className="font-serif text-4xl md:text-5xl font-bold tabular-nums"
              style={{ letterSpacing: "-0.03em", color: "#2db9d4" }}
            >
              {formatHour(churn.typical_dropout_hour)}
            </p>
          </div>
          <p className="text-base md:text-lg text-foreground/85 max-w-[48ch]">
            {churn.primary_reason}
          </p>
        </div>
        <blockquote className="pl-4 border-l-2 border-foreground/20 text-sm md:text-base italic text-foreground/70">
          &ldquo;{churn.representative_quote}&rdquo;
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
    </section>
  );
}
