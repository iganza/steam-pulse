"use client";

import Link from "next/link";
import { Download, Lock } from "lucide-react";
import { COMPARE_METRICS, METRIC_GROUPS, computeLeaders } from "@/lib/compare-metrics";
import type { CompareGameData, MetricRow } from "@/lib/compare-types";

interface MetricsGridProps {
  data: CompareGameData[];
  isPro: boolean;
}

function nodeToText(node: unknown): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeToText).join(" ").trim();
  if (typeof node === "object") {
    const el = node as { props?: { children?: unknown } };
    if (el.props && "children" in el.props) return nodeToText(el.props.children).trim();
  }
  return "";
}

function metricCsvValue(metric: MetricRow, d: CompareGameData): string {
  const n = metric.numeric(d);
  if (n != null) return String(n);
  return nodeToText(metric.render(d));
}

function toCsv(data: CompareGameData[]): string {
  const header = ["Metric", ...data.map((d) => d.meta.name)];
  const rows = COMPARE_METRICS.map((m) => [m.label, ...data.map((d) => metricCsvValue(m, d))]);
  return [header, ...rows]
    .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
    .join("\n");
}

function downloadCsv(data: CompareGameData[]): void {
  const csv = toCsv(data);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `steampulse-compare-${data.map((d) => d.appid).join("-")}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function LeaderCell({
  metric,
  d,
  isLeader,
}: {
  metric: MetricRow;
  d: CompareGameData;
  isLeader: boolean;
}) {
  const value = metric.render(d);
  const isMissing = metric.numeric(d) == null && metric.direction !== "neutral";
  return (
    <td
      data-testid={isLeader ? "metric-leader" : undefined}
      className="relative px-4 py-3 text-sm align-top"
    >
      {isLeader && (
        <div
          className="absolute inset-y-2 left-0 w-0.5 rounded-full"
          style={{ background: "var(--teal)" }}
        />
      )}
      <div
        className={
          isMissing
            ? "text-muted-foreground"
            : isLeader
              ? "font-medium text-foreground"
              : "text-foreground/70"
        }
      >
        {value}
      </div>
    </td>
  );
}

export function MetricsGrid({ data, isPro }: MetricsGridProps) {
  if (data.length < 2) {
    return (
      <div className="rounded-xl border border-dashed border-border p-10 text-center">
        <p className="text-muted-foreground">Add at least 2 games to compare.</p>
      </div>
    );
  }

  const freeMetrics = COMPARE_METRICS.filter((m) => m.free);
  const proMetrics = COMPARE_METRICS.filter((m) => !m.free);

  function renderGroupRows(metrics: MetricRow[]) {
    return METRIC_GROUPS.flatMap((group) => {
      const rows = metrics.filter((m) => m.group === group.id);
      if (rows.length === 0) return [];
      return [
        <tr key={`group-${group.id}`}>
          <td
            colSpan={data.length + 1}
            className="px-4 pt-5 pb-2 text-xs font-mono uppercase tracking-widest"
            style={{ color: "var(--teal)" }}
          >
            {group.label}
          </td>
        </tr>,
        ...rows.map((m) => {
          const leaders = computeLeaders(m, data);
          return (
            <tr
              key={m.id}
              data-testid={`metric-row-${m.id}`}
              className="border-t border-border/50"
            >
              <td
                className="sticky left-0 z-10 bg-card px-4 py-3 text-sm text-muted-foreground whitespace-nowrap"
                title={m.info}
              >
                {m.label}
              </td>
              {data.map((d, i) => (
                <LeaderCell key={d.appid} metric={m} d={d} isLeader={leaders.has(i)} />
              ))}
            </tr>
          );
        }),
      ];
    });
  }

  return (
    <div className="rounded-xl bg-card border border-border overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-border">
        <h3 className="font-serif text-lg font-semibold">Metrics</h3>
        {isPro && (
          <button
            type="button"
            data-testid="compare-export-csv"
            onClick={() => downloadCsv(data)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-border">
              <th className="sticky left-0 z-10 bg-card px-4 py-3 text-left w-[200px]" />
              {data.map((d) => (
                <th
                  key={d.appid}
                  className="px-4 py-3 text-left min-w-[200px]"
                >
                  {d.meta.header_image && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={d.meta.header_image}
                      alt=""
                      className="w-[120px] h-14 object-cover rounded mb-2"
                    />
                  )}
                  <div className="font-semibold text-sm">{d.meta.name}</div>
                  <Link
                    href={`/games/${d.appid}/${d.meta.slug}`}
                    className="text-xs hover:underline"
                    style={{ color: "var(--teal)" }}
                  >
                    Go to game →
                  </Link>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>{renderGroupRows(freeMetrics)}</tbody>
        </table>

        {/* Pro block: either visible or blurred behind a single overlay */}
        <div className="relative">
          <div
            className={
              isPro
                ? ""
                : "blur-sm pointer-events-none select-none"
            }
            aria-hidden={!isPro}
          >
            <table className="w-full border-collapse">
              <tbody>{renderGroupRows(proMetrics)}</tbody>
            </table>
          </div>
          {!isPro && (
            <div
              data-testid="compare-pro-gate"
              className="absolute inset-0 flex items-center justify-center p-8"
            >
              <div className="rounded-xl bg-card/95 border border-border shadow-xl px-6 py-5 text-center max-w-sm">
                <Lock className="w-5 h-5 mx-auto mb-2 text-[color:var(--teal)]" />
                <div className="font-semibold mb-1">Unlock 12+ Pro metrics</div>
                <p className="text-xs text-muted-foreground mb-3">
                  Hidden Gem Score, Promise Gap diff, Churn Triggers, Content Depth, Radar
                  comparison, CSV export and more.
                </p>
                <Link
                  href="/pro"
                  className="inline-block text-sm font-medium px-4 py-2 rounded-full"
                  style={{ background: "var(--teal)", color: "#000" }}
                >
                  Upgrade to Pro →
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
