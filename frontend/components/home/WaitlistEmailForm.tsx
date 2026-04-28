"use client";

import { useState, type FormEvent } from "react";
import { usePlausible } from "next-plausible";
import { joinWaitlist, submitWaitlistSuggestion } from "@/lib/api";

interface WaitlistEmailFormProps {
  buttonLabel: string;
  subtext: string;
  headline?: string;
  variant?: "hero" | "repeat";
}

type Status =
  | "idle"
  | "submitting"
  | "awaiting_suggestion"
  | "sending_suggestion"
  | "thanked";

type SignupStatus = "registered" | "already_registered";

export function WaitlistEmailForm({
  buttonLabel,
  subtext,
  headline,
  variant = "hero",
}: WaitlistEmailFormProps) {
  const plausible = usePlausible();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [signupStatus, setSignupStatus] = useState<SignupStatus>("registered");
  const [suggestion, setSuggestion] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (status === "submitting") return; // guard re-entrancy

    const normalizedEmail = email.trim();
    setError("");

    if (!normalizedEmail) {
      setError("Please enter your email address.");
      return;
    }

    setStatus("submitting");

    try {
      const result = await joinWaitlist(normalizedEmail);
      setSignupStatus(result.status);
      setStatus("awaiting_suggestion");
      plausible("Waitlist Signup", { props: { status: result.status, variant } });
    } catch (err) {
      console.error("Waitlist signup failed:", err);
      setError("Something went wrong. Please try again.");
      setStatus("idle");
    }
  }

  function finishWithSkip() {
    plausible("Waitlist Suggestion Skipped", { props: { variant } });
    setStatus("thanked");
  }

  function sendAnother() {
    setSuggestion("");
    setStatus("awaiting_suggestion");
  }

  async function handleSuggestionSend() {
    if (status === "sending_suggestion") return;

    const trimmed = suggestion.trim();
    if (!trimmed) {
      finishWithSkip();
      return;
    }

    setStatus("sending_suggestion");
    try {
      await submitWaitlistSuggestion(email.trim().toLowerCase(), trimmed);
      plausible("Waitlist Suggestion", { props: { length: trimmed.length, variant } });
      setSuggestion("");
      setStatus("thanked");
    } catch (err) {
      console.error("Waitlist suggestion submit failed:", err);
      finishWithSkip();
    }
  }

  if (status === "awaiting_suggestion" || status === "sending_suggestion") {
    const sending = status === "sending_suggestion";
    return (
      <div
        data-testid={`waitlist-suggestion-form-${variant}`}
        className="max-w-md mx-auto text-center"
      >
        <p className="font-mono text-xs uppercase tracking-widest text-teal">
          Thanks. One quick thing.
        </p>
        <p className="mt-2 text-sm text-muted-foreground font-mono">
          What would make Pro most useful for you? (Optional.)
        </p>
        <textarea
          rows={3}
          maxLength={2000}
          value={suggestion}
          onChange={(e) => setSuggestion(e.target.value)}
          placeholder='e.g. "track sentiment shifts on competitors", "weekly genre digest", ...'
          aria-label="Optional suggestion for Pro features"
          className="mt-3 w-full px-3 py-2 rounded-lg bg-background border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-teal-400/30 text-sm font-mono resize-none"
        />
        <div className="mt-3 flex items-center justify-center gap-3">
          <button
            type="button"
            onClick={handleSuggestionSend}
            disabled={sending}
            className="px-5 py-2.5 rounded-lg font-mono uppercase tracking-widest text-xs transition-colors disabled:opacity-50 bg-teal text-background"
          >
            {sending ? "Sending..." : "Send"}
          </button>
          <button
            type="button"
            onClick={finishWithSkip}
            disabled={sending}
            className="px-3 py-2.5 font-mono uppercase tracking-widest text-xs text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
          >
            Skip
          </button>
        </div>
      </div>
    );
  }

  if (status === "thanked") {
    return (
      <div
        data-testid={`waitlist-success-${variant}`}
        className="max-w-md mx-auto text-center"
      >
        <p className="font-mono text-base text-teal">
          {signupStatus === "registered"
            ? "You're on the list."
            : "You're already on the list."}
        </p>
        <p className="mt-2 text-sm text-muted-foreground font-mono">
          We&apos;ll email you when Pro launches.
        </p>
        <button
          type="button"
          onClick={sendAnother}
          data-testid={`waitlist-send-another-${variant}`}
          className="mt-3 font-mono uppercase tracking-widest text-xs text-muted-foreground hover:text-teal transition-colors"
        >
          Send another suggestion
        </button>
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
