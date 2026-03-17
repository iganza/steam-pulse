interface SectionLabelProps {
  children: React.ReactNode;
  className?: string;
}

export function SectionLabel({
  children,
  className = "",
}: SectionLabelProps) {
  return (
    <div className={`flex items-center gap-3 mb-5 ${className}`}>
      <h2 className="text-xs uppercase tracking-[0.18em] text-muted-foreground font-sans font-medium">
        {children}
      </h2>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}
