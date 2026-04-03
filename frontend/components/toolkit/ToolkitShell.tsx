"use client";

import { useState } from "react";
import { usePro } from "@/lib/pro";
import { useToolkitState, LENS_IDS } from "@/lib/toolkit-state";
import { getLens } from "@/lib/lens-registry";
import { FilterBar } from "./FilterBar";
import { LensTabSwitcher } from "./LensTabSwitcher";
import { LensRenderer } from "./LensRenderer";
import { ProLockOverlay } from "./ProLockOverlay";
import type { LensId } from "@/lib/toolkit-state";

interface ToolkitShellProps {
  /** Filters the user cannot remove, displayed as pinned chips. Display-only — not synced to URL. */
  lockedFilters?: Partial<
    Record<string, string | number | boolean | number[]>
  >;
  /** Default lens if none is in the URL. Falls back to "sentiment". */
  defaultLens?: LensId;
  /** Content above the filter bar (e.g., game header). */
  header?: React.ReactNode;
  /** Which lens tabs to show. Defaults to all 6. */
  visibleLenses?: LensId[];
  /** Override content for specific lenses (e.g., existing page components). */
  lensContent?: Partial<Record<LensId, React.ReactNode>>;
}

export function ToolkitShell({
  lockedFilters,
  defaultLens = "sentiment",
  header,
  visibleLenses,
  lensContent,
}: ToolkitShellProps) {
  const isPro = usePro();
  const [state, setState] = useToolkitState();
  const [proCtaLens, setProCtaLens] = useState<LensId | null>(null);

  const visible = visibleLenses ?? LENS_IDS.map((id) => id);

  // Resolve active lens: URL param > defaultLens > first visible lens
  const rawLens = state.lens ?? defaultLens;
  const activeLens = visible.includes(rawLens) ? rawLens : visible[0] ?? defaultLens;

  // If a free user navigates directly to a pro lens via URL, show the CTA overlay
  const activeLensDef = getLens(activeLens);
  const showProGate = !isPro && activeLensDef.pro;

  // Merge locked filters into the filter state for downstream consumers
  const { lens: _lens, ...urlFilters } = state;
  const effectiveFilters = lockedFilters
    ? { ...urlFilters, ...lockedFilters }
    : urlFilters;

  function handleLensChange(lens: LensId) {
    setProCtaLens(null);
    setState({ lens });
  }

  function handleProLensClick(lens: LensId) {
    setProCtaLens(lens);
  }

  return (
    <div>
      {header}

      <FilterBar
        state={state}
        setState={setState}
        lockedFilters={lockedFilters}
      />

      <LensTabSwitcher
        activeLens={activeLens}
        visibleLenses={visible}
        onLensChange={handleLensChange}
        onProLensClick={handleProLensClick}
      />

      <div className="relative min-h-[200px] mt-4">
        <LensRenderer
          lens={activeLens}
          filters={effectiveFilters}
          isPro={isPro}
          override={lensContent?.[activeLens]}
        />

        {(proCtaLens || showProGate) && (
          <ProLockOverlay
            lens={proCtaLens ? getLens(proCtaLens) : activeLensDef}
            onDismiss={() => setProCtaLens(null)}
          />
        )}
      </div>
    </div>
  );
}
