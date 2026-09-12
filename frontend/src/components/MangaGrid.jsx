import { useState, useEffect, useRef, useMemo } from 'react';
import { List } from 'react-window';
import MangaCard from './MangaCard';
import SectionDivider from './SectionDivider';

export default function MangaGrid({
  mangas = [],
  loading = false,
  onCardClick,
  bookmarks = [],
  onToggleBookmark,
  gridSize = 'standard',
  stampStyle = 'hanko',
  hoverAccent = 'vermillion',
  nsfwBlur = true,
  onSelectAuthor = null,
  hasMore = false,
  onLoadMore = null,
  hasSearched = false,
  hideDivider = false,
  showRank = false,
  showMatchPct = true,
  infiniteScroll = true
}) {
  const [sortBy, setSortBy] = useState('best_match');
  const isBookmarked = (id) => bookmarks.some(b => b.id === id);

  const activeGridSize = gridSize || 'standard';
  const gridColsMap = {
    compact: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3.5',
    standard: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6',
    large: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-8'
  };

  // Feature 16: Sort mangas dynamically (Memoized to prevent sorting on unrelated renders)
  const sortedMangas = useMemo(() => {
    if (sortBy === 'best_match') return mangas;
    return [...mangas].sort((a, b) => {
      if (sortBy === 'score') return (b.average_score || 0) - (a.average_score || 0);
      if (sortBy === 'newest') return (b.start_year || 0) - (a.start_year || 0);
      if (sortBy === 'popular') return (b.popularity || 0) - (a.popularity || 0);
      return 0;
    });
  }, [mangas, sortBy]);

  // Feature 74: Responsive Viewport Virtualization State
  const gridRef = useRef(null);
  const [columns, setColumns] = useState(4);
  const [viewportHeight, setViewportHeight] = useState(800);

  // Dynamic Column Count Calculation based on viewport width & grid density
  useEffect(() => {
    const updateDimensions = () => {
      const w = window.innerWidth;
      setViewportHeight(window.innerHeight);

      if (activeGridSize === 'compact') {
        if (w >= 1280) setColumns(6);
        else if (w >= 1024) setColumns(5);
        else if (w >= 768) setColumns(4);
        else if (w >= 640) setColumns(3);
        else setColumns(2);
      } else if (activeGridSize === 'large') {
        if (w >= 768) setColumns(3);
        else if (w >= 640) setColumns(2);
        else setColumns(1);
      } else {
        // Standard
        if (w >= 1024) setColumns(4);
        else if (w >= 768) setColumns(3);
        else if (w >= 640) setColumns(2);
        else setColumns(1);
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, [activeGridSize]);

  // Threshold: only virtualize when collection exceeds 36 items to prevent mounting jitter on small sets
  const shouldVirtualize = sortedMangas.length > 36;
  const estimatedRowHeight = activeGridSize === 'compact' ? 360 : activeGridSize === 'large' ? 520 : 450;
  const totalRows = Math.ceil(sortedMangas.length / columns);

  // Feature 149: Infinite Scroll with Load-More Sentinel
  const sentinelRef = useRef(null);
  const loadingRef = useRef(loading);
  loadingRef.current = loading;

  const onLoadMoreRef = useRef(onLoadMore);
  onLoadMoreRef.current = onLoadMore;

  const hasMoreRef = useRef(hasMore);
  hasMoreRef.current = hasMore;

  useEffect(() => {
    if (!infiniteScroll || !hasMore || !onLoadMore) return;

    const sentinelEl = sentinelRef.current;
    if (!sentinelEl) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        if (entry && entry.isIntersecting && !loadingRef.current && hasMoreRef.current && onLoadMoreRef.current) {
          onLoadMoreRef.current();
        }
      },
      {
        root: null,
        rootMargin: '160px 0px',
        threshold: 0.05
      }
    );

    observer.observe(sentinelEl);
    return () => {
      observer.disconnect();
    };
  }, [infiniteScroll, hasMore, onLoadMore]);

  // Feature 34: Shimmer Paper Skeleton Grid Loading State
  if (loading && mangas.length === 0) {
    return (
      <div className={`grid ${gridColsMap[activeGridSize] || gridColsMap.standard}`}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
          <div
            key={i}
            className="aspect-[2/3] shimmer-paper-loading rounded-2xl border border-[var(--border-color)] flex flex-col items-center justify-center p-4"
          >
            <span className="text-sm font-serif-jp text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
          </div>
        ))}
      </div>
    );
  }

  if (mangas.length === 0) {
    if (!hasSearched) return null;
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <p className="text-[var(--text-muted)] font-serif-jp text-lg">No titles found.</p>
      </div>
    );
  }

  // Feature 74: Virtualized Grid Render Container using react-window
  const Row = ({ index, style }) => {
    const items = sortedMangas.slice(index * columns, (index + 1) * columns);
    return (
      <div style={{ ...style, display: 'flex', alignItems: 'flex-start' }} className="pb-6">
        <div className={`w-full grid ${gridColsMap[activeGridSize] || gridColsMap.standard}`}>
          {items.map((m, colIdx) => {
            const globalIdx = index * columns + colIdx;
            return (
              <div key={m.id || globalIdx} className="relative transform-gpu will-change-transform h-full">
                <MangaCard
                  manga={m}
                  onClick={onCardClick}
                  isBookmarked={isBookmarked(m.id)}
                  onToggleBookmark={onToggleBookmark}
                  gridSize={activeGridSize}
                  stampStyle={stampStyle}
                  hoverAccent={hoverAccent}
                  nsfwBlur={nsfwBlur}
                  onSelectAuthor={onSelectAuthor}
                  showMatchPct={showMatchPct}
                  rank={showRank ? (globalIdx + 1) : null}
                />
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div ref={gridRef} className="space-y-6 w-full">

      {/* Top Header Bar with Count & Feature 16: Quick Sort Dropdown */}
      {!hideDivider && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 border-b border-[var(--border-color)] pb-4 pt-2">
          <div className="flex items-center gap-2 text-xs font-mono text-[var(--text-muted)]">
            <span className="text-[var(--accent-vermillion)] font-serif-jp text-sm">❖</span>
            <span className="uppercase tracking-wider font-bold text-[var(--text-color)]">
              Results ({mangas.length})
            </span>
            {shouldVirtualize && (
              <span className="text-[10px] bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--accent-emerald)] px-2 py-0.5 rounded-full font-mono">
                ⚡ 60fps Windowing (react-window)
              </span>
            )}
          </div>

          {/* Feature 16: Horizontal Sort Pill Toggle Bar */}
          <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar max-w-full">
            <span className="text-[11px] font-mono text-[var(--text-muted)] uppercase tracking-wider shrink-0 mr-1 hidden md:inline">
              Sort:
            </span>
            <div className="inline-flex items-center gap-1 bg-[var(--surface-color)] border border-[var(--border-color)] p-1 rounded-full shadow-xs">
              {[
                { id: 'best_match', label: 'Best Match' },
                { id: 'score', label: 'Highest Rating' },
                { id: 'newest', label: 'Newest Release' },
                { id: 'popular', label: 'Most Popular' }
              ].map(opt => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setSortBy(opt.id)}
                  className={`px-3 py-1 rounded-full text-xs font-mono transition-all cursor-pointer whitespace-nowrap ${sortBy === opt.id
                    ? 'bg-[var(--accent-vermillion)] text-white font-bold shadow-xs'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-color)] hover:bg-[var(--bg-color)]/60'
                    }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {shouldVirtualize ? (
        <List
          style={{ height: viewportHeight || 800, width: '100%' }}
          rowCount={totalRows}
          rowHeight={estimatedRowHeight}
          rowComponent={Row}
          overscanCount={2}
          className="no-scrollbar"
        />
      ) : (
        /* Standard Un-virtualized Grid Display for smaller item sets */
        <div className={`grid ${gridColsMap[activeGridSize] || gridColsMap.standard}`}>
          {sortedMangas.map((m, idx) => (
            <div key={m.id || idx} className="relative transform-gpu will-change-transform">
              <MangaCard
                manga={m}
                onClick={onCardClick}
                isBookmarked={isBookmarked(m.id)}
                onToggleBookmark={onToggleBookmark}
                gridSize={activeGridSize}
                stampStyle={stampStyle}
                hoverAccent={hoverAccent}
                nsfwBlur={nsfwBlur}
                onSelectAuthor={onSelectAuthor}
                showMatchPct={showMatchPct}
                rank={showRank ? (idx + 1) : null}
              />
            </div>
          ))}
        </div>
      )}

      {/* Feature 149: Infinite Scroll Load-More Sentinel or Manual Fallback Button */}
      {hasMore && onLoadMore && (
        <div className="text-center pt-6 pb-2">
          {infiniteScroll ? (
            <div
              ref={sentinelRef}
              onClick={() => {
                if (!loading && onLoadMore) onLoadMore();
              }}
              className="w-full flex flex-col items-center justify-center py-6 gap-3 cursor-pointer group"
              title="Click to manually load more if auto-scroll is paused"
            >
              {loading ? (
                <div className="inline-flex items-center px-6 py-2.5 rounded-full bg-[var(--surface-color)] border border-[var(--border-color)] shadow-sm select-none">
                  <span className="text-xs font-mono tracking-wider text-[var(--text-muted)] leading-none">
                    Summoning more titles...
                  </span>
                </div>
              ) : (
                <div className="inline-flex items-center px-5 py-2.5 rounded-full border border-dashed border-[var(--border-color)] text-[var(--text-muted)] group-hover:border-[var(--accent-vermillion)] group-hover:text-[var(--text-color)] transition-all select-none">
                  <span className="text-xs font-mono tracking-wider leading-none">
                    Scroll for more or click to expand
                  </span>
                </div>
              )}
            </div>
          ) : (
            <button
              onClick={onLoadMore}
              disabled={loading}
              className="px-8 py-3 bg-[var(--surface-color)] hover:border-[var(--accent-vermillion)] border border-[var(--border-color)] text-[var(--text-color)] rounded-full font-serif-jp font-bold text-xs md:text-sm transition-all hover:scale-105 active:scale-95 shadow-sm cursor-pointer disabled:opacity-50"
            >
              {loading ? 'Loading...' : 'Load More Recommendations'}
            </button>
          )}
        </div>
      )}

      {/* End-of-Catalog Aesthetic Indicator */}
      {!hasMore && mangas.length > 0 && (
        <div className="flex items-center justify-center gap-3 py-8 text-[var(--text-muted)] opacity-60 select-none">
          <div className="h-px w-16 bg-[var(--border-color)]" />
          <div className="inline-flex items-center gap-2 text-xs font-serif-jp tracking-wider">
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
