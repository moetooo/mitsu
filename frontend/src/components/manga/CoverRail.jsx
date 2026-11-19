import SimilarCoverItem from './SimilarCoverItem';

/**
 * A one-line horizontal cover rail: loading skeletons, tiles, an optional
 * trailing action tile, and the empty line.
 *
 * It scrolls horizontally at every width, including mobile, and never wraps: the
 * strip is the same height on a phone as on a desktop, so a section above the
 * results does not push them down. The action tile is the "Load More" affordance
 * a rail uses — in the detail modal it opens the full "You Might Also Like"
 * page, on Explore it opens the full Trending page — so a rail never paginates
 * in place.
 */
export default function CoverRail({
  items = [],
  loading = false,
  onSelect,
  // `null` means this rail has no destination and shows no action tile.
  onAction = null,
  actionLabel = 'Load More',
  actionAriaLabel = 'Load more',
  emptyLabel = null,
  skeletonCount = 4
}) {
  if (loading) {
    return (
      <div className="flex gap-3.5 overflow-x-auto overscroll-x-contain rail-scroll pb-2 no-scrollbar">
        {Array.from({ length: skeletonCount }, (_, index) => (
          <div
            key={index}
            className="w-28 sm:w-32 h-44 shrink-0 shimmer-paper-loading rounded-2xl border border-[var(--border-color)]"
          />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return emptyLabel ? <p className="text-xs text-[var(--text-muted)] font-light">{emptyLabel}</p> : null;
  }

  return (
    <div className="flex items-stretch gap-3.5 overflow-x-auto overscroll-x-contain rail-scroll pb-2 no-scrollbar">
      {items.map(item => (
        <SimilarCoverItem key={item.id} item={item} onSelect={onSelect} />
      ))}
      {onAction && (
        <button
          type="button"
          onClick={onAction}
          aria-label={actionAriaLabel}
          className="w-28 sm:w-32 shrink-0 aspect-[2/3] rounded-2xl border border-dashed border-[var(--border-color)] bg-[var(--surface-color)] text-[var(--text-muted)] hover:border-[var(--accent-vermillion)] hover:text-[var(--accent-vermillion)] transition-all duration-200 flex flex-col items-center justify-center gap-1.5 cursor-pointer"
        >
          <span aria-hidden="true" className="font-heading text-lg">＋</span>
          <span className="text-[10px] font-mono uppercase tracking-wider">{actionLabel}</span>
        </button>
      )}
    </div>
  );
}
