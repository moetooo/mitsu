import { useState, useEffect, useRef } from 'react';
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
  showMatchPct = true
}) {
  const [sortBy, setSortBy] = useState('best_match');
  const isBookmarked = (id) => bookmarks.some(b => b.id === id);

  const activeGridSize = gridSize || 'standard';
  const gridColsMap = {
    compact: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3.5',
    standard: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6',
    large: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-8'
  };

  // Feature 16: Sort mangas dynamically (Preserve fetched pagination order for 'best_match')
  const sortedMangas = sortBy === 'best_match'
    ? mangas
    : [...mangas].sort((a, b) => {
        if (sortBy === 'score') return (b.average_score || 0) - (a.average_score || 0);
        if (sortBy === 'newest') return (b.start_year || 0) - (a.start_year || 0);
        if (sortBy === 'popular') return (b.popularity || 0) - (a.popularity || 0);
        return 0;
      });

  // Feature 74: Responsive Viewport Virtualization State
  const gridRef = useRef(null);
  const [columns, setColumns] = useState(4);
  const [scrollTop, setScrollTop] = useState(0);
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

  // Window Scroll Listener for Virtual Windowing
  useEffect(() => {
    let rAFId = null;
    const handleScroll = () => {
      if (rAFId) cancelAnimationFrame(rAFId);
      rAFId = requestAnimationFrame(() => {
        setScrollTop(window.scrollY || document.documentElement.scrollTop);
      });
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', handleScroll);
      if (rAFId) cancelAnimationFrame(rAFId);
    };
  }, []);

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
      <div className="text-center py-20 space-y-3 font-serif-jp">
        <p className="text-[var(--text-muted)] text-sm">No titles found.</p>
        <p className="text-[var(--text-muted)] opacity-60 text-xs">Try adjusting your query or filter parameters.</p>
      </div>
    );
  }

  // Feature 74 Virtualization Calculations
  const estimatedRowHeight = activeGridSize === 'compact' ? 360 : activeGridSize === 'large' ? 520 : 450;
  const totalRows = Math.ceil(sortedMangas.length / columns);
  const gridTopOffset = gridRef.current ? gridRef.current.offsetTop : 300;

  // Compute visible row range with overscan (renders ~8-12 cards in viewport)
  const relativeScroll = Math.max(0, scrollTop - gridTopOffset);
  const startRow = Math.max(0, Math.floor(relativeScroll / estimatedRowHeight) - 1);
  const endRow = Math.min(totalRows, Math.ceil((relativeScroll + viewportHeight) / estimatedRowHeight) + 1);

  // Split items into row arrays for grid virtualization
  const rows = [];
  for (let r = 0; r < totalRows; r++) {
    rows.push(sortedMangas.slice(r * columns, (r + 1) * columns));
  }

  const visibleRows = rows.slice(startRow, endRow);
  const paddingTop = startRow * estimatedRowHeight;
  const paddingBottom = Math.max(0, (totalRows - endRow) * estimatedRowHeight);

  // Enable Virtualization when dataset is larger than 12 items
  const shouldVirtualize = sortedMangas.length > 12;

  return (
    <div ref={gridRef} className="space-y-6">

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
                ⚡ Virtualized ({endRow - startRow} rows rendered)
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

      {/* Feature 74: Virtualized Grid Render Container */}
      {shouldVirtualize ? (
        <div style={{ paddingTop: `${paddingTop}px`, paddingBottom: `${paddingBottom}px` }}>
          <div className="space-y-6">
            {visibleRows.map((rowItems, rowIndexOffset) => {
              const actualRowIndex = startRow + rowIndexOffset;
              return (
                <div key={actualRowIndex} className={`grid ${gridColsMap[activeGridSize] || gridColsMap.standard}`}>
                  {rowItems.map((m, colIdx) => {
                    const globalIdx = actualRowIndex * columns + colIdx;
                    return (
                      <div key={m.id || globalIdx} className="relative">
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
              );
            })}
          </div>
        </div>
      ) : (
        /* Standard Un-virtualized Grid Display for smaller item sets */
        <div className={`grid ${gridColsMap[activeGridSize] || gridColsMap.standard}`}>
          {sortedMangas.map((m, idx) => (
            <div key={m.id || idx} className="relative">
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

      {hasMore && onLoadMore && (
        <div className="text-center pt-4">
          <button
            onClick={onLoadMore}
            disabled={loading}
            className="px-8 py-3 bg-[var(--surface-color)] hover:border-[var(--accent-vermillion)] border border-[var(--border-color)] text-[var(--text-color)] rounded-full font-serif-jp font-bold text-xs md:text-sm transition-all hover:scale-105 active:scale-95 shadow-sm cursor-pointer disabled:opacity-50"
          >
            {loading ? 'Loading...' : 'Load More Recommendations'}
          </button>
        </div>
      )}
    </div>
  );
}
