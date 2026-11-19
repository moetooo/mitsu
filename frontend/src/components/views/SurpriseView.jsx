import { useState, useEffect, useRef, useCallback } from 'react';
import { isCoverCached, markCoverCached } from '../../utils/imageUtils';
import { normalizeTag, getTagStyle } from '../../utils/tagUtils';
import CoverFallback from '../manga/CoverFallback';
import { useCoverSource, coverCandidates } from '../../hooks/useCoverSource';
import useEscapeLayer from '../../hooks/useEscapeLayer';
import { formatScore } from '../../utils/scoreUtils';
import { cleanSynopsis } from '../../utils/text';

import {
  SURPRISE_CARD_LAYOUT,
  SURPRISE_CARD_TEXT
} from '../../utils/surpriseCardLayout';

function SurpriseCoverImage({ manga, title, allowHover }) {
  // The card is the whole screen here, so a dead host is the most visible failure
  // in the app: walk every candidate before falling back to the tile.
  const cover = useCoverSource(manga);
  const isCached = isCoverCached(cover.src);
  const [loaded, setLoaded] = useState(isCached);

  useEffect(() => {
    setLoaded(isCoverCached(cover.src));
  }, [cover.src]);

  const handleLoad = () => {
    markCoverCached(cover.src);
    setLoaded(true);
  };

  const handleError = () => {
    cover.handleError();
    setLoaded(true);
  };

  return (
    // The card aspect (410x600) already matches a manga cover, so the artwork
    // fills it edge to edge. `surpriseImageLength` no longer crops the cover to
    // a band: it sets how far up the card the details scrim reaches (see the
    // sheet below), which keeps the cover whole instead of cut in half.
    <div className="absolute top-0 left-0 w-full h-full select-none overflow-hidden bg-[var(--surface-color)]">
      {/* Feature 34: Shimmer Paper Skeleton Loader matching search cards */}
      {!loaded && !cover.dead && cover.src && (
        <div className="absolute inset-0 shimmer-paper-loading z-10 flex flex-col items-center justify-center p-4">
          <span className="text-base font-heading text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
        </div>
      )}

      {cover.dead || !cover.src ? (
        <CoverFallback title={title} />
      ) : (
        <img 
          src={cover.src} 
          alt={title} 
          referrerPolicy="no-referrer"
          decoding="async"
          // The user asked for this title; there is nothing else to load first.
          loading="eager"
          fetchPriority="high"
          onLoad={handleLoad}
          onError={handleError}
          className={`w-full h-full object-cover select-none pointer-events-none transition-all duration-300 ease-out ${
            loaded ? 'opacity-100' : 'opacity-0'
          } ${allowHover ? 'group-hover:scale-103' : ''}`}
        />
      )}

      {/* No scrims here any more. The status pill and the bookmark chip carry their
          own translucent surface + backdrop blur (>= 6:1 against every art), so the
          top 96px veil was protecting nothing but the art still paid for it. The
          only gradient left on the card is the 64px ribbon at the foot of the
          details sheet, which dissolves the poster into an opaque plate. */}
    </div>
  );
}

