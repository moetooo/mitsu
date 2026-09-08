import { useState, useEffect, useRef, useCallback } from 'react';
import { isCoverCached, markCoverCached } from '../utils/imageUtils';

function SurpriseCoverImage({ url, title, allowHover }) {
  const isCached = isCoverCached(url);
  const [loaded, setLoaded] = useState(isCached);

  useEffect(() => {
    if (isCoverCached(url)) {
      setLoaded(true);
    } else {
      setLoaded(false);
    }
  }, [url]);

  const handleLoad = () => {
    markCoverCached(url);
    setLoaded(true);
  };

  return (
    <div className="absolute inset-0 w-full h-full select-none overflow-hidden bg-neutral-900">
      {/* Feature 34: Shimmer Paper Skeleton Loader matching search cards */}
      {!loaded && url && (
        <div className="absolute inset-0 shimmer-paper-loading z-10 flex flex-col items-center justify-center p-4">
          <span className="text-base font-serif-jp text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
        </div>
      )}

      {url ? (
        <img 
          src={url} 
          alt={title} 
          referrerPolicy="no-referrer"
          decoding="async"
          onLoad={handleLoad}
          className={`w-full h-full object-cover select-none pointer-events-none transition-all duration-300 ease-out ${
            loaded ? 'opacity-100' : 'opacity-0'
          } ${allowHover ? 'group-hover:scale-103' : ''}`}
        />
      ) : (
        <div className="w-full h-full flex items-center justify-center bg-neutral-900 text-neutral-600 font-mono text-xs">
          No Cover Artwork
        </div>
      )}

      {/* Top ambient vignette for header */}
      <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/80 via-black/35 to-transparent z-10 pointer-events-none" />

      {/* Bottom gradient shadow for default title & rating peek */}
      <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-black/90 via-black/45 to-transparent z-10 pointer-events-none" />
    </div>
  );
}

