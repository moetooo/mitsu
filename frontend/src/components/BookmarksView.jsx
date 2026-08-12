import MangaGrid from './MangaGrid';
import SectionDivider from './SectionDivider';

export default function BookmarksView({ bookmarks, onSelectManga, onToggleBookmark, onClearAll }) {
  if (bookmarks.length === 0) {
    return (
      <div className="text-center py-20 space-y-4 max-w-md mx-auto">
        <div className="w-14 h-14 rounded-full bg-[var(--surface-color)] border border-[var(--border-color)] flex items-center justify-center mx-auto text-[var(--accent-vermillion)] font-serif-jp text-lg">
          ❖
        </div>
        <h2 className="text-xl font-serif-jp font-bold text-[var(--text-color)]">No Saved Manga</h2>
        <p className="text-xs text-[var(--text-muted)] leading-relaxed font-serif-jp">
          Click the bookmark icon on any manga card or preview modal to save your favorite titles here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-3">
        <div>
          <h2 className="text-2xl font-serif-jp font-bold text-[var(--text-color)]">Saved Manga Collection</h2>
          <p className="text-xs text-[var(--text-muted)] font-mono">{bookmarks.length} bookmarked titles saved locally</p>
        </div>
        <button
          onClick={onClearAll}
          className="px-3.5 py-1.5 bg-[var(--surface-color)] text-red-400 hover:border-red-500 border border-[var(--border-color)] rounded-full text-xs font-mono transition-all cursor-pointer"
        >
          Clear All
        </button>
      </div>

      <SectionDivider label="Saved Collection" />

      <MangaGrid 
        mangas={bookmarks}
        loading={false}
        onCardClick={onSelectManga}
        bookmarks={bookmarks}
        onToggleBookmark={onToggleBookmark}
      />
    </div>
  );
}
