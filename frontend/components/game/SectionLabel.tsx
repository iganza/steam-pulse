interface SectionLabelProps {
  children: React.ReactNode;
  premium?: boolean;
  className?: string;
}

export function SectionLabel({
  children,
  premium,
  className = "",
}: SectionLabelProps) {
  return (
    <div className={`flex items-center gap-3 mb-5 ${className}`}>
      <h2 className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-sans font-medium">
        {children}
      </h2>
      {premium && (
        <span
          className="text-[10px] uppercase tracking-widest px-2 py-0.5 rounded font-mono"
          style={{
            background: "rgba(201, 151, 60, 0.12)",
            color: "#c9973c",
            border: "1px solid rgba(201, 151, 60, 0.2)",
          }}
        >
          Premium
        </span>
      )}
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}
