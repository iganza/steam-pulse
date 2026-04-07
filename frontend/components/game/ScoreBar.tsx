"use client";

interface ScoreBarProps {
  score: number; // 0–100
  label?: string;
  className?: string;
}

function getScoreColor(score: number): string {
  if (score >= 75) return "#22c55e";
  if (score >= 50) return "#f59e0b";
  return "#ef4444";
}

function getScoreLabel(score: number): string {
  if (score >= 90) return "Overwhelmingly Positive";
  if (score >= 75) return "Mostly Positive";
  if (score >= 60) return "Mixed";
  if (score >= 40) return "Mostly Negative";
  return "Overwhelmingly Negative";
}

export function ScoreBar({ score, label, className = "" }: ScoreBarProps) {
  const color = getScoreColor(score);
  const displayLabel = label ?? getScoreLabel(score);

  return (
    <div className={`space-y-2 ${className}`}>
      <div className="flex items-center justify-between">
        <span className="text-sm uppercase tracking-widest text-muted-foreground font-mono inline-flex items-center gap-1.5">
          <span aria-hidden>👍</span>
          Steam Sentiment
        </span>
        <span
          className="font-mono text-2xl font-bold tabular-nums"
          style={{ color }}
        >
          {score}
        </span>
      </div>
      <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
        <div
          className="h-full rounded-full score-bar-fill transition-all"
          style={
            {
              "--score-pct": `${score}%`,
              width: `${score}%`,
              background: `linear-gradient(90deg, ${color}88, ${color})`,
            } as React.CSSProperties
          }
        />
      </div>
      <p className="text-sm text-muted-foreground font-mono">{displayLabel}</p>
    </div>
  );
}
