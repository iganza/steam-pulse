"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartResolver, effectiveChartType } from "@/components/toolkit/builder/ChartResolver";
import { ChartTypePicker } from "@/components/toolkit/builder/ChartTypePicker";
import { MetricPicker } from "@/components/toolkit/builder/MetricPicker";
import {
  getAnalyticsMetricsCatalog,
  getAnalyticsTrendQuery,
} from "@/lib/api";
import type {
  BuilderChartType,
  Granularity,
  MetricDefinition,
  TrendQueryResult,
} from "@/lib/types";
import { useToolkitState } from "@/lib/toolkit-state";
import type { LensProps } from "@/lib/toolkit-state";

// Free tier granularities are restricted; week is Pro-only.
const FREE_GRANULARITIES: Granularity[] = ["month", "quarter", "year"];
const PRO_GRANULARITIES: Granularity[] = ["week", "month", "quarter", "year"];

// Used when the URL has no metric selected yet — never show an empty canvas.
const DEFAULT_METRIC = "releases";

// Limit ≤1000 data points per chart (prompt perf budget). 200 is the hard cap.
const MAX_LIMIT = 200;
const DEFAULT_LIMIT = 24;

export function BuilderLens({ filters, isPro }: LensProps) {
  const [state, setState] = useToolkitState();

  const [catalog, setCatalog] = useState<MetricDefinition[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogReloadKey, setCatalogReloadKey] = useState<number>(0);

  const [result, setResult] = useState<TrendQueryResult | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [fallbackNote, setFallbackNote] = useState<string | null>(null);

  // In-memory cache — keyed by full query JSON so toggling chart type doesn't
  // re-fetch. Lives for the lifetime of the component instance.
  const cacheRef = useRef<Map<string, TrendQueryResult>>(new Map());

  // Tracks whether the user has explicitly chosen a chart type this session.
  // While false, selection changes auto-update b_chart from the first
  // metric's default_chart_hint (smart-default rule from the prompt).
  const userPickedChartRef = useRef<boolean>(false);

  // Bumped on error-state Retry to force the fetch effect to re-run even
  // when `fetchKey` (derived from URL state) is unchanged.
  const [retryKey, setRetryKey] = useState<number>(0);

  const maxMetrics = isPro ? 6 : 1;
  const allowedGranularities = isPro ? PRO_GRANULARITIES : FREE_GRANULARITIES;

  // Normalize state derived from URL: dedupe + trim to maxMetrics so a hand-
  // edited/shared URL with duplicates or >cap entries can't wedge the UI.
  const selectedIds = useMemo<string[]>(() => {
    const raw = state.b_metrics ?? [];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const id of raw) {
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push(id);
      if (out.length >= maxMetrics) break;
    }
    return out;
  }, [state.b_metrics, maxMetrics]);

  // If the URL diverges from the normalized list (dupes, over-cap, reorder
  // from Pro→free), sync it back so cap checks and share-links stay honest.
  // Depend on the RAW URL string, not the normalized one — otherwise a URL
  // like `b_metrics=releases,releases` that normalizes to the same
  // `selectedIds` wouldn't trigger the effect and stay un-deduped.
  const rawMetricsKey = (state.b_metrics ?? []).join(",");
  useEffect(() => {
    const raw = state.b_metrics ?? [];
    const same =
      raw.length === selectedIds.length &&
      raw.every((id, i) => id === selectedIds[i]);
    if (!same) setState({ b_metrics: selectedIds });
    // Depend on both the raw URL AND maxMetrics so a Pro→free transition
    // (which changes the cap but not the raw URL) still re-runs normalization
    // and clamps the URL back down.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawMetricsKey, maxMetrics]);
  const chartType: BuilderChartType = state.b_chart ?? "bar";
  const requestedGranularity: Granularity =
    state.b_gran && allowedGranularities.includes(state.b_gran)
      ? state.b_gran
      : "month";

  const normalize = state.b_norm ?? false;

  // If the URL contains a disallowed granularity (e.g. a Pro-only value on
  // free tier), sync it back to the effective fallback so URL ↔ render stay
  // in agreement.
  useEffect(() => {
    if (state.b_gran && !allowedGranularities.includes(state.b_gran)) {
      setState({ b_gran: requestedGranularity });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.b_gran, isPro]);

  const genreSlug = filters.genre || undefined;
  const tagSlug = filters.tag || undefined;

  // Fetch catalog on mount and whenever the user clicks Retry
  // (catalogReloadKey bump triggers a refetch).
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const res = await getAnalyticsMetricsCatalog(controller.signal);
        if (!controller.signal.aborted) {
          setCatalog(res.metrics);
          setCatalogError(null);
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setCatalogError(e instanceof Error ? e.message : "Failed to load catalog");
        }
      }
    })();
    return () => controller.abort();
  }, [catalogReloadKey]);

  // Smart default: if no metric is selected, pre-select one so the canvas is
  // never blank on first load. Runs after the catalog resolves.
  useEffect(() => {
    if (!catalog) return;
    if ((state.b_metrics ?? []).length > 0) return;
    const preferred = catalog.find((m) => m.id === DEFAULT_METRIC) ?? catalog[0];
    if (preferred) {
      // Seed chart type from the metric's default_chart_hint so the first
      // render matches the metric's natural shape (e.g. line for pct).
      const patch: { b_metrics: string[]; b_chart?: BuilderChartType } = {
        b_metrics: [preferred.id],
      };
      if (!state.b_chart) patch.b_chart = preferred.default_chart_hint;
      setState(patch);
    }
    // Intentionally only runs when the catalog first arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog]);

  // Resolve the MetricDefinition objects for the current selection.
  const selectedDefs = useMemo<MetricDefinition[]>(() => {
    if (!catalog) return [];
    const byId = new Map(catalog.map((m) => [m.id, m]));
    return selectedIds
      .map((id) => byId.get(id))
      .filter((m): m is MetricDefinition => Boolean(m));
  }, [catalog, selectedIds]);

  // Once the catalog has loaded, strip any URL metric ids that aren't in it
  // (e.g. a shared link referencing a removed/renamed metric). Without this,
  // `fetchKey` would keep requesting invalid ids and the lens would sit in a
  // permanent error state.
  useEffect(() => {
    if (!catalog) return;
    if (selectedIds.length === 0) return;
    const validIds = new Set(catalog.map((m) => m.id));
    const filtered = selectedIds.filter((id) => validIds.has(id));
    if (filtered.length !== selectedIds.length) {
      setState({ b_metrics: filtered });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, selectedIds.join(",")]);

  // Smart chart-type hint: while the user hasn't explicitly chosen a chart
  // type, follow the first selected metric's default_chart_hint so e.g.
  // picking a pct metric shows a line chart, not bars.
  useEffect(() => {
    if (userPickedChartRef.current) return;
    if (selectedDefs.length === 0) return;
    const hint = selectedDefs[0].default_chart_hint;
    if (hint !== state.b_chart) {
      setState({ b_chart: hint });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDefs.map((m) => m.id).join(",")]);

  // Build the fetch key — this is the cache key and the effect dep.
  const fetchKey = useMemo(() => {
    if (selectedIds.length === 0) return null;
    return JSON.stringify({
      metrics: [...selectedIds].sort(),
      granularity: requestedGranularity,
      genre: genreSlug ?? null,
      tag: tagSlug ?? null,
      limit: Math.min(DEFAULT_LIMIT, MAX_LIMIT),
    });
  }, [selectedIds, requestedGranularity, genreSlug, tagSlug]);

  // Fetch data on query change, debounced by 250ms.
  useEffect(() => {
    if (fetchKey === null) {
      setResult(null);
      return;
    }
    const cached = cacheRef.current.get(fetchKey);
    if (cached) {
      setResult(cached);
      setError(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);

    const timer = setTimeout(async () => {
      try {
        const parsed = JSON.parse(fetchKey) as {
          metrics: string[];
          granularity: Granularity;
          genre: string | null;
          tag: string | null;
          limit: number;
        };
        const res = await getAnalyticsTrendQuery(
          {
            metrics: parsed.metrics,
            granularity: parsed.granularity,
            genre: parsed.genre ?? undefined,
            tag: parsed.tag ?? undefined,
            limit: parsed.limit,
          },
          controller.signal,
        );
        if (!cancelled) {
          cacheRef.current.set(fetchKey, res);
          setResult(res);
          setLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Couldn't load chart data.");
          setLoading(false);
        }
      }
    }, 250);

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [fetchKey, retryKey]);

  // Toggle a metric on/off in the selection. Cap checks run against the
  // normalized selectedIds so hand-edited/duplicate URL state can't bypass
  // the Free-tier cap.
  const onToggleMetric = useCallback(
    (metricId: string) => {
      if (selectedIds.includes(metricId)) {
        setState({ b_metrics: selectedIds.filter((id) => id !== metricId) });
      } else if (selectedIds.length < maxMetrics) {
        setState({ b_metrics: [...selectedIds, metricId] });
      }
    },
    [selectedIds, maxMetrics, setState],
  );

  const onClearMetrics = useCallback(() => {
    setState({ b_metrics: [] });
  }, [setState]);

  const onChartTypeChange = useCallback(
    (t: BuilderChartType) => {
      userPickedChartRef.current = true;
      setFallbackNote(null);
      setState({ b_chart: t });
    },
    [setState],
  );

  const onGranularityChange = useCallback(
    (g: Granularity) => setState({ b_gran: g }),
    [setState],
  );

  const onNormalizeChange = useCallback(
    (n: boolean) => setState({ b_norm: n }),
    [setState],
  );

  // If the chosen chart type becomes incompatible with the selection,
  // surface a note so the user knows we silently fell back.
  useEffect(() => {
    if (selectedDefs.length === 0) {
      setFallbackNote(null);
      return;
    }
    const effective = effectiveChartType(selectedDefs, chartType);
    if (effective !== chartType) {
      setFallbackNote(`Switched to ${effective.replace("_", " ")} — ${chartType.replace("_", " ")} is not compatible with the current selection.`);
    } else {
      setFallbackNote(null);
    }
  }, [selectedDefs, chartType]);

  // Pro normalize toggle is only meaningful when every metric is a count.
  const allCounts =
    selectedDefs.length > 0 && selectedDefs.every((m) => m.unit === "count");

  // Clamp `normalize`: the URL can carry b_norm=1 even when the current
  // selection/chart is ineligible (e.g. a shared link with pct metrics).
  // Passing that through to ChartResolver would produce nonsensical "percent
  // share" computations on non-count series, so gate it here.
  const effectiveChart = effectiveChartType(selectedDefs, chartType);
  const normalizeEligible =
    isPro && allCounts && effectiveChart === "stacked_area" && selectedDefs.length >= 2;
  const effectiveNormalize = normalize && normalizeEligible;

  // Keep URL state honest: if the selection/chart has made normalization
  // ineligible, reset `b_norm` so the URL doesn't carry a stale "on" flag.
  useEffect(() => {
    if (!normalizeEligible && state.b_norm) {
      setState({ b_norm: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [normalizeEligible, state.b_norm]);

  // Keep URL's `b_chart` normalized to the effective chart type so that if
  // a shared link carries e.g. stacked_area+1metric, the picker's active
  // button isn't stuck disabled (which would break roving-tabindex).
  useEffect(() => {
    if (selectedDefs.length === 0) return;
    if (effectiveChart !== chartType) {
      setState({ b_chart: effectiveChart });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveChart, chartType, selectedDefs.length]);

  if (catalogError) {
    return (
      <div
        data-testid="builder-error"
        className="rounded-xl border border-border bg-card p-6 text-sm"
      >
        <p className="mb-2">Couldn&apos;t load the metric catalog.</p>
        <p className="text-muted-foreground text-xs mb-3">{catalogError}</p>
        <button
          type="button"
          className="px-3 py-1.5 rounded bg-teal-500/20 text-teal-400 text-xs"
          onClick={() => {
            setCatalogError(null);
            setCatalog(null);
            setCatalogReloadKey((k) => k + 1);
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!catalog) {
    return (
      <div data-testid="builder-loading" className="p-6 text-sm text-muted-foreground">
        Loading metric catalog…
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="builder-lens">
      <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6">
        {/* Left rail — pickers */}
        <div className="space-y-4">
          <MetricPicker
            catalog={catalog}
            selected={selectedIds}
            maxMetrics={maxMetrics}
            onToggle={onToggleMetric}
            onClear={onClearMetrics}
          />

          {!isPro && (
            <div className="text-[11px] font-mono text-muted-foreground border-l-2 border-teal-500/30 pl-2">
              <Link href="/pro" className="text-[color:var(--teal)] hover:underline">
                Upgrade to Pro
              </Link>{" "}
              to combine up to 6 metrics.
            </div>
          )}

          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
              Chart type
            </div>
            <ChartTypePicker
              value={chartType}
              selected={selectedDefs}
              onChange={onChartTypeChange}
            />
          </div>

          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
              Granularity
            </div>
            <div
              className="inline-flex rounded-lg border border-border overflow-hidden text-xs font-mono"
              role="radiogroup"
              aria-label="Granularity"
            >
              {allowedGranularities.map((g) => (
                <button
                  key={g}
                  type="button"
                  role="radio"
                  aria-checked={requestedGranularity === g}
                  data-testid={`builder-gran-${g}`}
                  onClick={() => onGranularityChange(g)}
                  className={`px-3 py-1 capitalize transition-colors ${
                    requestedGranularity === g
                      ? "bg-teal-500/20 text-teal-400"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>

          {normalizeEligible && (
            <div className="space-y-2">
              <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-mono">
                Normalize
              </div>
              <div className="inline-flex rounded-lg border border-border overflow-hidden text-xs font-mono">
                <button
                  type="button"
                  onClick={() => onNormalizeChange(true)}
                  className={`px-3 py-1 transition-colors ${
                    effectiveNormalize ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground"
                  }`}
                >
                  % Share
                </button>
                <button
                  type="button"
                  onClick={() => onNormalizeChange(false)}
                  className={`px-3 py-1 transition-colors ${
                    !normalize ? "bg-teal-500/20 text-teal-400" : "text-muted-foreground"
                  }`}
                >
                  Raw
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right — chart */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {selectedDefs.length === 0
                ? "Pick a metric to start plotting"
                : selectedDefs.map((m) => m.label).join(" · ")}
            </CardTitle>
            {fallbackNote && (
              <p
                data-testid="builder-fallback-note"
                className="text-xs text-muted-foreground"
              >
                {fallbackNote}
              </p>
            )}
          </CardHeader>
          <CardContent>
            {selectedDefs.length === 0 ? (
              <div
                data-testid="builder-empty-state"
                className="flex flex-col items-center justify-center h-[300px] text-sm text-muted-foreground gap-2"
              >
                <span>Pick a metric on the left to start plotting.</span>
              </div>
            ) : error ? (
              <div data-testid="builder-error-state" className="h-[300px] flex flex-col items-center justify-center gap-2 text-sm">
                <span>Couldn&apos;t load chart data.</span>
                <button
                  type="button"
                  className="px-3 py-1 rounded bg-teal-500/20 text-teal-400 text-xs"
                  onClick={() => {
                    // Clear cache for the current key and bump retryKey to
                    // force the fetch effect to re-run reliably, regardless
                    // of whether `fetchKey` / URL state changed.
                    if (fetchKey) cacheRef.current.delete(fetchKey);
                    setError(null);
                    setRetryKey((k) => k + 1);
                  }}
                >
                  Retry
                </button>
              </div>
            ) : loading ? (
              <div
                data-testid="builder-loading-skeleton"
                className="h-[360px] rounded bg-muted/40 animate-pulse"
              />
            ) : result && result.periods.length === 0 ? (
              <div className="h-[300px] flex items-center justify-center text-sm text-muted-foreground">
                No data for this combination of filters. Try widening the date range or removing a filter.
              </div>
            ) : result ? (
              <ChartResolver
                selected={selectedDefs}
                chartType={chartType}
                data={result.periods}
                granularity={result.granularity}
                normalize={effectiveNormalize}
              />
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
