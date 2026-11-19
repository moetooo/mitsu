import { useState, useEffect, useRef } from 'react';
import { isCoverCached, markCoverCached } from '../../utils/imageUtils';
import CoverFallback from '../manga/CoverFallback';
import { useCoverSource } from '../../hooks/useCoverSource';
import { API_ROUTES } from '../../config';
import { formatScore } from '../../utils/scoreUtils';
import { cleanSynopsis } from '../../utils/text';

function HeroCoverThumbnail({ manga }) {
  // Same candidate walk as the grid cards: the hero shows the most visible cover
  // on the page, so it must not be the one place that gives up on the first host.
  const cover = useCoverSource(manga);
  const title = manga?.title;
  const isCached = isCoverCached(cover.src);
  const [loaded, setLoaded] = useState(isCached);
  const [error, setError] = useState(false);

  useEffect(() => {
    setError(false);
    setLoaded(isCoverCached(cover.src));
  }, [cover.src]);

  return (
    <div className="w-32 h-52 sm:w-38 sm:h-56 md:w-44 md:h-64 rounded-2xl overflow-hidden border-2 border-[var(--hero-thumb-border)] shadow-2xl shrink-0 bg-[var(--hero-thumb-bg)] relative group-hover:scale-[1.02] transition-transform">
      {!loaded && !error && cover.src && (
        <div className="absolute inset-0 shimmer-paper-loading z-10 flex flex-col items-center justify-center p-4">
          <span className="text-base font-heading text-[var(--accent-vermillion)] opacity-60 animate-pulse">❖</span>
        </div>
      )}
      {error || !cover.src ? (
        <CoverFallback title={title} />
      ) : (
        <img
          src={cover.src}
          alt={title}
          referrerPolicy="no-referrer"
          decoding="async"
          // This is the largest element above the fold on first paint.
          loading="eager"
          fetchPriority="high"
          width={400}
          height={600}
          onLoad={() => {
            markCoverCached(cover.src);
            setLoaded(true);
          }}
          onError={() => {
            cover.handleError();
            if (cover.remaining === 0) setError(true);
            setLoaded(true);
          }}
          className={`w-full h-full object-cover transition-opacity duration-300 ${loaded ? 'opacity-100' : 'opacity-0'}`}
        />
      )}
    </div>
  );
}

// Shown only until the catalogue answers. These four used to point at
// uploads.mangadex.org, which now serves an HTML challenge page to browsers:
// the banner was broken art on the first paint of every visit. They are the same
// four titles, re-sourced from the host the catalogue itself uses.
const FALLBACK_BANNERS = [
  {
    id: 1,
    title: 'Berserk',
    genres: ['Action', 'Dark Fantasy', 'Horror'],
    status: 'FINISHED',
    start_year: 1989,
    average_score: 94,
    synopsis: 'Guts, a mercenary known as the Black Swordsman, seeks sanctuary from demonic forces and vengeance against his former comrade Griffith.',
    cover_image_url: 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx30002-Cul4OeN7bYtn.jpg'
  },
  {
    id: 2,
    title: 'Solo Leveling',
    genres: ['Action', 'Supernatural', 'Fantasy'],
    status: 'FINISHED',
    start_year: 2018,
    average_score: 87,
    synopsis: 'Weakest hunter Sung Jinwoo gains the secret ability to level up infinitely, transforming into humanity\'s strongest Shadow Monarch.',
    cover_image_url: 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx105398-b673Vt5ZSuz3.jpg'
  },
  {
    id: 3,
    title: 'The Horizon',
    genres: ['Drama', 'Psychological', 'Tragedy'],
    status: 'FINISHED',
    start_year: 2016,
    average_score: 89,
    synopsis: 'A young boy and girl meet amidst the ruins of a war-torn world, embarking on a quiet journey towards an uncertain horizon.',
    cover_image_url: 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx100568-4BC0PsdwU4bL.png'
  },
  {
    id: 4,
    title: 'Vagabond',
    genres: ['Action', 'Historical', 'Martial Arts'],
    status: 'FINISHED',
    start_year: 1998,
    average_score: 92,
    synopsis: 'Shinmen Takezo evolves into Musashi Miyamoto, pursuing the path of the sword across feudal Japan in search of true strength.',
    cover_image_url: 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx30656-9mW113O7rDnA.png'
  }
];

