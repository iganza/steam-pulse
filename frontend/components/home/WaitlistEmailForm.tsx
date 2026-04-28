"use client";

import { useState, type FormEvent } from "react";
import { usePlausible } from "next-plausible";
import { joinWaitlist } from "@/lib/api";

interface WaitlistEmailFormProps {
  buttonLabel: string;
  subtext: string;
  headline?: string;
  variant?: "hero" | "repeat";
}

type Status = "idle" | "submitting" | "registered" | "already_registered";

export function WaitlistEmailForm({
  buttonLabel,
  subtext,
  headline,
  variant = "hero",
}: WaitlistEmailFormProps) {
  const plausible = usePlausible();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;

    setStatus("submitting");
    setError("");

    try {
      const result = await joinWaitlist(email.trim());
      setStatus(result.status);
      plausible("Waitlist Signup", { props: { status: result.status, variant } });
    } catch {
      setError("Something went wrong. Please try again.");
      setStatus("idle");
    }
  }

  if (status === "registered" || status === "already_registered") {
    return (
      <div
        data-testid={`waitlist-success-${variant}`}
        className="max-w-md mx-auto text-center"
      >
        <p className="font-mono text-base text-teal">
          {status === "registered"
            ? "You're on the list."
            : "You're already on the list."}
        </p>
        <p className="mt-2 text-sm text-muted-foreground font-mono">
          We&apos;ll email you when Pro launches.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto">
      {headline && (
        <h2 className="font-serif text-xl font-semibold text-foreground text-center mb-4">
          {headline}
        </h2>
      )}
      <form
        onSubmit={handleSubmit}
        data-testid={`waitlist-form-${variant}`}
        className="flex flex-col gap-2"
      >
        <div className="flex flex-col sm:flex-row gap-2">
          <label htmlFor={`waitlist-email-${variant}`} className="sr-only">
            Email address
          </label>
          <input
            id={`waitlist-email-${variant}`}
            type="email"
            name="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            aria-label="Email address"
            required
            className="flex-1 px-3 py-2.5 rounded-lg bg-background border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 text-sm"
          />
          <button
            type="submit"
            disabled={status === "submitting"}
            className="px-5 py-2.5 rounded-lg font-mono uppercase tracking-widest text-xs transition-colors disabled:opacity-50 bg-teal text-background"
          >
            {status === "submitting" ? "Sending..." : buttonLabel}
          </button>
        </div>
        {error && <p className="text-xs text-center" style={{ color: "#ef4444" }}>{error}</p>}
      </form>
      <p className="mt-3 text-xs text-muted-foreground font-mono text-center">
        {subtext}
      </p>
    </div>
  );
}
