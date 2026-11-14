// FE-25: a failed request used to look like an empty result set — the grid said
// "No titles found." whether the search truly matched nothing or the service was
// unreachable. This is the honest version: it says what happened and offers the
// one action that can help.
export default function ErrorBanner({
  message,
  onRetry,
  retryLabel = 'Try again',
  label = 'Could not load results'
}) {
  if (!message) return null;

  return (
    <div
      role="alert"
      className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-2xl border border-[var(--border-color)] bg-[var(--surface-color)] px-4 py-3"
    >
      <div className="flex items-start gap-2.5 min-w-0">
        <span aria-hidden="true" className="text-[var(--accent-vermillion)] text-sm leading-5 shrink-0">❖</span>
        <div className="min-w-0">
          <p className="text-xs font-mono uppercase tracking-wider text-[var(--text-color)]">{label}</p>
          <p className="text-xs text-[var(--text-muted)] pt-0.5">{message}</p>
        </div>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 px-4 py-1.5 rounded-full border border-[var(--border-color)] bg-[var(--bg-color)] text-[11px] font-mono uppercase tracking-widest text-[var(--text-color)] hover:border-[var(--accent-vermillion)] hover:text-[var(--accent-vermillion)] cursor-pointer"
        >
          {retryLabel}
        </button>
      )}
    </div>
  );
}
