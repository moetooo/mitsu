import { useState, useRef, useEffect, memo } from 'react';
import { isCoverCached, markCoverCached } from '../../utils/imageUtils';
import { useCoverSource } from '../../hooks/useCoverSource';
import { formatScore } from '../../utils/scoreUtils';
import CoverFallback from './CoverFallback';

function MangaCard({ 
  manga, 
  onClick, 
  isBookmarked, 
  onToggleBookmark,
  hoverAccent = 'vermillion',
  showMatchPct = true,
  rank = null,
  nsfwBlur = true,
  // True for cards in the first screenful: they are what the browser paints first,
  // so their covers must not be deferred like the rest of the grid.
  priority = false
}) {
  // The cover this card will draw, after walking the candidate list when a host
  // fails. `cover.dead` means every candidate refused, so the tile is the honest
  // answer - not a broken <img>.
  const cover = useCoverSource(manga);
  const isCached = isCoverCached(cover.src);
  const [imgLoaded, setImgLoaded] = useState(isCached);
  const [isNearViewport, setIsNearViewport] = useState(isCached);
  const cardRef = useRef(null);

  // Sync state if the cover changed (fallback walked, candidate replaced, or a
  // cached payload arrived without the list).
  useEffect(() => {
    if (isCoverCached(cover.src)) {
      setImgLoaded(true);
      setIsNearViewport(true);
    } else {
      setImgLoaded(false);
    }
  }, [cover.src]);

  // Feature 82: IntersectionObserver Prefetching (400px margin for silky smooth pre-load)
  useEffect(() => {
    if (isCached || !cardRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setIsNearViewport(true);
            observer.disconnect();
          }
        });
      },
      { rootMargin: '400px' }
    );
    observer.observe(cardRef.current);
    return () => observer.disconnect();
  }, [cover.src, isCached]);

  const handleImageLoaded = () => {
    markCoverCached(cover.src);
    setImgLoaded(true);
  };

  const handleImageError = () => {
    cover.handleError(); // retry the same host once, then next candidate
    setImgLoaded(true); // Stop shimmer skeleton from pulsing indefinitely
  };

  const matchPct = (showMatchPct && manga.similarity_score !== undefined && manga.similarity_score !== null) 
    ? Math.round(manga.similarity_score * 100) 
    : null;

  const hoverBorderMap = {
    rose: 'hover:border-[var(--accent-vermillion)]',
    gold: 'hover:border-[#e6a15c]',
    emerald: 'hover:border-[#4e9f78]',
    mono: 'hover:border-[var(--text-color)]',
    indigo: 'hover:border-[var(--accent-indigo)]'
  };

  // Feature 32: Detect Explicit NSFW content (Hentai / Erotica / Adult - excluding standard Ecchi)
  const isMature = (manga.is_nsfw && !manga.genres?.some(g => g.toLowerCase() === 'ecchi')) || 
    (manga.genres && manga.genres.some(g => {
      const name = g.toLowerCase();
      return name === 'hentai' || name === 'erotica' || name === 'adult';
    })) ||
    (manga.tags && manga.tags.some(t => {
      const name = (typeof t === 'string' ? t : t.name || '').toLowerCase();
      return (name.includes('hentai') || name.includes('erotica') || name.includes('explicit') || name === 'nsfw') && !name.includes('ecchi');
    }));

  const authorName = manga.author || manga.artist || (manga.staff && manga.staff[0]) || (manga.authors && manga.authors[0]) || null;

  return (
    <div
      ref={cardRef}
      onClick={() => onClick(manga)}
      style={{ contentVisibility: 'auto', containIntrinsicSize: '0 380px' }}
      className={`manga-card-item group relative bg-[var(--surface-color)] border border-[var(--border-color)] rounded-2xl p-3 cursor-pointer shadow-sm hover:shadow-md ${hoverBorderMap[hoverAccent] || hoverBorderMap.vermillion} transition-all duration-150 ease-out hover:scale-[1.02] flex flex-col justify-between`}
    >
      {/* Feature 314: Atmospheric Dynamic Ambient Glow Sync on Card Hover */}
      {cover.src && (
        <div 
          className="absolute -inset-1.5 rounded-2xl pointer-events-none opacity-0 group-hover:opacity-35 transition-opacity duration-300 blur-xl -z-10 overflow-hidden transform-gpu will-change-transform"
          aria-hidden="true"
        >
          <img
            src={cover.src}
            alt=""
            aria-hidden="true"
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover scale-110 saturate-150"
            loading="lazy"
            decoding="async"
            // A decorative duplicate of the poster below: it must never compete with
            // the real cover for bandwidth, or become the largest painted element.
            fetchPriority="low"
          />
        </div>
      )}

      {/* Framed Print Cover Container */}
      <div className="relative aspect-[2/3] w-full rounded-xl overflow-hidden bg-[var(--surface-color)] border border-[var(--border-color)]">
        
        {/* Feature 34: Shimmer Paper Skeleton Loader */}
        {!imgLoaded && cover.src && (
          <div className="absolute inset-0 shimmer-paper-loading z-10 flex flex-col items-center justify-center p-4">
            <span className="text-xs font-heading text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
          </div>
        )}

        {cover.dead || !cover.src ? (
          <CoverFallback title={manga.title} />
        ) : (isNearViewport || imgLoaded) ? (
          <img
            src={cover.src}
            alt={manga.title}
            referrerPolicy="no-referrer"
            onLoad={handleImageLoaded}
            onError={handleImageError}
            // A lazy hint on the first screen delays the biggest thing on the page.
            loading={priority ? 'eager' : 'lazy'}
            fetchPriority={priority ? 'high' : 'auto'}
            // Intrinsic size: the container already fixes the 2:3 box, so this only
            // stops the browser reserving the wrong space before the bytes arrive.
            width={300}
            height={450}
            className={`w-full h-full object-cover transition-all duration-300 group-hover:scale-105 ${
              nsfwBlur && isMature ? 'blur-md group-hover:blur-none scale-105' : ''
            }`}
            decoding="async"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] font-heading text-xs">
            Loading...
          </div>
        )}
        
        {/* Feature 32: Explicit NSFW Safety Warning Badge */}
        {nsfwBlur && isMature && (
          <div className="absolute inset-0 flex items-center justify-center z-15 pointer-events-none group-hover:opacity-0 transition-opacity">
            <span className="px-2.5 py-1 rounded-full bg-[var(--warn-chip-bg)] border border-[var(--warn-chip-border)] text-[var(--warn-chip-ink)] font-mono text-[9px] font-bold tracking-widest uppercase backdrop-blur-xs">
              EXPLICIT 18+
            </span>
          </div>
        )}

        {/* Subtle Dark Bottom Gradient */}
        <div className="absolute inset-0 bg-gradient-to-t from-[var(--cover-art-fade-from)] via-[var(--cover-art-fade-via)] to-transparent opacity-80 group-hover:opacity-90 transition-opacity pointer-events-none" />

        {/* Top-Right Corner Rank Badge */}
        {rank !== null && (
          <div className="absolute top-2.5 right-2.5 z-20 w-7 h-7 rounded-full bg-[var(--accent-vermillion)] text-white font-mono text-xs font-bold flex items-center justify-center border-2 border-[var(--bg-color)] shadow-md">
            #{rank}
          </div>
        )}

        {/* Finalized Circular Ink Crest (Symmetrical 28px x 28px Circle) - Hover Only */}
        {matchPct !== null && rank === null && (
          <div className="absolute top-2.5 right-2.5 stamp-crest z-10 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none">
            <span>{matchPct}%</span>
          </div>
        )}

        {/* Bookmark Button (Symmetrical 28px x 28px Circle) - Hover Only */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleBookmark(manga);
          }}
          className={`absolute top-2.5 left-2.5 w-7 h-7 rounded-full flex items-center justify-center border transition-all duration-200 z-20 cursor-pointer opacity-0 group-hover:opacity-100 ${
            isBookmarked 
              ? 'bg-[var(--accent-vermillion)] text-white border-[var(--accent-vermillion)] scale-105 shadow-sm'
              : 'bg-[var(--surface-color)]/75 text-[var(--text-color)] border-[var(--border-color)] hover:text-[var(--accent-vermillion)] hover:bg-[var(--surface-color)]/95'
          }`}
          title={isBookmarked ? "Remove Bookmark" : "Save Bookmark"}
        >
          <svg className="w-3.5 h-3.5" fill={isBookmarked ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
          </svg>
        </button>
      </div>


      {/* Card Info & Typography */}
      <div className="pt-3 px-1 space-y-1.5 flex-grow flex flex-col justify-between">
        <div className="space-y-1">
          <h3 
            title={manga.title}
            className="font-heading font-bold text-xs md:text-sm text-[var(--text-color)] line-clamp-2 leading-snug group-hover:text-[var(--accent-vermillion)] transition-colors h-[2.5rem] overflow-hidden flex items-start"
          >
            {manga.title}
          </h3>

          {/* FE-09: the author is plain text. It was a button wired to
              `onSelectAuthor`, which no caller ever passed, so it looked
              clickable and did nothing. `/recommend` has no author filter. */}
          {authorName && (
            <p className="text-[10px] font-mono text-[var(--accent-indigo)] truncate block max-w-full text-left">
              by {authorName}
            </p>
          )}

        </div>

        <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)] font-mono">
          {manga.start_year && <span>{manga.start_year}</span>}
          {manga.status && <span>• {manga.status}</span>}
          {manga.average_score && (
            <span className="ml-auto text-[var(--accent-vermillion)] font-bold">
              ★ {formatScore(manga.average_score)}
            </span>
          )}
        </div>

      </div>

    </div>
  );
}

// Feature 73: Component Memoization to prevent re-rendering cards unless card props change
export default memo(MangaCard);

