"use client";

import { getLens } from "@/lib/lens-registry";
import { LensIcon } from "../LensIcon";
import type { LensProps } from "@/lib/toolkit-state";

const def = getLens("benchmark");

export function BenchmarkLens(_props: LensProps) {
  return (
    <div className="py-20 text-center">
      <LensIcon name={def.icon} className="w-10 h-10 mx-auto mb-4 text-muted-foreground" />
      <h2 className="font-serif text-xl font-semibold mb-2">{def.label}</h2>
      <p className="text-muted-foreground text-sm">This lens is under construction.</p>
    </div>
  );
}
