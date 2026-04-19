"use client";

import { useState } from "react";
import { requestAnalysis } from "@/lib/api";
import { track } from "@/lib/track";

interface RequestAnalysisProps {
  appid: number;
  /** Required for the card variant so the copy can address the specific game.
   *  Ignored in compact mode (reports-listing tiles). */
  gameTitle?: string;
  initialRequestCount?: number;
  compact?: boolean;
}

export function RequestAnalysis({
  appid,
  gameTitle,
  initialRequestCount = 0,
  compact = false,
}: RequestAnalysisProps) {
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
      track("report_waitlist_signup", { appid, status: result.status });
    } catch {
      setError("Something went wrong. Please try again.");
      setStatus("idle");
    }
  }

  if (compact) {
    return <CompactCta
      status={status}
      showInput={showInput}
      email={email}
      requestCount={requestCount}
      error={error}
      setEmail={setEmail}
      setShowInput={setShowInput}
      setError={setError}
      handleSubmit={handleSubmit}
    />;
  }

  if (status === "requested" || status === "already_requested") {
    return (
      <section
        data-testid="report-waitlist-card"
        className="rounded-xl p-6"
        style={{ background: "var(--card)", border: "1px solid var(--border)" }}
      >
        <p className="font-mono text-base" style={{ color: "var(--teal)" }}>
          You&apos;re on the list.
        </p>
        <p className="mt-2 text-sm text-muted-foreground font-mono">
          We&apos;ll email you when {gameTitle ? `${gameTitle}'s` : "this"} report is ready.
        </p>
      </section>
    );
  }

  const heading = gameTitle
    ? `Get the full SteamPulse report on ${gameTitle} when it's ready.`
    : "Get the full SteamPulse report when it's ready.";
  const socialProof =
    requestCount > 0
      ? `${requestCount} dev${requestCount === 1 ? "" : "s"} waiting`
      : "Be the first to request this analysis.";

  return (
    <section
      data-testid="report-waitlist-card"
      className="rounded-xl p-6"
      style={{ background: "var(--card)", border: "1px solid var(--border)" }}
    >
      <h2 className="font-mono text-lg leading-snug mb-3">{heading}</h2>
      <p className="text-sm text-muted-foreground font-mono mb-4">
        A SteamPulse report covers player sentiment clusters, wishlist signals,
        retention friction points, and competitive context — cited, ~5,000 words.
      </p>
      <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground mb-4">
        {socialProof} · usually ready within 2 weeks of hitting ~20 requests
      </p>
      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            required
            className="flex-1 px-3 py-2 rounded-lg bg-background border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 text-sm"
          />
          <button
            type="submit"
            disabled={status === "submitting"}
            className="px-4 py-2 rounded-lg font-mono uppercase tracking-widest text-xs transition-colors disabled:opacity-50"
            style={{ background: "var(--teal)", color: "#0c0c0f" }}
          >
            {status === "submitting" ? "Sending..." : "Notify me"}
          </button>
        </div>
        {error && <p className="text-xs" style={{ color: "#ef4444" }}>{error}</p>}
      </form>
      <p className="mt-3 text-xs text-muted-foreground font-mono">
        No spam. One email when the report is ready. Unsubscribe anytime.
      </p>
    </section>
  );
}

interface CompactCtaProps {
  status: "idle" | "submitting" | "requested" | "already_requested";
  showInput: boolean;
  email: string;
  requestCount: number;
  error: string;
  setEmail: (v: string) => void;
  setShowInput: (v: boolean) => void;
  setError: (v: string) => void;
  handleSubmit: (e: React.FormEvent) => void;
}

function CompactCta({
  status,
  showInput,
  email,
  requestCount,
  error,
  setEmail,
  setShowInput,
  setError,
  handleSubmit,
}: CompactCtaProps) {
  if (status === "requested" || status === "already_requested") {
    return (
      <div className="flex items-center gap-2 text-xs">
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
            className="flex-1 px-3 py-1 rounded-lg bg-card border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 text-xs"
          />
          <button
            type="submit"
            disabled={status === "submitting"}
            className="px-3 py-1 rounded-lg font-mono uppercase tracking-widest text-xs transition-colors disabled:opacity-50"
            style={{ background: "var(--teal)", color: "#0c0c0f" }}
          >
            {status === "submitting" ? "..." : "Submit"}
          </button>
          <button
            type="button"
            onClick={() => { setShowInput(false); setError(""); }}
            className="px-2 rounded-lg text-muted-foreground hover:text-foreground transition-colors text-xs"
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
        className="px-3 py-1 rounded-lg font-mono uppercase tracking-widest text-xs transition-colors hover:opacity-90"
        style={{ background: "var(--teal)", color: "#0c0c0f" }}
      >
        Request Analysis
      </button>
      {requestCount > 0 && (
        <span className="text-muted-foreground font-mono text-xs">
          {requestCount} {requestCount === 1 ? "request" : "requests"}
        </span>
      )}
    </div>
  );
}