export default function SurpriseView({ 
  manga, 
  loading, 
  onRefresh, 
  fetchBatch,
  filters = {},
  onOpenFilter,
  bookmarks = [], 
  onToggleBookmark, 
  onSelectManga,
  imageLength = 60
}) {
  // Queue of discovered manga titles
  const [titles, setTitles] = useState(() => (manga ? [manga] : []));
  const [currentIndex, setCurrentIndex] = useState(0);

  // Sliding state for throttling and hover suppression mid-motion
  const [isSliding, setIsSliding] = useState(false);

  // Mobile card peek accordion toggle state
  const [mobileDetailsOpen, setMobileDetailsOpen] = useState(false);

  // Diptych Folio Full Details state & responsive breakpoint
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(() => (typeof window !== 'undefined' ? window.innerWidth >= 820 : true));

  // Idle navigation hint state: shows ONLY when inactive for 60 seconds
  const [showHint, setShowHint] = useState(false);
  const idleTimerRef = useRef(null);

  // Responsive card dimensions
  const containerRef = useRef(null);
  const [cardSize, setCardSize] = useState({ width: 390, height: 560 });

  // References
  const seenIdsRef = useRef(new Set(manga?.id ? [manga.id] : []));
  const isFetchingBatchRef = useRef(false);
  const touchStartYRef = useRef(0);
  const isSlidingRef = useRef(false);
  const lastSlideTimeRef = useRef(0);
  const prevDeltaRef = useRef(0);
  const accumRef = useRef(0);
  const lastEventTimeRef = useRef(0);
  const lastDirectionRef = useRef(0);
  const resetTimerRef = useRef(null);

  // Idle inactivity tracker (60 seconds)
  const resetIdleHintTimer = useCallback(() => {
    setShowHint(false);
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    idleTimerRef.current = setTimeout(() => {
      setShowHint(true);
    }, 60000); // 60 seconds
  }, []);

  // Initialize idle hint timer on mount
  useEffect(() => {
    resetIdleHintTimer();
    return () => {
      if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    };
  }, [resetIdleHintTimer]);

  // Responsive sizing ensuring ZERO window scrollbar and proper margin for controls
  useEffect(() => {
    const updateSize = () => {
      const vh = window.innerHeight;
      const vw = window.innerWidth;
      setIsDesktop(vw >= 820);
      
      const targetH = Math.max(460, Math.min(600, vh - 150));
      const targetW = Math.max(300, Math.min(410, vw - 90));

      setCardSize({ width: targetW, height: targetH });
    };

    updateSize();
    window.addEventListener('resize', updateSize);
    return () => window.removeEventListener('resize', updateSize);
  }, []);

  // Preload image helper
  const preloadImage = (url) => {
    if (!url) return;
    const img = new Image();
    img.src = url;
  };

  // Preload covers for subsequent titles
  useEffect(() => {
    if (titles.length > 0) {
      for (let i = currentIndex; i < Math.min(currentIndex + 4, titles.length); i++) {
        if (titles[i]?.cover_image_url) {
          preloadImage(titles[i].cover_image_url);
        }
      }
    }
  }, [currentIndex, titles]);

  // Sync initial manga prop if queue is empty
  useEffect(() => {
    if (manga && titles.length === 0) {
      setTitles([manga]);
      seenIdsRef.current.add(manga.id);
    }
  }, [manga, titles.length]);

  // Refill background buffer whenever remaining titles drop below 4
  const refillQueue = useCallback(async () => {
    if (isFetchingBatchRef.current || !fetchBatch) return;
    isFetchingBatchRef.current = true;

    try {
      const batch = await fetchBatch(5);
      if (Array.isArray(batch) && batch.length > 0) {
        const newItems = batch.filter(item => {
          if (!item?.id || seenIdsRef.current.has(item.id)) return false;
          seenIdsRef.current.add(item.id);
          return true;
        });

        if (newItems.length > 0) {
          newItems.forEach(item => {
            if (item.cover_image_url) preloadImage(item.cover_image_url);
          });
          setTitles(prev => [...prev, ...newItems]);
        }
      }
    } catch (err) {
      console.error('Failed to prefetch surprise discovery batch:', err);
    } finally {
      isFetchingBatchRef.current = false;
    }
  }, [fetchBatch]);

  // Initial prefetch to ensure continuous scroll queue
  useEffect(() => {
    if (titles.length < 4) {
      refillQueue();
    }
  }, [refillQueue, titles.length]);

  // Check if buffer needs refill when navigating
  useEffect(() => {
    if (titles.length - currentIndex <= 3) {
      refillQueue();
    }
  }, [currentIndex, titles.length, refillQueue]);

  // Reset queue if filters change
  useEffect(() => {
    seenIdsRef.current.clear();
    setTitles([]);
    setCurrentIndex(0);
    setIsSliding(false);
    setIsDetailsOpen(false);
    resetIdleHintTimer();
    if (onRefresh) {
      onRefresh().then(first => {
        if (first) {
          setTitles([first]);
          seenIdsRef.current.add(first.id);
        }
      });
    }
  }, [filters, resetIdleHintTimer]);

  // Navigation handlers (Vertical physical slide)
  const handleNext = useCallback(() => {
    resetIdleHintTimer();
    if (isSlidingRef.current) return;
    if (currentIndex < titles.length - 1) {
      isSlidingRef.current = true;
      lastSlideTimeRef.current = Date.now();
      setIsSliding(true);
      setCurrentIndex(prev => prev + 1);
      setTimeout(() => {
        setIsSliding(false);
        isSlidingRef.current = false;
      }, 360);
    } else {
      refillQueue();
    }
  }, [currentIndex, titles.length, refillQueue, resetIdleHintTimer]);

  const handlePrev = useCallback(() => {
    resetIdleHintTimer();
    if (isSlidingRef.current || currentIndex <= 0) return;
    isSlidingRef.current = true;
    lastSlideTimeRef.current = Date.now();
    setIsSliding(true);
    setCurrentIndex(prev => prev - 1);
    setTimeout(() => {
      setIsSliding(false);
      isSlidingRef.current = false;
    }, 360);
  }, [currentIndex, resetIdleHintTimer]);

  // Fluid Touchpad & Wheel listener — Kinetic Coasting Filter (NO LOCKOUT / NEVER STUCK)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onWheel = (e) => {
      // Natural scrolling inside the dossier synopsis
      if (e.target && e.target.closest && e.target.closest('#dossier-card-scroll')) {
        return;
      }

      e.preventDefault();
      resetIdleHintTimer();

      const now = Date.now();
      const timeSinceLastEvent = now - lastEventTimeRef.current;
      lastEventTimeRef.current = now;

      // Normalize delta across line vs pixel modes
      const rawDelta = e.deltaMode === 1 ? e.deltaY * 32 : e.deltaY;
      const absDelta = Math.abs(rawDelta);
      const currentDir = rawDelta > 0 ? 1 : -1;

      // If user paused between swipes (> 140ms silence), reset accumulator & inertia memory
      if (timeSinceLastEvent > 140) {
        accumRef.current = 0;
        prevDeltaRef.current = 0;
      }

      // If card is actively animating (within 360ms slide window):
      if (isSlidingRef.current || now - lastSlideTimeRef.current < 360) {
        prevDeltaRef.current = absDelta;
        accumRef.current = 0;
        return;
      }

      // If swipe direction reversed, immediately clear any forward inertia memory
      if (lastDirectionRef.current !== 0 && currentDir !== lastDirectionRef.current) {
        accumRef.current = 0;
        prevDeltaRef.current = 0;
      }
      lastDirectionRef.current = currentDir;

      // KINETIC INERTIA FILTER:
      // When a swipe finishes, touchpads coast down with small, decelerating deltas.
      // If delta is small (< 32) and decelerating, it is decaying coasting momentum — discard it!
      const isCoasting = absDelta < 32 && absDelta <= prevDeltaRef.current + 3;
      prevDeltaRef.current = absDelta;

      if (isCoasting) {
        return;
      }

      // Accumulate intentional gesture force
      accumRef.current += rawDelta;

      // Auto-clear accumulator if user stops mid-swipe without meeting threshold
      clearTimeout(resetTimerRef.current);
      resetTimerRef.current = setTimeout(() => {
        accumRef.current = 0;
        prevDeltaRef.current = 0;
      }, 140);

      // Trigger threshold: 40px of intentional directional force
      if (accumRef.current >= 40) {
        accumRef.current = 0;
        prevDeltaRef.current = 0;
        handleNext();
      } else if (accumRef.current <= -40) {
        accumRef.current = 0;
        prevDeltaRef.current = 0;
        handlePrev();
      }
    };

    el.addEventListener('wheel', onWheel, { passive: false });
    return () => {
      el.removeEventListener('wheel', onWheel);
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    };
  }, [handleNext, handlePrev, resetIdleHintTimer]);

  // Keyboard navigation (Arrow keys, PageUp/Down, J/K, Escape)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;

      if (e.key === 'Escape') {
        if (isDetailsOpen) {
          setIsDetailsOpen(false);
          return;
        }
      }

      if (e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === 'j') {
        e.preventDefault();
        resetIdleHintTimer();
        handleNext();
      } else if (e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'k') {
        e.preventDefault();
        resetIdleHintTimer();
        handlePrev();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleNext, handlePrev, resetIdleHintTimer, isDetailsOpen]);

  // Touch swipe support on card
  const handleTouchStart = (e) => {
    resetIdleHintTimer();
    touchStartYRef.current = e.touches[0].clientY;
  };

  const handleTouchEnd = (e) => {
    resetIdleHintTimer();
    const touchEndY = e.changedTouches[0].clientY;
    const diff = touchStartYRef.current - touchEndY;
    if (Math.abs(diff) > 35) {
      if (diff > 0) {
        handleNext();
      } else {
        handlePrev();
      }
    }
  };

  const getCleanSynopsis = (text) => {
    if (!text) return 'No synopsis description available for this title.';
    if (typeof text !== 'string') return String(text);
    return text.replace(/<[^>]*>?/gm, '').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
  };

  // Filter counters
  const excludedCount = filters.exclude_genres?.length || 0;
  const includedCount = filters.genres?.length || 0;
  const hasActiveFilters = (
    excludedCount > 0 || 
    includedCount > 0 || 
    Boolean(filters.format_type) || 
    (filters.min_score > 0) || 
    (filters.status?.length > 0)
  );

  // Renders the Companion Dossier Card Content (Shared between desktop folio & mobile sheet)
  const renderDossierContent = (mangaItem, onClose) => {
    if (!mangaItem) return null;
    const isBookmarked = Array.isArray(bookmarks) ? bookmarks.some(b => b?.id === mangaItem.id) : false;
    const titleStr = typeof mangaItem.title === 'string' 
      ? mangaItem.title 
      : (mangaItem.title?.english || mangaItem.title?.romaji || mangaItem.title_english || mangaItem.title_romaji || 'Manga Title');
    const anilistUrl = mangaItem.anilist_id 
      ? `https://anilist.co/manga/${mangaItem.anilist_id}` 
      : `https://anilist.co/search/manga?search=${encodeURIComponent(titleStr)}`;
    const malUrl = mangaItem.mal_id 
      ? `https://myanimelist.net/manga/${mangaItem.mal_id}` 
      : `https://myanimelist.net/manga.php?q=${encodeURIComponent(titleStr)}`;

    return (
      <div className="p-5 sm:p-6 w-full h-full flex flex-col justify-between select-none bg-transparent">
        {/* Top Header Bar */}
        <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-3 shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-[var(--accent-vermillion)] text-sm font-bold animate-pulse">❖</span>
            <span className="font-mono text-[10px] tracking-widest uppercase text-[var(--text-muted)]">
              PROFILE #{String(currentIndex + 1).padStart(2, '0')}
            </span>
          </div>
          <button 
            type="button"
            onClick={onClose}
            aria-label="Close Profile"
            className="w-7 h-7 rounded-full bg-[var(--surface-color)]/80 hover:bg-[var(--accent-vermillion)] border border-[var(--border-color)] hover:border-[var(--accent-vermillion)] text-[var(--text-color)] hover:text-white flex items-center justify-center transition-all cursor-pointer text-xs"
          >
            ✕
          </button>
        </div>

        {/* Scrollable Center Dossier Body */}
        <div 
          id="dossier-card-scroll" 
          className="flex-1 overflow-y-auto custom-scrollbar pr-1.5 py-3.5 space-y-4 text-left pointer-events-auto"
        >
          {/* Title & Metadata */}
          <div>
            <h3 className="font-serif-jp text-lg md:text-xl font-bold text-[var(--text-color)] leading-tight">
              {titleStr}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] font-mono text-[var(--text-muted)] tracking-wider uppercase">
                {mangaItem.format_type || 'MANGA'} • {mangaItem.status || 'RELEASED'}
              </span>
            </div>
          </div>

          {/* Quick Metrics Badges */}
          <div className="flex flex-wrap gap-2 text-[10px] font-mono">
            {mangaItem.average_score ? (
              <span className="bg-[var(--accent-vermillion)]/15 text-[var(--accent-vermillion)] border border-[var(--accent-vermillion)]/30 px-2.5 py-1 rounded-full font-bold">
                ★ {mangaItem.average_score > 10 ? (mangaItem.average_score / 10).toFixed(1) : mangaItem.average_score} SCORE
              </span>
            ) : null}
            {mangaItem.chapters ? (
              <span className="bg-[var(--surface-color)] text-[var(--text-color)] px-2.5 py-1 rounded-full border border-[var(--border-color)] shadow-sm">
                {mangaItem.chapters} CHAPTERS
              </span>
            ) : null}
            {mangaItem.start_year ? (
              <span className="bg-[var(--surface-color)] text-[var(--text-color)] px-2.5 py-1 rounded-full border border-[var(--border-color)] shadow-sm">
                YEAR {mangaItem.start_year}
              </span>
            ) : null}
          </div>

          {/* Genre Tags */}
          <div className="flex flex-wrap gap-1.5">
            {(Array.isArray(mangaItem.genres) ? mangaItem.genres : []).map((genre, gIdx) => (
              <span 
                key={typeof genre === 'string' ? genre : gIdx}
                className="text-[9px] font-mono bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] px-2.5 py-0.5 rounded-full shadow-sm"
              >
                #{typeof genre === 'string' ? genre : String(genre)}
              </span>
            ))}
          </div>

          {/* Full Synopsis */}
          <div className="space-y-1.5 pt-1">
            <span className="text-[10px] font-mono text-[var(--accent-vermillion)] tracking-widest uppercase font-semibold block">
              Full Synopsis
            </span>
            <p className="text-xs font-serif-jp leading-relaxed text-[var(--text-color)]/90 select-text">
              {getCleanSynopsis(mangaItem.synopsis)}
            </p>
          </div>
        </div>

        {/* Action Footer: AniList Portal (Clean & Focused) */}
        <div className="pt-3 border-t border-[var(--border-color)] flex items-center shrink-0">
          <a 
            href={anilistUrl} 
            target="_blank" 
            rel="noopener noreferrer"
            className="w-full py-2.5 rounded-xl bg-[var(--surface-color)] hover:bg-[var(--accent-vermillion)] text-[var(--text-color)] hover:text-white font-mono text-xs font-bold text-center border border-[var(--border-color)] hover:border-[var(--accent-vermillion)] transition-all flex items-center justify-center gap-2 cursor-pointer shadow-sm group/btn"
          >
            <span>View on AniList</span>
            <span className="text-xs transition-transform group-hover/btn:translate-x-0.5 group-hover/btn:-translate-y-0.5">↗</span>
          </a>
        </div>
      </div>
    );
  };

  // Renders individual discovery card
  const renderCard = (mangaItem, isActive = false) => {
    if (!mangaItem) return null;
    const isBookmarked = Array.isArray(bookmarks) ? bookmarks.some(b => b?.id === mangaItem.id) : false;
    const allowHover = isActive && !isSliding && !(isDesktop && isDetailsOpen);

    const cardTitle = typeof mangaItem.title === 'string' 
      ? mangaItem.title 
      : (mangaItem.title?.english || mangaItem.title?.romaji || mangaItem.title_english || mangaItem.title_romaji || 'Manga Title');
    const authorStr = mangaItem.author || mangaItem.artist || (Array.isArray(mangaItem.staff) ? mangaItem.staff[0] : (typeof mangaItem.staff === 'string' ? mangaItem.staff : null)) || (Array.isArray(mangaItem.authors) ? mangaItem.authors[0] : null) || null;
    const genreFallback = (Array.isArray(mangaItem.genres) && mangaItem.genres.length > 0) ? mangaItem.genres[0] : (mangaItem.format_type || 'MANGA');
    const yearStr = mangaItem.release_year || mangaItem.start_year || '2020';
    const subtitleStr = authorStr ? `${authorStr} • ${yearStr}` : `${genreFallback} • ${yearStr}`;

    return (
      <div 
        className={`w-full h-full relative rounded-[36px] overflow-hidden bg-[var(--surface-color)] select-none shadow-[0_20px_60px_rgba(0,0,0,0.5)] border border-[var(--border-color)] cursor-default ${
          allowHover ? 'group' : ''
        }`}
      >
        {/* 1. FULL-BLEED MANGA COVER IMAGE (Unified Shimmer Paper Skeleton + Smooth Fade) */}
        <SurpriseCoverImage 
          url={mangaItem.cover_image_url} 
          title={cardTitle} 
          allowHover={allowHover} 
        />

        {/* 2. FLOATING TOP HEADER (Status pill & Universal Ribbon Bookmark button) */}
        <div className="absolute top-4 left-5 right-5 flex items-center justify-between z-20 pointer-events-auto">
          <span className="text-[9px] font-mono tracking-widest text-[var(--text-color)] uppercase bg-[var(--surface-color)]/75 backdrop-blur-md px-3 py-1 rounded-full border border-[var(--border-color)] shadow-sm">
            {mangaItem.format_type ? `${mangaItem.format_type} • ` : 'MANGA • '}
            {mangaItem.status || 'COMPLETED'}
          </span>

          {/* Universal Bookmark Ribbon Button matching MangaCard */}
          <button 
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onToggleBookmark(mangaItem);
            }}
            aria-label={isBookmarked ? 'Remove Bookmark' : 'Add Bookmark'}
            title={isBookmarked ? 'Remove Bookmark' : 'Save Bookmark'}
            className={`w-8 h-8 rounded-full flex items-center justify-center border transition-all duration-200 cursor-pointer shadow-sm ${
              isBookmarked 
                ? 'bg-[var(--accent-vermillion)] text-white border-[var(--accent-vermillion)] scale-105 shadow-sm' 
                : 'bg-[var(--surface-color)]/75 text-[var(--text-color)] border-[var(--border-color)] hover:text-[var(--accent-vermillion)] hover:bg-[var(--surface-color)]/95'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill={isBookmarked ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
            </svg>
          </button>
        </div>

        {/* 3. STABLE ACCORDION BOTTOM DETAILS SHEET */}
        <div 
          onClick={(e) => {
            if (isActive) {
              e.stopPropagation();
              setMobileDetailsOpen(prev => !prev);
            }
          }}
          className={`absolute inset-x-0 bottom-0 z-20 p-5 pt-3.5 bg-gradient-to-t from-[var(--surface-color)] via-[var(--surface-color)]/95 to-[var(--surface-color)]/85 border-t border-[var(--border-color)] transition-all duration-350 flex flex-col justify-end ${
            (mobileDetailsOpen || allowHover) ? 'group-hover:shadow-2xl' : ''
          }`}
        >
          {/* Header Peek Area (Always visible at bottom of card, perfectly stable) */}
          <div className="flex items-center justify-between gap-3 shrink-0 cursor-pointer">
            <div className="min-w-0 flex-1">
              <h3 className="font-serif-jp text-base sm:text-lg font-bold text-[var(--text-color)] tracking-tight truncate leading-snug">
                {cardTitle}
              </h3>
              <p className="text-[11px] font-mono text-[var(--text-muted)] truncate pt-0.5">
                {subtitleStr}
              </p>
            </div>

            {/* Score Badge */}
            <div className="shrink-0 flex items-center gap-1.5">
              <span className="text-[10px] font-mono text-[var(--accent-vermillion)] font-bold bg-[var(--surface-color)]/80 px-2 py-0.5 rounded-full border border-[var(--border-color)]">
                ★ {mangaItem.score ? (mangaItem.score / 10).toFixed(1) : (mangaItem.bayesian_rating ? mangaItem.bayesian_rating.toFixed(1) : (mangaItem.average_score ? (mangaItem.average_score / 10).toFixed(1) : '9.0'))}
              </span>
            </div>
          </div>

          {/* REVEALED CONTENT ON HOVER / EXPAND */}
          <div 
            className={`card-details-peek overflow-hidden ${
              mobileDetailsOpen ? 'is-expanded' : ''
            }`}
          >
            <div className="min-h-0 overflow-hidden space-y-2.5">
              
              {/* FINALIZED MOON CREST ❖ DIVIDER */}
              <div className="relative w-full py-0.5 flex items-center justify-center shrink-0">
                <div className="absolute inset-x-3 top-1/2 -translate-y-1/2 h-[1px] bg-gradient-to-r from-transparent via-[var(--border-color)] to-transparent pointer-events-none" />
                <div className="relative px-2.5 py-0.5 bg-[var(--surface-color)] rounded-full border border-[var(--border-color)] text-[10px] text-[var(--accent-vermillion)] font-bold shadow-sm tracking-widest flex items-center gap-1 z-10">
                  <span>❖</span>
                </div>
              </div>

              {/* Minimal Monochrome Genre Pills */}
              <div className="flex flex-wrap gap-1.5">
                {(Array.isArray(mangaItem.genres) && mangaItem.genres.length > 0 
                  ? mangaItem.genres 
                  : ['Action', 'Adventure', 'Supernatural']
                ).slice(0, 3).map((genre, gIdx) => (
                  <span 
                    key={typeof genre === 'string' ? genre : gIdx}
                    className="font-mono rounded-full bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] px-2.5 py-0.5 text-[9px] shadow-sm"
                  >
                    #{typeof genre === 'string' ? genre : String(genre)}
                  </span>
                ))}
              </div>

              {/* Italic Synopsis Excerpt */}
              <p className="font-serif-jp text-[var(--text-muted)] italic text-xs leading-relaxed line-clamp-2 sm:line-clamp-3">
                "{getCleanSynopsis(mangaItem.synopsis)}"
              </p>

              {/* Full-Width Action Button */}
              <button 
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsDetailsOpen(prev => !prev);
                }}
                className={`w-full py-2.5 rounded-full font-mono text-xs font-bold tracking-wider hover:opacity-95 active:scale-95 transition-all shadow-md flex items-center justify-center gap-2 cursor-pointer mt-1 ${
                  isDetailsOpen && isActive
                    ? 'bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] hover:border-[var(--accent-vermillion)] hover:text-[var(--accent-vermillion)]'
                    : 'bg-[var(--accent-vermillion)] text-white'
                }`}
              >
                {isDetailsOpen && isActive ? '← Collapse Details' : 'Full Details →'}
              </button>
            </div>
          </div>

        </div>

      </div>
    );
  };

  const gap = 20;
  const translateY = -(currentIndex * (cardSize.height + gap));

  // Empty or Loading state with aesthetic pulse
  if (titles.length === 0 || loading) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center space-y-3 bg-transparent select-none animate-in fade-in duration-200">
        <div className="w-9 h-9 rounded-xl bg-[var(--surface-color)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-vermillion)] font-bold text-base shadow-md animate-pulse">
          ❖
        </div>
        <span className="text-xs font-mono text-[var(--text-muted)] tracking-widest uppercase animate-pulse">
          Discovering Titles...
        </span>
      </div>
    );
  }

  return (
    <div 
      ref={containerRef}
      className="relative w-full h-full max-h-full overflow-hidden bg-transparent flex flex-col items-center justify-center select-none py-1 cursor-default"
    >
      {/* 1. TOP STATUS / IDLE HINT TOOLBAR (Shown ONLY when inactive for 60 seconds) */}
      <div className="flex items-center justify-center w-full max-w-[410px] px-2 h-7 shrink-0 mb-1.5 pointer-events-none z-20">
        <p 
          className={`transition-opacity duration-1000 text-[10px] sm:text-[11px] font-mono text-[var(--text-muted)]/80 tracking-wide select-none truncate ${
            showHint ? 'opacity-100' : 'opacity-0'
          }`}
        >
          ↕ Scroll wheel or ↑ / ↓ arrows
        </p>
      </div>

      {/* 2. CENTERED DISCOVERY CARD STAGE (DIPTYCH FOLIO) */}
      <div 
        className="relative flex items-center justify-center max-w-full transition-all duration-500 ease-out"
        style={{ transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}
      >
        <div 
          className="flex items-center gap-4 sm:gap-5 transition-all duration-500"
          style={{ transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}
        >
          {/* LEFT: SINGLE CAPSULE VIEWPORT */}
          <div 
            id="card-viewport" 
            onTouchStart={handleTouchStart}
            onTouchEnd={handleTouchEnd}
            style={{ 
              width: `${cardSize.width}px`, 
              height: `${cardSize.height}px` 
            }}
            className="relative overflow-hidden bg-transparent rounded-[36px] shrink-0 transition-all duration-500"
          >
            {/* CONTINUOUS VERTICAL REEL TRACK */}
            <div 
              style={{ 
                transform: `translate3d(0, ${translateY}px, 0)`,
                transition: 'transform 360ms cubic-bezier(0.16, 1, 0.3, 1)',
                willChange: 'transform'
              }}
              className="flex flex-col gap-[20px] items-center"
            >
              {titles.filter(Boolean).map((item, idx) => (
                <div 
                  key={item?.id || idx}
                  style={{ 
                    width: `${cardSize.width}px`, 
                    height: `${cardSize.height}px` 
                  }}
                  className="shrink-0 relative rounded-[36px] overflow-hidden"
                >
                  {renderCard(item, idx === currentIndex)}
                </div>
              ))}
            </div>
          </div>

          {/* RIGHT: COMPANION DOSSIER CARD (DESKTOP SLIDE-OUT) */}
          {isDesktop && (
            <div 
              style={{ 
                width: isDetailsOpen ? `${Math.min(cardSize.width, 390)}px` : '0px', 
                height: `${cardSize.height}px`,
                opacity: isDetailsOpen ? 1 : 0,
                transform: isDetailsOpen ? 'translateX(0)' : 'translateX(-20px)',
                transitionProperty: 'width, opacity, transform',
                transitionDuration: '360ms',
                transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)'
              }}
              className={`rounded-[36px] bg-[var(--surface-color)]/95 backdrop-blur-2xl border border-[var(--border-color)] shadow-[0_25px_70px_rgba(0,0,0,0.65)] flex flex-col justify-between overflow-hidden shrink-0 ${
                isDetailsOpen ? 'pointer-events-auto' : 'pointer-events-none'
              }`}
            >
              {renderDossierContent(titles[currentIndex] || manga, () => setIsDetailsOpen(false))}
            </div>
          )}
        </div>

        {/* 3. FIXED STATIONARY NAVIGATION CONTROLS (ARROWS ONLY, NO FILTER BUTTON IN BETWEEN) */}
        <div 
          className="flex flex-col items-center gap-3 z-30 pointer-events-auto absolute -right-14 sm:-right-16 md:-right-18 top-1/2 -translate-y-1/2 max-[480px]:right-2 transition-all duration-500"
          style={{ transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)' }}
        >
          {/* Up Arrow (Previous) */}
          <button 
            type="button"
            onClick={handlePrev}
            disabled={currentIndex === 0}
            aria-label="Previous Manga"
            className={`w-11 h-11 sm:w-12 sm:h-12 rounded-full bg-[var(--surface-color)]/95 backdrop-blur-xl border flex items-center justify-center shadow-[0_8px_25px_rgba(0,0,0,0.5)] transition-all ${
              currentIndex === 0 
                ? 'opacity-30 border-[var(--border-color)] text-[var(--text-muted)] cursor-not-allowed'
                : 'opacity-100 border-[var(--border-color)] hover:border-[var(--accent-vermillion)] text-[var(--text-color)] hover:text-[var(--accent-vermillion)] hover:scale-110 active:scale-95 cursor-pointer'
            }`}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 15l7-7 7 7" />
            </svg>
          </button>

          {/* Minimal Stream Index Badge */}
          <span className="font-mono text-[9px] sm:text-[10px] text-[var(--text-muted)] bg-[var(--surface-color)]/75 backdrop-blur-md px-2.5 py-1 rounded-full border border-[var(--border-color)] shadow-sm select-none">
            #{String(currentIndex + 1).padStart(2, '0')}
          </span>

          {/* Down Arrow (Next) */}
          <button 
            type="button"
            onClick={handleNext}
            aria-label="Next Manga"
            className="w-11 h-11 sm:w-12 sm:h-12 rounded-full bg-[var(--surface-color)]/95 backdrop-blur-xl border border-[var(--border-color)] hover:border-[var(--accent-vermillion)] text-[var(--text-color)] hover:text-[var(--accent-vermillion)] hover:scale-110 active:scale-95 flex items-center justify-center shadow-[0_8px_25px_rgba(0,0,0,0.5)] transition-all cursor-pointer"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>

      </div>

      {/* MOBILE RESPONSIVE DOSSIER BOTTOM SHEET (< 820px) */}
      {!isDesktop && isDetailsOpen && (
        <div 
          onClick={() => setIsDetailsOpen(false)}
          className="fixed inset-0 z-50 flex items-end justify-center p-3 bg-black/75 backdrop-blur-md animate-in fade-in duration-300 pointer-events-auto"
        >
          <div 
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-md max-h-[82vh] rounded-[32px] bg-[var(--surface-color)]/98 backdrop-blur-2xl border border-[var(--border-color)] shadow-2xl p-5 overflow-hidden flex flex-col justify-between animate-in slide-in-from-bottom duration-300"
          >
            {/* Grab handle */}
            <div className="w-12 h-1.5 rounded-full bg-[var(--text-muted)]/30 mx-auto -mt-1 mb-3" />
            {renderDossierContent(titles[currentIndex] || manga, () => setIsDetailsOpen(false))}
          </div>
        </div>
      )}

      {/* 4. CIRCULAR FILTER BUTTON FLOATING IN BOTTOM-RIGHT CORNER */}
      <button 
        type="button"
        onClick={onOpenFilter}
        aria-label="Discovery Filters"
        title="Discovery Filters"
        className={`fixed bottom-6 right-6 w-12 h-12 rounded-full bg-[var(--surface-color)]/95 backdrop-blur-xl border flex items-center justify-center shadow-[0_10px_30px_rgba(0,0,0,0.5)] transition-all cursor-pointer z-40 pointer-events-auto ${
          hasActiveFilters 
            ? 'border-[var(--accent-vermillion)] text-[var(--accent-vermillion)] scale-105 shadow-[0_0_15px_rgba(230,57,70,0.3)]' 
            : 'border-[var(--border-color)] hover:border-[var(--accent-vermillion)] text-[var(--text-color)] hover:text-[var(--accent-vermillion)] hover:scale-110 active:scale-95'
        }`}
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
        </svg>
        {hasActiveFilters && (
          <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-[var(--accent-vermillion)] border-2 border-[var(--bg-color)]" />
        )}
      </button>

    </div>
  );
}