export default function SurpriseView({ 
  items = [],
  loading, 
  filters = {},
  isFilterOpen = false,
  onOpenFilter,
  bookmarks = [], 
  onToggleBookmark, 
  imageLength = 60,
  error = null,
  onRetry,
  onNeedMore,
  exhausted = false
}) {
  // FE-10: the queue itself lives in App. This component owns the presentation
  // index only, and asks for more instead of fetching, deduping or holding a
  // second seen-id set of its own.
  const [currentIndex, setCurrentIndex] = useState(0);

  // Sliding state for throttling and hover suppression mid-motion
  const [isSliding, setIsSliding] = useState(false);

  // FE-16: the peek accordion belongs to one card, so it is keyed by manga id
  // instead of being a single flag that followed the user to the next card.
  const [detailsOpenId, setDetailsOpenId] = useState(null);

  // Diptych Folio Full Details state & responsive breakpoint
  const [isDetailsOpen, setIsDetailsOpen] = useState(false);
  const [isDesktop, setIsDesktop] = useState(() => (typeof window !== 'undefined' ? window.innerWidth >= 820 : true));

  // FE-08: the details pane is an Escape layer, so it yields to a layer opened
  // above it (the detail modal) instead of closing alongside it.
  useEscapeLayer(isDetailsOpen, () => setIsDetailsOpen(false));

  // Idle navigation hint state: shows ONLY when inactive for 60 seconds
  const [showHint, setShowHint] = useState(false);
  const idleTimerRef = useRef(null);

  // Responsive card dimensions
  const containerRef = useRef(null);
  const [cardSize, setCardSize] = useState({ width: 390, height: 560 });

  // References
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
    img.referrerPolicy = 'no-referrer';
    img.src = url;
  };

  // Preload covers for the next few titles
  useEffect(() => {
    if (items.length > 0) {
      for (let i = currentIndex; i < Math.min(currentIndex + 4, items.length); i++) {
        const next = items[i];
        if (next) coverCandidates(next).forEach(preloadImage);
      }
    }
  }, [currentIndex, items]);

  // Ask the queue owner for more. The in-flight flag is local so a wheel burst
  // or a re-render cannot start a second batch (the App appends and dedupes).
  const needMoreRef = useRef(false);
  const requestMore = useCallback(async () => {
    if (needMoreRef.current || !onNeedMore) return;
    needMoreRef.current = true;
    try {
      await onNeedMore(5);
    } finally {
      needMoreRef.current = false;
    }
  }, [onNeedMore]);

  // Keep the queue topped up: four ahead is enough to slide smoothly.
  useEffect(() => {
    if (items.length - currentIndex <= 3) {
      requestMore();
    }
  }, [items.length, currentIndex, requestMore]);

  // A fresh draw replaces the queue; the index must not point past its end.
  useEffect(() => {
    if (currentIndex > items.length - 1) {
      setCurrentIndex(Math.max(0, items.length - 1));
    }
  }, [items.length, currentIndex]);

  // Each card owns its own accordion state.
  useEffect(() => {
    setDetailsOpenId(null);
  }, [currentIndex]);

  // Navigation handlers (Vertical physical slide)
  const handleNext = useCallback(() => {
    resetIdleHintTimer();
    if (isSlidingRef.current) return;
    if (currentIndex < items.length - 1) {
      isSlidingRef.current = true;
      lastSlideTimeRef.current = Date.now();
      setIsSliding(true);
      setCurrentIndex(prev => prev + 1);
      setTimeout(() => {
        setIsSliding(false);
        isSlidingRef.current = false;
      }, 360);
    } else {
      // End of the buffer: one owner fetches, this only asks.
      requestMore();
    }
  }, [currentIndex, items.length, requestMore, resetIdleHintTimer]);

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

  // Keyboard navigation (Arrow keys, PageUp/Down, J/K). Escape is not handled
  // here any more: it belongs to the topmost overlay layer (useEscapeLayer).
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
      // An overlay on top of this view owns the keyboard while it is open.
      if (e.target?.closest?.('[role="dialog"]')) return;

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
  }, [handleNext, handlePrev, resetIdleHintTimer]);

  // Touch swipe support on card
  const handleTouchStart = (e) => {
    resetIdleHintTimer();
    touchStartYRef.current = e.touches[0].clientY;
  };

  const handleTouchEnd = (e) => {
    resetIdleHintTimer();
    if (hasTextSelection()) return;
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


  // Filter counters
  const excludedCount = filters.exclude_genres?.length || 0;
  const includedCount = filters.genres?.length || 0;
  const hasActiveFilters = (
    excludedCount > 0 || 
    includedCount > 0 || 
    Boolean(filters.format_type) || 
    (filters.min_score > 0) || 
    (filters.status?.length > 0) ||
    Boolean(filters.min_year) ||
    Boolean(filters.max_year) ||
    Boolean(filters.min_chapters) ||
    Boolean(filters.max_chapters) ||
    (filters.min_match_pct > 0)
  );

  // A drag that ended in highlighted text is a copy gesture, not a card tap.
  // Without this, selecting the title would also toggle the peek accordion and
  // a touch selection would slide to the next card.
  const hasTextSelection = () => {
    if (typeof window === 'undefined' || !window.getSelection) return false;
    return window.getSelection().toString().trim().length > 0;
  };

  // Renders the Companion Dossier Card Content (Shared between desktop folio & mobile sheet)
  const renderDossierContent = (mangaItem, onClose) => {
    if (!mangaItem) return null;
    const titleStr = typeof mangaItem.title === 'string' 
      ? mangaItem.title 
      : (mangaItem.title?.english || mangaItem.title?.romaji || mangaItem.title_english || mangaItem.title_romaji || 'Manga Title');
    const anilistUrl = mangaItem.anilist_id 
      ? `https://anilist.co/manga/${mangaItem.anilist_id}` 
      : `https://anilist.co/search/manga?search=${encodeURIComponent(titleStr)}`;

    return (
      <div className="p-5 sm:p-6 w-full h-full flex flex-col justify-between select-text bg-transparent">
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
            <h3 className="font-heading text-lg md:text-xl font-bold text-[var(--text-color)] leading-tight">
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
                ★ {formatScore(mangaItem.average_score)} SCORE
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

          {/* Inferred Narrative Tags */}
          {Array.isArray(mangaItem.inferred_tags) && mangaItem.inferred_tags.length > 0 && (
            <div className="space-y-1 pt-0.5">
              <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-wider font-semibold block">
                Narrative Elements
              </span>
              <div className="flex flex-wrap gap-1.5">
                {mangaItem.inferred_tags.slice(0, 6).map((t, idx) => {
                  const tag = normalizeTag(t);
                  const style = getTagStyle(tag.category);
                  const pct = Math.round(tag.confidence * 100);
                  return (
                    <span 
                      key={tag.slug || tag.name || idx}
                      title={`${tag.name} (${tag.category}) • ${pct}% confidence`}
                      className={`inline-flex items-center gap-1 text-[9px] font-mono px-2 py-0.5 rounded-full border shadow-sm ${style.bg} ${style.border} ${style.text}`}
                    >
                      <span className={`w-1 h-1 rounded-full ${style.dot}`} />
                      <span>{tag.name}</span>
                    </span>
                  );
                })}
              </div>
            </div>
          )}

          {/* Full Synopsis */}
          <div className="space-y-1.5 pt-1">
            <span className="text-[10px] font-mono text-[var(--accent-vermillion)] tracking-widest uppercase font-semibold block">
              Full Synopsis
            </span>
            <p className="text-xs font-heading leading-relaxed text-[var(--text-color)]/90 select-text">
              {cleanSynopsis(mangaItem.synopsis)}
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
    // FE-16: only the card whose id is stored can be expanded.
    const detailsOpen = detailsOpenId === mangaItem.id;

    const cardTitle = typeof mangaItem.title === 'string' 
      ? mangaItem.title 
      : (mangaItem.title?.english || mangaItem.title?.romaji || mangaItem.title_english || mangaItem.title_romaji || 'Manga Title');

    // The hover reveal shows the card's real genre and year. Both used to have
    // invented fallbacks ('Action', 'Adventure', 'Supernatural' / '2020'), which
    // put titles that have no such genres and no release year in front of the
    // reader as if the catalog said so. Values now come only from the record:
    // genre from `genres[0]` (falling back to the format, e.g. MANGA), year
    // from `release_year` then `start_year`.
    const genres = (Array.isArray(mangaItem.genres) ? mangaItem.genres : [])
      .map(genre => (typeof genre === 'string' ? genre : genre?.name))
      .filter(genre => typeof genre === 'string' && genre.trim())
      .map(genre => genre.trim());
    const primaryGenre = genres[0] || mangaItem.format_type || null;
    const yearStr = mangaItem.release_year || mangaItem.start_year || null;
    const subtitleStr = [primaryGenre, yearStr].filter(Boolean).join(' • ');

    return (
      <div 
        className={`w-full h-full relative rounded-[36px] overflow-hidden bg-[var(--surface-color)] shadow-[0_20px_60px_rgba(0,0,0,0.5)] border border-[var(--border-color)] cursor-default ${
          allowHover ? 'group' : ''
        }`}
        data-surprise-card=""
        data-expanded={detailsOpen ? 'true' : 'false'}
        style={{
          '--surprise-text-y': `${SURPRISE_CARD_TEXT.TEXT_OFFSET_Y}px`,
          '--surprise-text-y-hover': `${SURPRISE_CARD_TEXT.TEXT_OFFSET_Y_HOVER}px`,
          '--surprise-expanded-drop': `${SURPRISE_CARD_LAYOUT.EXPANDED_DROP}px`,
          '--surprise-title-size': `${SURPRISE_CARD_TEXT.TITLE_SIZE_MOBILE}px`,
          '--surprise-title-size-sm': `${SURPRISE_CARD_TEXT.TITLE_SIZE_DESKTOP}px`,
          '--surprise-title-weight': SURPRISE_CARD_TEXT.TITLE_WEIGHT,
          '--surprise-title-leading': SURPRISE_CARD_TEXT.TITLE_LINE_HEIGHT,
          '--surprise-title-tracking': `${SURPRISE_CARD_TEXT.TITLE_TRACKING_EM}em`,
          '--surprise-title-lines': SURPRISE_CARD_TEXT.TITLE_LINES,
          '--surprise-meta-size': `${SURPRISE_CARD_TEXT.META_SIZE}px`,
          '--surprise-meta-weight': SURPRISE_CARD_TEXT.META_WEIGHT,
          '--surprise-meta-leading': SURPRISE_CARD_TEXT.META_LINE_HEIGHT,
          '--surprise-meta-tracking': `${SURPRISE_CARD_TEXT.META_TRACKING_EM}em`,
          '--surprise-status-size': `${SURPRISE_CARD_TEXT.STATUS_SIZE}px`,
          '--surprise-status-weight': SURPRISE_CARD_TEXT.STATUS_WEIGHT,
          '--surprise-status-tracking': `${SURPRISE_CARD_TEXT.STATUS_TRACKING_EM}em`,
          '--surprise-status-pad-x': `${SURPRISE_CARD_TEXT.STATUS_PAD_X}px`,
          '--surprise-status-pad-y': `${SURPRISE_CARD_TEXT.STATUS_PAD_Y}px`,
          '--surprise-status-radius': `${SURPRISE_CARD_TEXT.STATUS_RADIUS}px`,
          '--surprise-synopsis-size': `${SURPRISE_CARD_TEXT.SYNOPSIS_SIZE}px`,
          '--surprise-synopsis-leading': SURPRISE_CARD_TEXT.SYNOPSIS_LINE_HEIGHT,
          '--surprise-synopsis-lines-mobile': SURPRISE_CARD_TEXT.SYNOPSIS_LINES_MOBILE,
          '--surprise-synopsis-lines': SURPRISE_CARD_TEXT.SYNOPSIS_LINES_DESKTOP,
          '--surprise-button-size': `${SURPRISE_CARD_TEXT.BUTTON_SIZE}px`,
          '--surprise-button-weight': SURPRISE_CARD_TEXT.BUTTON_WEIGHT,
          '--surprise-button-tracking': `${SURPRISE_CARD_TEXT.BUTTON_TRACKING_EM}em`,
          '--surprise-button-pad-y': `${SURPRISE_CARD_TEXT.BUTTON_PAD_Y}px`,
          '--surprise-button-radius': `${SURPRISE_CARD_TEXT.BUTTON_RADIUS}px`
        }}
      >
        {/* 1. FULL-BLEED MANGA COVER IMAGE (Unified Shimmer Paper Skeleton + Smooth Fade) */}
        <SurpriseCoverImage 
          manga={mangaItem}
          title={cardTitle} 
          allowHover={allowHover}
        />

        {/* 2. FLOATING TOP HEADER (Status pill & Universal Ribbon Bookmark button) */}
        <div className="absolute top-4 left-5 right-5 flex items-center justify-between z-20 pointer-events-auto">
          <span className="surprise-card-status font-mono text-[var(--text-color)] uppercase bg-[var(--surface-color)]/75 backdrop-blur-md border border-[var(--border-color)] shadow-sm">
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
            if (hasTextSelection()) return;
            if (isActive) {
              e.stopPropagation();
              setDetailsOpenId(prev => (prev === mangaItem.id ? null : mangaItem.id));
            }
          }}
          style={{ minHeight: `${Math.max(0, 100 - imageLength)}%` }}
          className={`absolute inset-x-0 bottom-0 z-20 transition-all duration-350 flex flex-col justify-end`}
        >
          {/* The fade is a flexible filler, not a fixed ribbon. `surpriseImageLength`
              still sets how far up the card the scrim reaches (it is the sheet's min
              height); the filler takes whatever room the plate does not need, so the
              gradient always ends exactly where the plate begins -- a 1px lip above the
              title -- instead of hovering above a flat band of surface.
              `min-h-16` is what keeps it there once the peek expands: an open peek can
              eat the whole min height on a short card, and without the floor the card
              lost its fade the moment the pointer landed on it. */}
          <div
            className="flex-1 min-h-16 pointer-events-none"
            style={{
              background:
                'linear-gradient(to top, var(--surface-color) 0, var(--surface-color) 1px, transparent 100%)',
            }}
            aria-hidden="true"
          />

          {/* The plate: opaque, hugging the text, so the title never depends on how
              bright the cover behind it is. */}
          <div
            className={`bg-[var(--surface-color)] ${(detailsOpen || allowHover) ? 'group-hover:shadow-2xl' : ''}`}
            data-card-plate=""
            style={{
              padding: `${SURPRISE_CARD_LAYOUT.PLATE_TOP}px ${SURPRISE_CARD_LAYOUT.PLATE_SIDE}px ${SURPRISE_CARD_LAYOUT.PLATE_BOTTOM}px`
            }}
          >
            {/* Header Peek Area (Always visible at bottom of card, perfectly stable).
                `data-card-text` reads its Y position from the card: the resting
                TEXT_OFFSET_Y, or TEXT_OFFSET_Y_HOVER while hovered / expanded. */}
            <div className="flex items-center justify-between gap-3 shrink-0 cursor-pointer" data-card-text="">
              <div className="min-w-0 flex-1">
                <h3 className="font-heading surprise-card-title text-[var(--text-color)] select-text cursor-text">
                  {cardTitle}
                </h3>
                <p
                  className="font-mono surprise-card-meta text-[var(--text-muted)] truncate select-text cursor-text"
                  data-card-meta=""
                  style={{ marginTop: `${SURPRISE_CARD_TEXT.META_OFFSET_Y}px` }}
                >
                  {subtitleStr}
                </p>
              </div>
            </div>

            {/* REVEALED CONTENT ON HOVER / EXPAND */}
            <div 
              className={`card-details-peek overflow-hidden ${
                detailsOpen ? 'is-expanded' : ''
              }`}
            >
              <div
                className="min-h-0 overflow-hidden"
                data-card-reveal=""
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: `${SURPRISE_CARD_LAYOUT.SECTION_GAP}px`
                }}
              >
              
                {/* FINALIZED MOON CREST ❖ DIVIDER */}
                <div className="relative w-full py-0.5 flex items-center justify-center shrink-0">
                  <div className="absolute inset-x-3 top-1/2 -translate-y-1/2 h-[1px] bg-gradient-to-r from-transparent via-[var(--border-color)] to-transparent pointer-events-none" />
                  <div className="relative px-2.5 py-0.5 bg-[var(--surface-color)] rounded-full border border-[var(--border-color)] text-[10px] text-[var(--accent-vermillion)] font-bold shadow-sm tracking-widest flex items-center gap-1 z-10">
                    <span>❖</span>
                  </div>
                </div>

                {/* Minimal Monochrome Genre Pills. Only the genres the record
                    carries: no placeholder list when `genres` is empty. */}
                {genres.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {genres.slice(0, 3).map((genre, gIdx) => (
                      <span 
                        key={`${genre}-${gIdx}`}
                        className="font-mono rounded-full bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] px-2.5 py-0.5 shadow-sm"
                        style={{ fontSize: `${SURPRISE_CARD_TEXT.PILL_SIZE}px` }}
                      >
                        #{genre}
                      </span>
                    ))}
                  </div>
                )}

                {/* Italic Synopsis Excerpt */}
                <p className="font-heading surprise-card-synopsis text-[var(--text-muted)] italic select-text">
                  "{cleanSynopsis(mangaItem.synopsis)}"
                </p>

                {/* Full-Width Action Button */}
                <button 
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setIsDetailsOpen(prev => !prev);
                  }}
                  className={`w-full surprise-card-action font-mono hover:opacity-95 active:scale-95 transition-all shadow-md flex items-center justify-center gap-2 cursor-pointer mt-1 ${
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

      </div>
    );
  };

  const gap = 20;
  const translateY = -(currentIndex * (cardSize.height + gap));

  // Empty, loading, failed and exhausted are four different things (FE-25).
  if (items.length === 0) {
    const failed = Boolean(error);
    return (
      <div
        role="status"
        aria-live="polite"
        className="w-full h-full flex flex-col items-center justify-center space-y-3 bg-transparent select-none animate-in fade-in duration-200"
      >
        <div className={`w-9 h-9 rounded-xl bg-[var(--surface-color)] border border-[var(--border-color)] flex items-center justify-center text-[var(--accent-vermillion)] font-bold text-base shadow-md ${exhausted || failed || !loading ? '' : 'animate-pulse'}`}>
          ❖
        </div>
        <span className={`text-xs font-mono text-[var(--text-muted)] tracking-widest uppercase ${exhausted || failed || !loading ? '' : 'animate-pulse'}`}>
          {failed ? 'Could not draw a title' : exhausted ? 'No titles match these filters' : 'Discovering Titles...'}
        </span>
        {failed && (
          <>
            <span className="text-[11px] font-mono text-[var(--text-muted)]/70 tracking-wide text-center max-w-xs">
              {error}
            </span>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="px-4 py-1.5 rounded-full border border-[var(--border-color)] bg-[var(--surface-color)] text-[11px] font-mono uppercase tracking-widest text-[var(--text-color)] hover:border-[var(--accent-vermillion)] hover:text-[var(--accent-vermillion)] cursor-pointer"
              >
                Try again
              </button>
            )}
          </>
        )}
        {exhausted && !failed && (
          <span className="text-[11px] font-mono text-[var(--text-muted)]/70 tracking-wide">
            Loosen a filter, then click Surprise Me again
          </span>
        )}
      </div>
    );
  }

  return (
    <div 
      ref={containerRef}
      className="relative w-full h-full max-h-full overflow-hidden bg-transparent flex flex-col items-center justify-center py-1 cursor-default"
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
              {items.map((item, idx) => (
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
              {renderDossierContent(items[currentIndex], () => setIsDetailsOpen(false))}
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
            {renderDossierContent(items[currentIndex], () => setIsDetailsOpen(false))}
          </div>
        </div>
      )}

      {/* 4. CIRCULAR FILTER BUTTON FLOATING IN BOTTOM-RIGHT CORNER */}
      {!isFilterOpen && (
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
      )}

    </div>
  );
}
