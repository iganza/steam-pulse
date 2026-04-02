"use client";

import Link from "next/link";
import { Lock } from "lucide-react";
import type { LensDefinition } from "@/lib/lens-registry";

interface ProLockOverlayProps {
  lens: LensDefinition;
  onDismiss: () => void;
}

export function ProLockOverlay({ lens, onDismiss }: ProLockOverlayProps) {
  return (
    <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/80 backdrop-blur-sm rounded-xl">
      <div className="text-center max-w-sm px-6">
        <Lock
          className="w-8 h-8 mx-auto mb-3"
          style={{ color: "var(--teal)" }}
        />
        <h3 className="font-serif text-lg font-semibold mb-1">{lens.label}</h3>
        <p className="text-muted-foreground text-sm mb-4">{lens.description}</p>
        <Link
          href="/pro"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg font-mono text-sm font-semibold transition-colors"
          style={{ background: "var(--teal)", color: "var(--background)" }}
        >
          Unlock with Pro &rarr;
        </Link>
        <button
          onClick={onDismiss}
          className="block mx-auto mt-3 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
