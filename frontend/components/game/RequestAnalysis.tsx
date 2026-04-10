"use client";

import { useState } from "react";
import { requestAnalysis } from "@/lib/api";

interface RequestAnalysisProps {
  appid: number;
  gameName: string;
  initialRequestCount?: number;
  compact?: boolean;
}

export function RequestAnalysis({ appid, gameName, initialRequestCount = 0, compact = false }: RequestAnalysisProps) {
  const [email, setEmail] = useState("");
  const [showInput, setShowInput] = useState(false);
  const [status, setStatus] = useState<"idle" | "submitting" | "requested" | "already_requested">("idle");
  const [requestCount, setRequestCount] = useState(initialRequestCount);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;

    setStatus("submitting");
    setError("");

    try {
      const result = await requestAnalysis(appid, email.trim());
      setStatus(result.status);
      setRequestCount(result.request_count);
      setShowInput(false);
    } catch {
      setError("Something went wrong. Please try again.");
      setStatus("idle");
    }
  }

  if (status === "requested" || status === "already_requested") {
    return (
      <div className={`flex items-center gap-2 ${compact ? "text-xs" : "text-sm"}`}>
        <span className="font-mono" style={{ color: "var(--teal)" }}>
          {status === "requested" ? "Requested!" : "Already requested"}
        </span>
        {requestCount > 0 && (
          <span className="text-muted-foreground font-mono">
            {requestCount} {requestCount === 1 ? "request" : "requests"}
          </span>
        )}
      </div>
    );
  }

  if (showInput) {
    return (
      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <div className="flex gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            required
            className={`flex-1 px-3 rounded-lg bg-card border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 ${compact ? "py-1 text-xs" : "py-1.5 text-sm"}`}
          />
          <button
            type="submit"
            disabled={status === "submitting"}
            className={`px-3 rounded-lg font-mono uppercase tracking-widest transition-colors disabled:opacity-50 ${compact ? "py-1 text-xs" : "py-1.5 text-xs"}`}
            style={{ background: "var(--teal)", color: "#0c0c0f" }}
          >
            {status === "submitting" ? "..." : "Submit"}
          </button>
          <button
            type="button"
            onClick={() => { setShowInput(false); setError(""); }}
            className={`px-2 rounded-lg text-muted-foreground hover:text-foreground transition-colors ${compact ? "text-xs" : "text-sm"}`}
          >
            Cancel
          </button>
        </div>
        {error && <p className="text-xs" style={{ color: "#ef4444" }}>{error}</p>}
      </form>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => setShowInput(true)}
        className={`px-3 rounded-lg font-mono uppercase tracking-widest transition-colors hover:opacity-90 ${compact ? "py-1 text-xs" : "py-1.5 text-xs"}`}
        style={{ background: "var(--teal)", color: "#0c0c0f" }}
      >
        Request Analysis
      </button>
      {requestCount > 0 && (
        <span className={`text-muted-foreground font-mono ${compact ? "text-xs" : "text-sm"}`}>
          {requestCount} {requestCount === 1 ? "request" : "requests"}
        </span>
      )}
    </div>
  );
}
