"use client";

import { useState, useEffect, useCallback } from "react";
import { Lock, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { validateKey } from "@/lib/api";
import type { GameReport } from "@/lib/types";

const LS_KEY = "sp_license_key";

interface PremiumUnlockProps {
  appid: number;
  children: React.ReactNode;
  onUnlock: (report: GameReport) => void;
}

type State = "locked" | "open" | "loading" | "error" | "unlocked";

export function PremiumUnlock({ appid, children, onUnlock }: PremiumUnlockProps) {
  const [state, setState] = useState<State>("locked");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");

  // Auto-unlock if key is stored in localStorage
  useEffect(() => {
    const stored = localStorage.getItem(LS_KEY);
    if (!stored) return;
    void attemptUnlock(stored, true);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const attemptUnlock = useCallback(
    async (licenseKey: string, silent = false) => {
      setState("loading");
      try {
        const report = await validateKey(licenseKey, appid);
        localStorage.setItem(LS_KEY, licenseKey);
        setState("unlocked");
        onUnlock(report);
      } catch {
        if (!silent) {
          setError("Invalid or expired license key.");
        }
        setState(silent ? "locked" : "error");
        if (silent) localStorage.removeItem(LS_KEY);
      }
    },
    [appid, onUnlock],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;
    setError("");
    void attemptUnlock(key.trim());
  };

  if (state === "unlocked") {
    return <>{children}</>;
  }

  return (
    <div className="premium-overlay rounded-xl">
      {/* Blurred content preview */}
      <div className="premium-blur-content">{children}</div>

      {/* Overlay CTA */}
      <div className="absolute inset-0 z-10 flex flex-col items-center justify-end pb-10 px-6">
        {state !== "open" && state !== "loading" && state !== "error" ? (
          <button
            onClick={() => setState("open")}
            className="group flex flex-col items-center gap-4 max-w-sm text-center"
          >
            <div
              className="w-10 h-10 rounded-full flex items-center justify-center"
              style={{
                background: "rgba(45,185,212,0.12)",
                border: "1px solid rgba(45,185,212,0.3)",
              }}
            >
              <Lock className="w-4 h-4 text-teal-400" />
            </div>
            <p className="text-sm text-foreground/80 leading-relaxed">
              You&rsquo;re a developer doing pre-launch research.{" "}
              <span className="text-foreground font-medium">
                Get action items, refund signals, and feature gaps your
                competitors haven&rsquo;t fixed
              </span>{" "}
              &mdash;
            </p>
            <span
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full text-sm font-mono font-medium transition-all group-hover:scale-105"
              style={{
                background: "var(--teal)",
                color: "#0c0c0f",
              }}
            >
              Unlock for $7
            </span>
          </button>
        ) : (
          <div className="w-full max-w-sm space-y-3">
            <p className="text-xs text-center text-muted-foreground font-mono uppercase tracking-widest mb-4">
              Enter your license key
            </p>
            <form onSubmit={handleSubmit} className="space-y-3">
              <input
                type="text"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX"
                autoFocus
                disabled={state === "loading"}
                className="w-full px-4 py-3 rounded-lg bg-card border border-border font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-teal-400/30 disabled:opacity-50"
              />
              {state === "error" && (
                <p className="flex items-center gap-1.5 text-xs text-destructive font-mono">
                  <XCircle className="w-3.5 h-3.5" />
                  {error}
                </p>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setState("locked")}
                  disabled={state === "loading"}
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm text-muted-foreground border border-border hover:border-foreground/20 transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={state === "loading" || !key.trim()}
                  className="flex-1 px-4 py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50 transition-all"
                  style={{ background: "var(--teal)", color: "#0c0c0f" }}
                >
                  {state === "loading" ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Verifying
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Unlock
                    </>
                  )}
                </button>
              </div>
            </form>
            <p className="text-center text-xs text-muted-foreground">
              No key?{" "}
              <a
                href="https://steampulse.io/#pricing"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 hover:text-foreground transition-colors"
                style={{ color: "var(--teal)" }}
              >
                Get one for $7
              </a>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
