import type { GenreDevPriority } from "@/lib/types";

interface Props {
  items: GenreDevPriority[];
  totalCount: number;
  /** When false, the "full table in PDF →" CTA is hidden — #buy anchors
   * only resolve when the ReportBuyBlock is on the page. */
  hasReport: boolean;
}

export function DevPrioritiesTeaser({ items, totalCount, hasReport }: Props) {
  // Pre-launch: raised from 2 → schema max (10) to review full synthesis content. Restore teaser cap when paywall ships.
  const preview = items.slice(0, 10);

  return (
    <section className="mb-16" data-testid="dev-priorities">
      <h2 className="font-serif text-h2 font-bold mb-2" style={{ letterSpacing: "-0.02em" }}>
        Where Dev Time Pays Off
      </h2>
      <p className="text-sm font-mono mb-8" style={{ color: "var(--muted-foreground)" }}>
        Ranked by mention frequency across the cohort.
      </p>

      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-xs font-mono uppercase tracking-widest"
              style={{ color: "var(--muted-foreground)", borderBottom: "1px solid var(--border)" }}
            >
              <th className="text-left px-4 py-3">Action</th>
              <th className="text-left px-4 py-3 hidden md:table-cell">Why it matters</th>
              <th className="text-right px-4 py-3 whitespace-nowrap">Mentions</th>
              <th className="text-right px-4 py-3">Effort</th>
            </tr>
          </thead>
          <tbody>
            {preview.map((item, idx) => (
              <tr key={idx} style={{ borderTop: idx === 0 ? "none" : "1px solid var(--border)" }}>
                <td className="px-4 py-4 font-serif text-base font-semibold">{item.action}</td>
                <td className="px-4 py-4 hidden md:table-cell" style={{ color: "var(--muted-foreground)" }}>
                  {item.why_it_matters}
                </td>
                <td className="px-4 py-4 text-right font-mono tabular-nums">{item.frequency}</td>
                <td className="px-4 py-4 text-right font-mono uppercase text-xs tracking-widest">
                  {item.effort}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalCount > preview.length && hasReport && (
        <p className="mt-6 text-sm font-mono" style={{ color: "var(--muted-foreground)" }}>
          <a href="#buy" className="underline underline-offset-2 hover:text-foreground transition-colors">
            The full ranked priorities table &mdash; all {totalCount} actions, plus strategic recommendations &mdash; is in the PDF &rarr;
          </a>
        </p>
      )}
    </section>
  );
}
