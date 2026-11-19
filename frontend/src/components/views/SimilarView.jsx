import { useEffect, useState } from 'react';
import MangaGrid from '../manga/MangaGrid';
import ErrorBanner from '../common/ErrorBanner';
import useSimilar from '../../hooks/useSimilar';
import { API_ROUTES } from '../../config';

/**
 * `/similar/{id}` — the full "You Might Also Like" page.
 *
 * The modal rail shows six covers; its Load More is a link here. The cards are
 * the same ones the result grid uses, so bookmarking and opening a title behave
 * identically. Pagination is the shared explicit Load More button owned by
 * `MangaGrid`; this page adds no second scroll container.
 */
export default function SimilarView({
  mangaId,
  onBack,
  onCardClick,
  bookmarks,
  onToggleBookmark,
  gridSize = 'standard',
  hoverAccent = 'vermillion',
  nsfwBlur = true,
  allowNsfw = false,
  requestLimit
}) {
  const { mangas, loading, searched, error, hasMore, loadMore, retry } = useSimilar({
    mangaId,
    allowNsfw,
    requestLimit
  });
  const [sourceTitle, setSourceTitle] = useState('');

  useEffect(() => {
    if (!mangaId) return undefined;
    let alive = true;
    setSourceTitle('');
    fetch(API_ROUTES.manga(mangaId))
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        if (!alive || !data) return;
        setSourceTitle(data.title_english || data.title_romaji || data.title_native || '');
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [mangaId]);

  return (
    <div className="animate-tab-fade-in max-w-7xl mx-auto px-4 md:px-8 py-6 pb-20 space-y-6">
      <div className="space-y-3 border-b border-[var(--border-color)] pb-5">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] cursor-pointer"
        >
          ← Back to results
        </button>
        <h1 className="flex items-center gap-2 text-xl md:text-2xl font-heading font-bold text-[var(--text-color)]">
          <span aria-hidden="true" className="text-[var(--accent-vermillion)]">❖</span>
          You Might Also Like
        </h1>
        <p className="text-xs text-[var(--text-muted)] font-mono">
          {sourceTitle ? `Titles similar to ${sourceTitle}` : 'Titles similar to this one'}
        </p>
      </div>

      <ErrorBanner message={error} label="Similar titles failed" onRetry={retry} />

      <MangaGrid
        mangas={mangas}
        loading={loading}
        hasSearched={searched}
        onCardClick={onCardClick}
        bookmarks={bookmarks}
        onToggleBookmark={onToggleBookmark}
        gridSize={gridSize}
        hoverAccent={hoverAccent}
        nsfwBlur={nsfwBlur}
        hasMore={hasMore}
        onLoadMore={loadMore}
        hideDivider
      />
    </div>
  );
}
