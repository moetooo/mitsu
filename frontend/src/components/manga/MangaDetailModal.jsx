import { useState, useEffect, useRef } from 'react';
import { isCoverCached, markCoverCached } from '../../utils/imageUtils';
import CoverFallback from './CoverFallback';
import { useCoverSource } from '../../hooks/useCoverSource';
import { API_ROUTES } from '../../config';
import { formatScore } from '../../utils/scoreUtils';
import { cleanSynopsis } from '../../utils/text';
import useScrollLock from '../../hooks/useScrollLock';
import useEscapeLayer from '../../hooks/useEscapeLayer';
import useFocusTrap from '../../hooks/useFocusTrap';
import CoverRail from './CoverRail';

const TITLE_ID = 'manga-detail-title';

const hoverBorderMap = {
  rose: 'hover:border-[var(--accent-vermillion)]',
  gold: 'hover:border-[#e6a15c]',
  emerald: 'hover:border-[#4e9f78]',
  mono: 'hover:border-[var(--text-color)]',
  indigo: 'hover:border-[var(--accent-indigo)]'
};

export default function MangaDetailModal({ 
  manga, 
  onClose, 
  onSelectTag, 
  onSelectManga,
  isBookmarked,
  onToggleBookmark,
  hoverAccent = 'vermillion',
  nsfwBlur = true,
  allowNsfw = false,
  onOpenSimilar = null
}) {
  const [similar, setSimilar] = useState([]);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [copied, setCopied] = useState(false);
  const cover = useCoverSource(manga);
  const [coverLoaded, setCoverLoaded] = useState(() => isCoverCached(cover.src));
  const [bannerBroken, setBannerBroken] = useState(false);
  const dialogRef = useRef(null);
  const isOpen = Boolean(manga);

  useEffect(() => {
    setBannerBroken(false);
    setCoverLoaded(isCoverCached(cover.src));
  }, [cover.src]);

  const activeHover = hoverBorderMap[hoverAccent] || hoverBorderMap.rose;

  // The bar has to name what the record actually is: a manhwa is not a manga, and
  // the API already says which one it is (`format_type`: MANGA / MANHWA / MANHUA).
  const formatLabel = (() => {
    const raw = typeof manga?.format_type === 'string' ? manga.format_type.trim() : '';
    if (!raw) return 'Manga';
    const lower = raw.toLowerCase();
    return lower.charAt(0).toUpperCase() + lower.slice(1);
  })();

  // Feature 32: Detect Explicit NSFW content (Hentai / Erotica / Adult - excluding standard Ecchi)
  const isMature = manga ? (
    (manga.is_nsfw && !manga.genres?.some(g => g.toLowerCase() === 'ecchi')) || 
    (manga.genres && manga.genres.some(g => ['hentai', 'erotica', 'adult'].includes(g.toLowerCase()))) ||
    (manga.tags && manga.tags.some(t => {
      const name = (typeof t === 'string' ? t : t.name || '').toLowerCase();
      return (name.includes('hentai') || name.includes('erotica') || name.includes('explicit') || name === 'nsfw') && !name.includes('ecchi');
    }))
  ) : false;

  const handleShare = () => {
    if (!manga) return;
    const shareUrl = `${window.location.origin}${window.location.pathname}?manga=${manga.id}`;
    const text = `Check out "${manga.title}" on Mitsu: ${shareUrl}`;
    
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text);
    } else {
      const el = document.createElement('textarea');
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand('copy');
      document.body.removeChild(el);
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  // FE-13: one counted scroll lock, so closing this overlay restores whatever
  // the page had before instead of forcing `overflow: unset`, and a second open
  // overlay is not unlocked underneath the user.
  useScrollLock(isOpen);

  // FE-08: Escape belongs to the topmost layer only. This used to be an
  // unconditional window listener, so it also fired while a layer above it was
  // open (and so did the Surprise Me handler, closing both at once).
  useEscapeLayer(isOpen, onClose);

  // FE-08: focus in on open, Tab stays inside, focus returns to the trigger.
  useFocusTrap(isOpen, dialogRef);

  useEffect(() => {
    // `/manga/{id}/similar` keys on the local database PK. A live provider row
    // (a trending title the catalog has not ingested) has no local id, so there
    // is nothing to look up -- sending an AniList id returned the wrong manga
    // or a 404.
    if (!manga || !Number.isInteger(manga.id)) {
      setSimilar([]);
      setLoadingSimilar(false);
      return;
    }
    
    let isMounted = true;
    const fetchSimilar = async () => {
      setLoadingSimilar(true);
      try {
        const res = await fetch(API_ROUTES.similar(manga.id, 6, allowNsfw));
        if (res.ok) {
          const data = await res.json();
          if (isMounted) setSimilar(data);
        }
      } catch (err) {
        console.error(err);
      } finally {
        if (isMounted) setLoadingSimilar(false);
      }
    };
    
    fetchSimilar();
    return () => { isMounted = false; };
  }, [manga, allowNsfw]);

  if (!manga) return null;

  const authorName = manga.author || (manga.staff && manga.staff[0]) || null;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={TITLE_ID}
      tabIndex={-1}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200 focus:outline-none"
    >
      
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/80 backdrop-blur-sm transition-all"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Feature 314: Atmospheric Dynamic Ambient Glow Sync */}
      {manga && (manga.banner_image || cover.src) && (
        <div 
          className="absolute inset-0 overflow-hidden pointer-events-none z-0 flex items-center justify-center transition-all duration-700 ease-out"
          aria-hidden="true"
        >
          <img
            src={(bannerBroken ? cover.src : manga.banner_image) || cover.src}
            alt=""
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover scale-125 blur-3xl opacity-30 saturate-150 transform-gpu"
            loading="eager"
            decoding="async"
            fetchPriority="low"
            aria-hidden="true"
            onError={() => setBannerBroken(true)}
          />
          {/* Soft dark radial vignette to frame the diffused ambient projection */}
          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-black/90" />
        </div>
      )}
      
      {/* Themed modal shell */}
      <div className="relative bg-[var(--surface-color)] border border-[var(--border-color)] w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-3xl shadow-2xl flex flex-col z-10 text-[var(--text-color)]">
        
        {/* Top Header Bar */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-[var(--border-color)] bg-[var(--bg-color)]/50 shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-xs font-heading text-[var(--accent-vermillion)]">❖</span>
            <span className="text-xs font-mono uppercase text-[var(--text-muted)] tracking-wider">{formatLabel} Details</span>
          </div>

          <div className="flex items-center gap-2.5">
            {/* Share Button Icon Only */}
            <button
              type="button"
              onClick={handleShare}
              className={`p-2 text-[var(--text-muted)] hover:text-[var(--text-color)] bg-[var(--surface-color)] border border-[var(--border-color)] ${activeHover} rounded-full transition-colors cursor-pointer relative`}
              title="Share"
            >
              {copied ? (
                <span className="text-[10px] font-mono font-bold text-[var(--accent-vermillion)]">Copied!</span>
              ) : (
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                </svg>
              )}
            </button>

            {/* Bookmark Button */}
            <button
              type="button"
              onClick={() => onToggleBookmark(manga)}
              className={`p-2 rounded-full border transition-all cursor-pointer ${
                isBookmarked 
                  ? 'bg-[var(--accent-vermillion)] text-white border-[var(--accent-vermillion)]'
                  : `bg-[var(--surface-color)] text-[var(--text-muted)] hover:text-[var(--text-color)] border-[var(--border-color)] ${activeHover}`
              }`}
              title={isBookmarked ? "Remove Bookmark" : "Save Bookmark"}
            >
              <svg className="w-4 h-4" fill={isBookmarked ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
              </svg>
            </button>

            {/* Close Button */}
            <button 
              type="button"
              onClick={onClose}
              className={`p-2 text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] bg-[var(--surface-color)] border border-[var(--border-color)] ${activeHover} rounded-full transition-colors cursor-pointer`}
              title="Close Preview (ESC)"
              aria-label="Close manga details"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
        
        {/* Scrollable Body. `.panel-scroll` is the site-wide rule: the rounded
            shell above clips this scrollbar so it cannot paint over the corner. */}
        <div className="panel-scroll custom-scrollbar flex flex-col md:flex-row md:items-start flex-grow min-w-0 max-w-full">
          
          {/* Clean Left Column */}
          <div className="w-full md:w-80 lg:w-[320px] shrink-0 p-5 md:p-6 flex flex-col gap-4 items-center md:items-stretch md:sticky md:top-0 h-fit">
            
            {/* Cover Image */}
            <div className="flex gap-3.5 w-full items-center justify-center">
              {/* Framed Print Cover */}
              <div className="relative group w-full max-w-[260px] md:max-w-none aspect-[2/3] rounded-2xl overflow-hidden border border-[var(--border-color)] shadow-lg bg-[var(--surface-color)]">
                {/* Feature 34: Shimmer Paper Skeleton Loader matching search cards */}
                {!coverLoaded && cover.src && (
                  <div className="absolute inset-0 shimmer-paper-loading z-10 flex flex-col items-center justify-center p-4">
                    <span className="text-base font-heading text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
                  </div>
                )}

                {!cover.src ? (
                  <CoverFallback title={manga.title} />
                ) : (
                  <img 
                    src={cover.src} 
                    alt={manga.title}
                    referrerPolicy="no-referrer"
                    decoding="async"
                    loading="eager"
                    fetchPriority="high"
                    onLoad={() => {
                      markCoverCached(cover.src);
                      setCoverLoaded(true);
                    }}
                    onError={() => {
                      cover.handleError();
                      setCoverLoaded(true);
                    }}
                    className={`w-full h-full object-cover transition-all duration-300 ${
                      coverLoaded ? 'opacity-100' : 'opacity-0'
                    } ${
                      nsfwBlur && isMature ? 'blur-md group-hover:blur-none scale-105' : ''
                    }`}
                  />
                )}

                {/* Feature 32: NSFW Warning Overlay on Modal Cover */}
                {nsfwBlur && isMature && (
                  <div className="absolute inset-0 flex items-center justify-center z-10 pointer-events-none group-hover:opacity-0 transition-opacity">
                    <span className="px-3 py-1 rounded-full bg-[var(--warn-chip-bg)] border border-[var(--warn-chip-border)] text-[var(--warn-chip-ink)] font-mono text-xs font-bold tracking-widest uppercase backdrop-blur-xs">
                      EXPLICIT 18+
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* External Links Bar */}
            {manga.anilist_id && (
              <a
                href={`https://anilist.co/manga/${manga.anilist_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className={`w-full max-w-[260px] md:max-w-none mx-auto py-2.5 px-4 rounded-xl text-xs font-mono text-[var(--accent-indigo)] border border-[var(--border-color)] ${activeHover} bg-[var(--surface-color)] hover:bg-[var(--surface-hover)] flex items-center justify-center gap-1.5 transition-colors shadow-xs`}
              >
                <span>View AniList Profile ↗</span>
              </a>
            )}

          </div>

          
          {/* Content Details */}
          <div className="p-6 md:p-8 flex flex-col gap-6 flex-grow min-w-0 max-w-full">
            
            <div>
              <h2 id={TITLE_ID} className="text-2xl md:text-4xl font-heading font-bold text-[var(--text-color)] mb-3 leading-snug">
                {manga.title}
              </h2>
              
              <div className="flex flex-wrap items-center gap-2.5 text-xs font-mono text-[var(--text-muted)]">
                {manga.status && (
                  <span className="px-3 py-1 rounded-full bg-[var(--surface-color)] border border-[var(--border-color)] uppercase">
                    {manga.status}
                  </span>
                )}
                {manga.start_year && (
                  <span className="px-3 py-1 rounded-full bg-[var(--surface-color)] border border-[var(--border-color)]">
                    {manga.start_year}
                  </span>
                )}
                {manga.chapters && (
                  <span className="px-3 py-1 rounded-full bg-[var(--surface-color)] border border-[var(--border-color)]">
                    {manga.chapters} Chapters
                  </span>
                )}
                {manga.average_score && (
                  <span className="px-3 py-1 rounded-full bg-[var(--seal-bg)] text-[var(--accent-vermillion)] border border-[var(--accent-vermillion)] font-bold">
                    ★ {formatScore(manga.average_score)} / 10
                  </span>
                )}

                {/* Feature 41: Clickable Author Badge inside modal */}
                {authorName && (
                  <button
                    type="button"
                    onClick={() => {
                      if (onSelectTag) onSelectTag(authorName);
                      onClose();
                    }}
                    className="px-3 py-1 rounded-full bg-[var(--surface-color)] border border-[var(--accent-indigo)] text-[var(--accent-indigo)] hover:bg-[var(--accent-indigo)] hover:text-white transition-all cursor-pointer font-mono font-bold"
                    title={`Search all works by ${authorName}`}
                  >
                    Author: {authorName}
                  </button>
                )}
              </div>
            </div>

            {/* Synopsis */}
            <div className="space-y-1.5">
              <h3 className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
                Synopsis
              </h3>
              <p className="text-[var(--text-color)] text-xs md:text-sm leading-relaxed whitespace-pre-wrap font-light">
                {cleanSynopsis(manga.synopsis, 'No detailed synopsis available.')}
              </p>
            </div>

            {/* Clickable Genres & Tags */}
            {((manga.genres && manga.genres.length > 0) || (manga.tags && manga.tags.length > 0)) && (
              <div className="space-y-1.5">
                <h3 className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
                  Genres & Tags (Click to Search)
                </h3>
                <div className="flex flex-wrap gap-2">
                  {(manga.genres || []).map(g => (
                    <button
                      key={g}
                      onClick={() => {
                        if (onSelectTag) onSelectTag(g);
                        onClose();
                      }}
                      className={`px-3 py-1 bg-[var(--bg-color)] ${activeHover} hover:text-[var(--accent-vermillion)] text-[var(--text-color)] text-xs rounded-full border border-[var(--border-color)] transition-all cursor-pointer font-heading`}
                    >
                      #{g}
                    </button>
                  ))}
                  {(manga.tags || []).slice(0, 8).map(t => {
                    const tagName = typeof t === 'string' ? t : t.name;
                    if (!tagName || (manga.genres || []).includes(tagName)) return null;
                    return (
                      <button
                        key={tagName}
                        onClick={() => {
                          if (onSelectTag) onSelectTag(tagName);
                          onClose();
                        }}
                        className={`px-3 py-1 bg-[var(--surface-color)] ${activeHover} hover:text-[var(--accent-indigo)] text-[var(--text-muted)] text-xs rounded-full border border-[var(--border-color)] transition-all cursor-pointer font-mono`}
                      >
                        #{tagName}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Horizontal More Like This Carousel */}
            <div className="pt-6 border-t border-[var(--border-color)] space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-2">
                  <span className="text-[var(--accent-vermillion)]">❖</span>
                  You Might Also Like
                </h3>
                <span className="text-[10px] text-[var(--text-muted)] font-mono">Click to preview</span>
              </div>

              <CoverRail
                items={similar}
                loading={loadingSimilar}
                onSelect={onSelectManga}
                onAction={onOpenSimilar && Number.isInteger(manga.id) ? () => onOpenSimilar(manga.id) : null}
                actionAriaLabel="Load more similar titles"
                emptyLabel="No similar titles found."
              />
            </div>

          </div>

        </div>

      </div>

    </div>
  );
}
