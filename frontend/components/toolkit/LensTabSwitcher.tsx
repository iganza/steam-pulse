"use client";

import { Lock } from "lucide-react";
import { usePro } from "@/lib/pro";
import { LENS_REGISTRY } from "@/lib/lens-registry";
import { LensIcon } from "./LensIcon";
import type { LensId } from "@/lib/toolkit-state";

interface LensTabSwitcherProps {
  activeLens: LensId;
  visibleLenses: LensId[];
  onLensChange: (lens: LensId) => void;
  onProLensClick: (lens: LensId) => void;
}

export function LensTabSwitcher({
  activeLens,
  visibleLenses,
  onLensChange,
  onProLensClick,
}: LensTabSwitcherProps) {
  const isPro = usePro();

  const visibleDefs = LENS_REGISTRY.filter((l) =>
    visibleLenses.includes(l.id),
  );

  function handleClick(lensId: LensId, isProLens: boolean) {
    if (isProLens && !isPro) {
      onProLensClick(lensId);
    } else {
      onLensChange(lensId);
    }
  }

  return (
    <div
      className="flex gap-1 overflow-x-auto border-b scrollbar-hide"
      style={{ borderColor: "var(--border)" }}
    >
      {visibleDefs.map((def) => {
        const isActive = activeLens === def.id;
        const isLocked = def.pro && !isPro;

        return (
          <button
            key={def.id}
            onClick={() => handleClick(def.id, def.pro)}
            className={`flex items-center gap-1.5 px-3 py-2 text-sm font-mono whitespace-nowrap transition-colors border-b-2 ${
              isActive
                ? "text-foreground border-[color:var(--teal)] bg-card/50"
                : "text-muted-foreground hover:text-foreground border-transparent"
            } ${isLocked ? "opacity-60" : ""}`}
          >
            <LensIcon name={def.icon} className="w-3.5 h-3.5" />
            {def.label}
            {isLocked && <Lock className="w-3 h-3" />}
          </button>
        );
      })}
    </div>
  );
}
