interface ProofBarProps {
  totalGames: number;
  genreCount: number;
}

export function ProofBar({ totalGames, genreCount }: ProofBarProps) {
  const stats = [
    { value: totalGames.toLocaleString(), label: "games tracked" },
    { value: `${genreCount}+`, label: "genres analyzed" },
    { value: "24mo", label: "trend history" },
  ];

  return (
    <div className="flex items-center justify-center gap-6 mt-6 text-sm">
      {stats.map((stat, i) => (
        <div key={stat.label} className="flex items-center gap-1.5">
          {i > 0 && (
            <span className="text-muted-foreground/40 mr-1.5">·</span>
          )}
          <span className="font-mono font-medium" style={{ color: "var(--teal)" }}>
            {stat.value}
          </span>
          <span className="text-muted-foreground">{stat.label}</span>
        </div>
      ))}
    </div>
  );
}