export default function HeroBanner({ mangas = [], onSelectManga, intervalMs = 5000 }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  // Background art that already failed. Keyed by item, so one dead banner does
  // not blank the whole carousel.
  const [brokenBackgrounds, setBrokenBackgrounds] = useState(() => new Set());
  const markBackgroundBroken = (key) => setBrokenBackgrounds((prev) => {
    if (prev.has(key)) return prev;
    const next = new Set(prev);
    next.add(key);
    return next;
  });
  const [items, setItems] = useState(FALLBACK_BANNERS);
  // Which result set the current mix was built from, so appended pages do not
  // rebuild (and reshuffle) it.
  const mixSignatureRef = useRef('');

  const shuffleArray = (arr) => [...arr].sort(() => 0.5 - Math.random());

  const processMixBannerItems = (rawItems) => {
    if (!rawItems || rawItems.length === 0) return FALLBACK_BANNERS;

    // FE-21: the pools are built from the score alone. The old split read
    // `item.popularity`, which `RecommendationResult` does not carry, so
    // `pop` was always 0, every 80+ title landed in "underrated" and the
    // acclaimed pool was unreachable -- the banner was not mixed at all.
    const acclaimed = [];
    const solid = [];
    const popular = [];

    rawItems.forEach(item => {
      const score = item.average_score || 0;

      if (score >= 85) {
        acclaimed.push(item);
      } else if (score >= 70) {
        solid.push(item);
      } else {
        popular.push(item);
      }
    });

    const mixed = [];
    const pick = (arr, count) => {
      const shuffled = shuffleArray(arr);
      for (let i = 0; i < Math.min(count, shuffled.length); i++) {
        if (!mixed.some(m => m.id === shuffled[i].id)) {
          mixed.push(shuffled[i]);
        }
      }
    };

    // Pick 2 from each pool so the banner is not six copies of the same tier
    pick(acclaimed, 2);
    pick(solid, 2);
    pick(popular, 2);

    // Fill up to 6 if any pool was short
    if (mixed.length < 6) {
      for (const item of shuffleArray(rawItems)) {
        if (!mixed.some(m => m.id === item.id)) {
          mixed.push(item);
          if (mixed.length >= 6) break;
        }
      }
    }

    return shuffleArray(mixed);
  };

  // Fetch featured titles or process incoming search mangas into randomized mix
  useEffect(() => {
    if (mangas && mangas.length > 0) {
      const signature = mangas.map(m => m.id).join(',');
      const previous = mixSignatureRef.current;
      if (previous && signature.startsWith(previous)) {
        // Page N+1 of the same query: the mix already on screen stays, so the
        // carousel neither reshuffles nor snaps back to slide 0 while the user
        // is reading it.
        return;
      }
      mixSignatureRef.current = signature;
      setItems(processMixBannerItems(mangas));
      setCurrentIndex(0);
    } else {
      mixSignatureRef.current = '';
      fetch(API_ROUTES.featured)
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            setItems(processMixBannerItems(data));
          } else {
            setItems(shuffleArray(FALLBACK_BANNERS));
          }
        })
        .catch(() => setItems(shuffleArray(FALLBACK_BANNERS)));
    }
  }, [mangas]);

  useEffect(() => {
    if (isPaused || items.length === 0) return;
    const timer = setInterval(() => {
      setCurrentIndex(prev => (prev + 1) % items.length);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [isPaused, intervalMs, items.length]);

  if (!items || items.length === 0) return null;

  const current = items[currentIndex] || items[0];

  return (
    <div
      onClick={() => onSelectManga && onSelectManga(current)}
      className="w-full max-w-6xl mx-auto relative rounded-3xl overflow-hidden border border-[var(--border-color)] shadow-xl bg-[var(--surface-color)] group select-none transition-all duration-300 cursor-pointer hover:border-[var(--accent-vermillion)]"
      title={`Click to view details for ${current.title}`}
    >
      {/* Background Image Carousel Layer */}
      <div className="relative h-60 sm:h-64 md:h-72 w-full overflow-hidden">
        {items.map((item, idx) => {
          const backgroundKey = item.id ?? `idx-${idx}`;
          const imageCandidates = [item.banner_image, item.cover_image_url].filter(Boolean);
          const imgSrc = brokenBackgrounds.has(`${backgroundKey}:${imageCandidates[0]}`) ? null : imageCandidates[0];

          return (
            <div
              key={item.id || idx}
              className={`absolute inset-0 bg-[var(--hero-veil)] transition-opacity duration-1000 ease-in-out ${idx === currentIndex ? 'opacity-100 z-10' : 'opacity-0 z-0 pointer-events-none'
                }`}
            >
              {imgSrc && (
                <img
                  src={imgSrc}
                  alt=""
                  referrerPolicy="no-referrer"
                  className="w-full h-full object-cover blur-xl opacity-[var(--hero-art-opacity)] scale-110"
                  // Only the slide being shown is worth fetching; the rest are behind
                  // a 1s fade and used to be downloaded `eager` all at once.
                  loading={idx === currentIndex ? 'eager' : 'lazy'}
                  fetchPriority={idx === currentIndex ? 'high' : 'low'}
                  decoding="async"
                  aria-hidden="true"
                  onError={() => markBackgroundBroken(`${backgroundKey}:${imgSrc}`)}
                />
              )}
              {/* Dark Gradient Overlays */}
              <div className="absolute inset-0 bg-gradient-to-t from-[var(--hero-scrim-from)] via-[var(--hero-scrim-via)] to-[var(--hero-scrim-to)]" />
              <div className="absolute inset-0 bg-gradient-to-r from-[var(--hero-side-from)] via-[var(--hero-side-via)] to-transparent" />
            </div>
          );
        })}
      </div>

      {/* Floating Info Overlay with Enlarged Cover Art */}
      <div
        className="absolute inset-0 z-20 p-4 sm:p-5 md:p-6 flex items-center gap-5 sm:gap-6 max-w-5xl pointer-events-none"
        style={{ color: 'var(--hero-ink)', filter: 'var(--hero-ink-shadow)' }}
      >
        {/* Exact Cover Thumbnail. Always rendered: with no usable art it draws the
            generated tile, which keeps the text column aligned with every other
            slide instead of jumping left. */}
        <HeroCoverThumbnail manga={current} />

        {/* Text Content */}
        <div className="flex flex-col gap-1.5 min-w-0">
          <h2 className="font-heading text-xl sm:text-2xl md:text-3xl font-extrabold leading-tight group-hover:text-[var(--accent-vermillion)] transition-colors truncate">
            {current.title}
          </h2>

          <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-[var(--hero-ink-muted)]">
            {current.genres && current.genres.length > 0 && (
              <span>{Array.isArray(current.genres) ? current.genres.slice(0, 3).join(' • ') : current.genres}</span>
            )}
            {current.start_year && <span>• {current.start_year}</span>}
            {current.average_score && (
              <span className="text-[var(--accent-vermillion)] font-bold ml-1">
                ★ {formatScore(current.average_score)}
              </span>
            )}
          </div>

          {current.synopsis && (
            <p className="text-xs text-[var(--hero-ink-soft)] font-light line-clamp-2 md:line-clamp-3 leading-relaxed mt-1 font-heading">
              {cleanSynopsis(current.synopsis, '')}
            </p>
          )}
        </div>
      </div>

      {/* Slide Navigation Controls */}
      <div className="absolute bottom-5 right-6 md:right-8 z-30 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          onClick={() => setIsPaused(!isPaused)}
          className="p-1.5 rounded-full bg-[var(--hero-chip-bg)] hover:bg-[var(--hero-chip-bg-hover)] text-[var(--hero-ink-muted)] hover:text-[var(--hero-ink)] border border-[var(--hero-chip-border)] text-[10px] font-mono transition-all cursor-pointer"
          title={isPaused ? "Play Autoplay" : "Pause Autoplay"}
        >
          {isPaused ? '▶' : '❚❚'}
        </button>

        <div className="flex items-center gap-1.5 bg-[var(--hero-chip-bg)] px-2.5 py-1.5 rounded-full border border-[var(--hero-chip-border)] backdrop-blur-xs">
          {items.map((_, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setCurrentIndex(idx)}
              className={`w-2 h-2 rounded-full transition-all cursor-pointer ${idx === currentIndex
                  ? 'bg-[var(--accent-vermillion)] w-4'
                  : 'bg-[var(--hero-dot)] hover:bg-[var(--hero-dot-hover)]'
                }`}
              title={`Go to slide ${idx + 1}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
