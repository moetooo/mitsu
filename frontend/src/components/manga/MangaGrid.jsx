import { useMemo, useCallback } from 'react';
import MangaCard from './MangaCard';

// Column classes never change, so they live at module scope: a fresh object here
// would re-render every card on every pass.
const GRID_COLS = {
  compact: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3.5',
  standard: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6',
  large: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-8'
};

// A stable empty list, so the default prop does not hand the bookmark memo a new
// array on every render.
const NO_BOOKMARKS = [];

export default function MangaGrid({
  mangas = [],
  loading = false,
  onCardClick,
  bookmarks = NO_BOOKMARKS,
  onToggleBookmark,
  gridSize = 'standard',
  hoverAccent = 'vermillion',
  nsfwBlur = true,
  hasMore = false,
  onLoadMore = null,
  hasSearched = false,
  filtersActive = false,
  hideDivider = false,
  showRank = false,
  showMatchPct = true,
  // "All matching titles displayed" is a promise about a *result set*. A ranked
  // shelf cut at ten is not one, so it must not claim to be.
  showEndNote = true,
  // FE-06: there is no `infiniteScroll` prop any more. The sentinel and the
  // row-based auto-fetch spent DB and API budget on pages nobody asked for, and
  // three triggers were doing one job. Pagination is now the explicit button
  // below, which is the one place a page is requested.
  // FE-15/FE-33: sort is decided by the request, not by a local comparator.
  // The old pills re-ordered only the rows already loaded and reset themselves
  // when `resultKey` changed, so "Highest Rating" on page 1 could not lead to
  // the highest-rated titles on page 2. The parent owns the value and the
  // refetch; `queryActive` is false for a filter-only browse, where relevance
  // has no query to rank against.
  sort = 'default',
  onSortChange = null,
  queryActive = false
}) {
  // B-02: the predicate is derived from the saved list, not read through a ref.
  // A permanently stable identity kept every bookmark change invisible to the
  // memoized cards: the icon stayed stale until the list re-rendered. Keying the
  // memo on `bookmarks` keeps the identity steady across unrelated renders while
  // making it change when the saved list does.
  const bookmarkedIds = useMemo(
    () => new Set((Array.isArray(bookmarks) ? bookmarks : []).map(b => b && b.id)),
    [bookmarks]
  );
  const isBookmarked = useCallback((id) => bookmarkedIds.has(id), [bookmarkedIds]);

  const activeGridSize = gridSize || 'standard';
  // B-09: the grid template is derived from the density, so it is a value the
  // cards depend on rather than something computed inline. Standard and large
  // resolve to the same column count below 640px, so a density switch could
  // leave the previous gap/breakpoint classes on screen until a resize.
  const gridCols = GRID_COLS[activeGridSize] || GRID_COLS.standard;

  // FE-33: the page scrolls. The list used to switch to a react-window <List>
  // past 36 results, which is its own scroll container with a fixed height, so
  // the page ended up with two scrollbars and BackToTop (which watches the
  // window) stopped working. Rendering the same plain grid every time keeps one
  // scroller; cards stay cheap because they lazy-load covers and carry
  // `content-visibility: auto`.

  // Feature 34: Shimmer Paper Skeleton Grid Loading State
  if (loading && mangas.length === 0) {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-label="Loading titles"
        className={`grid ${gridCols}`}
      >
        {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
          <div
            key={i}
            className="aspect-[2/3] shimmer-paper-loading rounded-2xl border border-[var(--border-color)] flex flex-col items-center justify-center p-4"
          >
            <span className="text-sm font-heading text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
          </div>
        ))}
      </div>
    );
  }

  if (mangas.length === 0) {
    if (!hasSearched) return null;
    return (
      <div role="status" aria-live="polite" className="flex flex-col items-center justify-center py-20 gap-1">
        <p className="text-[var(--text-muted)] font-heading text-lg">No titles found.</p>
        {filtersActive && (
          <p className="text-[11px] font-mono text-[var(--text-muted)]">
            Loosen a filter — the score or match floor is the usual culprit.
          </p>
        )}
      </div>
    );
  }


  return (
    <div className="space-y-6 w-full">

      {/* Top Header Bar with Count & Feature 16: Quick Sort Dropdown */}
      {!hideDivider && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 border-b border-[var(--border-color)] pb-4 pt-2">
          <div className="flex items-center gap-2 text-xs font-mono text-[var(--text-muted)]">
            <span className="text-[var(--accent-vermillion)] font-heading text-sm">❖</span>
            <span className="uppercase tracking-wider font-bold text-[var(--text-color)]">
              Results ({mangas.length})
            </span>
          </div>

          {/* Feature 16: Horizontal Sort Pill Toggle Bar. The value is a server
              sort over the whole result set, not a comparator for this page. */}
          <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar max-w-full">
            <span className="text-[11px] font-mono text-[var(--text-muted)] uppercase tracking-wider shrink-0 mr-1 hidden md:inline">
              Sort results:
            </span>
            <div
              role="group"
              aria-label="Sort results"
              className="inline-flex items-center gap-1 bg-[var(--surface-color)] border border-[var(--border-color)] p-1 rounded-full shadow-xs"
            >
              {[
                { id: 'default', label: 'Default' },
                { id: 'relevance', label: 'Relevance' },
                { id: 'popularity', label: 'Popularity' }
              ].map(opt => {
                const disabled = opt.id === 'relevance' && !queryActive;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => onSortChange && onSortChange(opt.id)}
                    aria-pressed={sort === opt.id}
                    disabled={disabled}
                    title={disabled ? 'Relevance needs a search query' : undefined}
                    className={`px-3 py-1 rounded-full text-xs font-mono transition-all cursor-pointer whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed ${sort === opt.id
                      ? 'bg-[var(--accent-vermillion)] text-white font-bold shadow-xs'
                      : 'text-[var(--text-muted)] hover:text-[var(--text-color)] hover:bg-[var(--bg-color)]/60'
                      }`}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* One plain grid at every size: the page is the only scroll container. */}
      <div className={`grid ${gridCols}`}>
        {mangas.map((m, idx) => (
          <div key={m.id || idx} className="relative transform-gpu will-change-transform">
            <MangaCard
              manga={m}
              onClick={onCardClick}
              isBookmarked={isBookmarked(m.id)}
              onToggleBookmark={onToggleBookmark}
              hoverAccent={hoverAccent}
              nsfwBlur={nsfwBlur}
              showMatchPct={showMatchPct}
              rank={showRank ? (idx + 1) : null}
              priority={idx < 4}
            />
          </div>
        ))}
      </div>

      {/* FE-06: one explicit Load More button, and nothing else. */}
      {hasMore && onLoadMore && (
        <div className="text-center pt-6 pb-2">
          <button
            onClick={onLoadMore}
            disabled={loading}
            aria-busy={loading}
            className="px-8 py-3 bg-[var(--surface-color)] hover:border-[var(--accent-vermillion)] border border-[var(--border-color)] text-[var(--text-color)] rounded-full font-heading font-bold text-xs md:text-sm transition-all hover:scale-105 active:scale-95 shadow-sm cursor-pointer disabled:opacity-50"
          >
            {loading ? 'Loading...' : 'Load More'}
          </button>
        </div>
      )}

      {/* End-of-Catalog Aesthetic Indicator */}
      {showEndNote && !hasMore && mangas.length > 0 && (
        <div className="flex items-center justify-center gap-3 py-8 text-[var(--text-muted)] opacity-60 select-none">
          <div className="h-px w-16 bg-[var(--border-color)]" />
          <div className="inline-flex items-center gap-2 text-xs font-heading tracking-wider">
            <span className="w-3.5 h-3.5 flex items-center justify-center leading-none shrink-0">❖</span>
            <span className="leading-none">All matching titles displayed</span>
            <span className="w-3.5 h-3.5 flex items-center justify-center leading-none shrink-0">❖</span>
          </div>
          <div className="h-px w-16 bg-[var(--border-color)]" />
        </div>
      )}
    </div>
  );
}
