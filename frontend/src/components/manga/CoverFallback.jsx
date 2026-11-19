export default function CoverFallback({ title, className = '', compact = false }) {
  return (
    <div 
      className={`w-full h-full flex flex-col items-center justify-center p-3 text-center bg-gradient-to-b from-[var(--cover-fallback-from)] via-[var(--cover-fallback-via)] to-[var(--cover-fallback-to)] border border-[var(--border-color)]/60 select-none relative overflow-hidden ${className}`}
      aria-label={title ? `${title} (cover unavailable)` : 'Cover unavailable'}
    >
      {/* Background subtle ink watermark */}
      <span className="absolute -bottom-4 -right-4 text-7xl font-heading opacity-[0.04] pointer-events-none select-none text-[var(--text-color)]">
        ❖
      </span>

      <div className={`${compact ? 'w-8 h-8 text-sm mb-1.5' : 'w-11 h-11 text-base mb-2.5'} rounded-full bg-[var(--surface-color)]/80 border border-[var(--border-color)] flex items-center justify-center shadow-inner shrink-0`}>
        <span className="font-heading text-[var(--accent-vermillion)]">❖</span>
      </div>

      {/* No title text here: every place that renders this tile already prints the
          title next to it (card footer, hero column, surprise card sheet), so the
          cover repeated it twice. `title` is still used for the accessible name. */}

      {!compact && (
        <span className="mt-2 text-[8px] sm:text-[9px] font-mono uppercase tracking-widest text-[var(--text-muted)] opacity-60">
          Cover Unavailable
        </span>
      )}
    </div>
  );
}
