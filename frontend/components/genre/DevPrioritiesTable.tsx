import type { GenreDevPriority } from "@/lib/types";

interface Props {
  rows: GenreDevPriority[];
}

export function DevPrioritiesTable({ rows }: Props) {
  return (
    <section aria-labelledby="priorities-heading" className="mb-14">
      <h2
        id="priorities-heading"
        className="font-serif text-2xl md:text-3xl font-semibold mb-2"
        style={{ letterSpacing: "-0.02em" }}
      >
        Dev Priorities
      </h2>
      <p className="text-sm text-muted-foreground font-mono mb-6">
        Ranked by cross-cohort mention count. Every row stays visible — no pagination.
      </p>
      <div className="overflow-x-auto -mx-4 md:mx-0">
        <table className="w-full text-left text-sm border-collapse min-w-[640px]">
          <thead>
            <tr className="border-b border-border">
              <th className="py-3 pr-4 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Action
              </th>
              <th className="py-3 pr-4 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Why it matters
              </th>
              <th className="py-3 pr-4 font-mono text-xs uppercase tracking-widest text-muted-foreground tabular-nums">
                Mentions
              </th>
              <th className="py-3 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                Effort
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={`${row.action}-${i}`}
                className="border-b border-border/40 last:border-b-0 align-top"
              >
                <td className="py-4 pr-4 font-serif font-medium text-foreground">
                  {row.action}
                </td>
                <td className="py-4 pr-4 text-foreground/75">{row.why_it_matters}</td>
                <td className="py-4 pr-4 font-mono tabular-nums text-muted-foreground">
                  {row.frequency}
                </td>
                <td className="py-4 font-mono text-xs uppercase tracking-widest text-muted-foreground">
                  {row.effort}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
