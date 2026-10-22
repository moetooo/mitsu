export default function CoverFallback({ title, className = '', compact = false }) {
  return (
    <div 
      className={`w-full h-full flex flex-col items-center justify-center p-3 text-center bg-gradient-to-b from-[#181920] via-[#121318] to-[#0a0a0d] border border-[var(--border-color)]/60 select-none relative overflow-hidden ${className}`}
      aria-label={title ? `${title} (cover unavailable)` : 'Cover unavailable'}
    >
      {/* Background subtle ink watermark */}
      <span className="absolute -bottom-4 -right-4 text-7xl font-serif-jp opacity-[0.04] pointer-events-none select-none text-[var(--text-color)]">
        ❖
      </span>

      <div className={`${compact ? 'w-8 h-8 text-sm mb-1.5' : 'w-11 h-11 text-base mb-2.5'} rounded-full bg-[var(--surface-color)]/80 border border-[var(--border-color)] flex items-center justify-center shadow-inner shrink-0`}>
        <span className="font-serif-jp text-[var(--accent-vermillion)]">❖</span>
      </div>

      <p className={`font-serif-jp ${compact ? 'text-[11px] line-clamp-2' : 'text-xs line-clamp-3'} font-semibold text-[var(--text-color)] opacity-90 leading-tight px-1`}>
        {title || 'Manga'}
      </p>

      {!compact && (
        <span className="mt-2 text-[8px] sm:text-[9px] font-mono uppercase tracking-widest text-[var(--text-muted)] opacity-60">
          Cover Unavailable
        </span>
      )}
    </div>
  );
}
