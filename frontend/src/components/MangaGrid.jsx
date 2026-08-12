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
  hasMore = false,
  onLoadMore = null,
  hasSearched = false
}) {
  const isBookmarked = (id) => bookmarks.some(b => b.id === id);

  const gridColsMap = {
    compact: 'grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4',
    standard: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6',
    large: 'grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-8'
  };

  if (loading && mangas.length === 0) {
    return (
      <div className={`grid ${gridColsMap[gridSize]}`}>
        {[1, 2, 3, 4, 5, 6, 7, 8].map(i => (
          <div key={i} className="aspect-[2/3] bg-[var(--surface-color)] rounded-2xl animate-pulse border border-[var(--border-color)]" />
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

  return (
    <div className="space-y-8">
      <SectionDivider label={`Results (${mangas.length})`} />

      <div className={`grid ${gridColsMap[gridSize]}`}>
        {mangas.map(m => (
          <MangaCard 
            key={m.id}
            manga={m}
            onClick={onCardClick}
            isBookmarked={isBookmarked(m.id)}
            onToggleBookmark={onToggleBookmark}
            gridSize={gridSize}
            stampStyle={stampStyle}
            hoverAccent={hoverAccent}
          />
        ))}
      </div>



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
