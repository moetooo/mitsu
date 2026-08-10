export default function SectionDivider({ label = null }) {
  return (
    <div className="relative my-8 flex items-center justify-center">
      <div className="absolute inset-0 flex items-center" aria-hidden="true">
        <div className="w-full border-t border-[var(--border-color)]" />
      </div>
      <div className="relative flex items-center justify-center px-4 bg-[var(--bg-color)] text-[var(--text-muted)] text-xs font-serif-jp tracking-widest gap-2">
        <span className="text-[var(--accent-vermillion)] text-xs">❖</span>
        {label && <span className="uppercase text-[11px] font-bold text-[var(--text-muted)]">{label}</span>}
        <span className="text-[var(--accent-vermillion)] text-xs">❖</span>
      </div>
    </div>
  );
}
