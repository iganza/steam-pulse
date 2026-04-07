"use client";

import { useEffect } from "react";
import { useToolkitState } from "@/lib/toolkit-state";
import { useCompareData } from "@/lib/use-compare-data";
import { GamePicker } from "../compare/GamePicker";
import { MetricsGrid } from "../compare/MetricsGrid";
import { CompareRadar } from "../compare/CompareRadar";
import { PromiseGapDiff } from "../compare/PromiseGapDiff";
import { WinsSummary } from "../compare/WinsSummary";
import type { LensProps } from "@/lib/toolkit-state";

// Two well-known appids suggested on the empty state. TF2 and Apex Legends.
const SUGGESTED = [
  { appid: 440, name: "Team Fortress 2" },
  { appid: 1172470, name: "Apex Legends" },
];

function CompareSkeleton({ count }: { count: number }) {
  return (
    <div className="rounded-xl bg-card border border-border p-6" data-testid="compare-skeleton">
      <div className="grid gap-3" style={{ gridTemplateColumns: `200px repeat(${Math.max(1, count)}, minmax(0, 1fr))` }}>
        {Array.from({ length: 8 * (count + 1) }).map((_, i) => (
          <div key={i} className="h-6 rounded bg-muted/50 animate-pulse" />
        ))}
      </div>
    </div>
  );
}

function ComparePromptEmpty({ onAdd }: { onAdd: (appid: number) => void }) {
  return (
    <div
      data-testid="compare-empty-prompt"
      className="rounded-xl border-2 border-dashed border-border p-10 text-center"
    >
      <h3 className="font-serif text-lg font-semibold mb-2">Pick at least 2 games to begin</h3>
      <p className="text-sm text-muted-foreground mb-4">
        Try{" "}
        <button
          type="button"
          onClick={() => onAdd(SUGGESTED[0].appid)}
          className="hover:underline"
          style={{ color: "var(--teal)" }}
        >
          {SUGGESTED[0].name}
        </button>{" "}
        vs{" "}
        <button
          type="button"
          onClick={() => onAdd(SUGGESTED[1].appid)}
          className="hover:underline"
          style={{ color: "var(--teal)" }}
        >
          {SUGGESTED[1].name}
        </button>
        .
      </p>
    </div>
  );
}

export function CompareLens({ filters, isPro }: LensProps) {
  const [state, setState] = useToolkitState();
  const maxGames = isPro ? 4 : 2;

  // Read appids directly from URL state (not `filters.appids`) because the
  // shell's `lockedFilters` overrides `filters.appids` — on the game detail
  // page that would clobber any appid the user adds via the picker.
  // Seed once from the locked value so the current game is pre-loaded.
  const urlAppids = state.appids ?? [];
  const lockedAppids = filters.appids ?? [];

  // Seed URL once from the locked appid (used on game detail pages).
  useEffect(() => {
    if (urlAppids.length === 0 && lockedAppids.length > 0) {
      setState({ appids: lockedAppids.slice(0, maxGames) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Normalize: dedupe + trim to maxGames. Keeps URL in sync with the rendered
  // state so toggling Pro/free can't surface hidden extra appids later.
  const normalized = Array.from(new Set(urlAppids)).slice(0, maxGames);
  useEffect(() => {
    const same =
      urlAppids.length === normalized.length &&
      urlAppids.every((id, i) => id === normalized[i]);
    if (!same) setState({ appids: normalized });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlAppids.join(","), maxGames]);

  const appids = normalized;
  const { data, loading, error } = useCompareData(appids);

  const setAppids = (next: number[]) => setState({ appids: next });
  const onAdd = (appid: number) => {
    if (appids.length >= maxGames) return;
    if (appids.includes(appid)) return;
    setAppids([...appids, appid]);
  };
  const onRemove = (appid: number) => setAppids(appids.filter((a) => a !== appid));
  const onClear = () => setAppids([]);

  return (
    <div className="space-y-6" data-testid="compare-lens">
      <GamePicker
        selectedAppids={appids}
        maxGames={maxGames}
        isPro={isPro}
        onAdd={onAdd}
        onRemove={onRemove}
        onClear={onClear}
      />

      {appids.length < 2 && <ComparePromptEmpty onAdd={onAdd} />}

      {loading && appids.length >= 2 && <CompareSkeleton count={appids.length} />}

      {error && (
        <div
          className="rounded-xl border border-border p-6 text-sm"
          style={{ color: "var(--negative)" }}
          data-testid="compare-error"
        >
          {error}
        </div>
      )}

      {!loading && !error && data.length >= 2 && (
        <>
          <MetricsGrid data={data} isPro={isPro} />
          {isPro && <CompareRadar data={data} />}
          {isPro && <PromiseGapDiff data={data} />}
          <WinsSummary data={data} isPro={isPro} />
        </>
      )}
    </div>
  );
}
