import { useState, useEffect } from 'react';
import { isCoverCached, markCoverCached } from '../../utils/imageUtils';
import CoverFallback from './CoverFallback';

/**
 * One tile in a horizontal cover rail (FE-29 extraction).
 *
 * A rail is a preview strip, not a result grid: the tile stays one line tall so
 * the panel around it does not have to scroll to show it. Both rails in the app
 * — "You Might Also Like" in the detail modal and the Trending section on
 * Explore — render this one component, so a tile looks and behaves the same in
 * both and there is no second copy to drift.
 *
 * The cover walk (cached → shimmer → fallback on error) is the same one the grid
 * cards use; the difference is only the size and the gradient title overlay.
 */
export default function SimilarCoverItem({ item, onSelect }) {
  const isCached = isCoverCached(item.cover_image_url);
  const [loaded, setLoaded] = useState(isCached);
  const [error, setError] = useState(false);

  useEffect(() => {
    setError(false);
    setLoaded(isCoverCached(item.cover_image_url));
  }, [item.cover_image_url]);

  return (
    <div
      onClick={() => onSelect(item)}
      className="w-28 sm:w-32 shrink-0 group relative aspect-[2/3] rounded-2xl overflow-hidden cursor-pointer border border-[var(--border-color)] hover:border-[var(--accent-vermillion)] transition-all duration-200 shadow-md bg-[var(--surface-color)]"
    >
      {!loaded && !error && item.cover_image_url && (
        <div className="absolute inset-0 shimmer-paper-loading z-10 flex flex-col items-center justify-center p-2">
          <span className="text-[10px] font-heading text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
        </div>
      )}
      {error || !item.cover_image_url ? (
        <CoverFallback title={item.title} compact />
      ) : (
        <img
          src={item.cover_image_url}
          alt={item.title}
          referrerPolicy="no-referrer"
          decoding="async"
          onLoad={() => {
            markCoverCached(item.cover_image_url);
            setLoaded(true);
          }}
          onError={() => {
            setError(true);
            setLoaded(true);
          }}
          className={`w-full h-full object-cover transition-all duration-300 group-hover:scale-110 ${
            loaded ? 'opacity-100' : 'opacity-0'
          }`}
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black via-black/30 to-transparent opacity-90 p-2.5 flex flex-col justify-end">
        <span className="text-[11px] font-heading font-bold text-white line-clamp-2 leading-tight">
          {item.title}
        </span>
      </div>
    </div>
  );
}
