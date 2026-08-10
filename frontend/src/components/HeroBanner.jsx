import { useState, useEffect } from 'react';

const FALLBACK_BANNERS = [
  {
    id: 1,
    title: 'Berserk',
    genres: ['Action', 'Dark Fantasy', 'Horror'],
    status: 'FINISHED',
    start_year: 1989,
    average_score: 94,
    synopsis: 'Guts, a mercenary known as the Black Swordsman, seeks sanctuary from demonic forces and vengeance against his former comrade Griffith.',
    cover_image_url: 'https://uploads.mangadex.org/covers/789642f8-ca89-4e4e-8f7b-eee4d17ea08b/60530e72-f76f-45d5-b6f9-f95e05058fc3.png'
  },
  {
    id: 2,
    title: 'Solo Leveling',
    genres: ['Action', 'Supernatural', 'Fantasy'],
    status: 'FINISHED',
    start_year: 2018,
    average_score: 87,
    synopsis: 'Weakest hunter Sung Jinwoo gains the secret ability to level up infinitely, transforming into humanity\'s strongest Shadow Monarch.',
    cover_image_url: 'https://uploads.mangadex.org/covers/32d76d19-8a05-4db0-9fc2-e0b0648fe9d0/3743f5ec-bf3b-4861-bb5c-15a0c8b211bb.jpg'
  },
  {
    id: 3,
    title: 'Chainsaw Man',
    genres: ['Action', 'Supernatural', 'Horror'],
    status: 'RELEASING',
    start_year: 2018,
    average_score: 88,
    synopsis: 'Denji merges with Pochita to become Chainsaw Man, hunting devil threats for Public Safety under Makima.',
    cover_image_url: 'https://uploads.mangadex.org/covers/a77742b1-b6a4-4f14-b67d-4c07f9970f78/e8d53ef6-234b-4f96-bfae-e28a50f146a8.jpg'
  },
  {
    id: 4,
    title: 'Vagabond',
    genres: ['Action', 'Historical', 'Martial Arts'],
    status: 'FINISHED',
    start_year: 1998,
    average_score: 92,
    synopsis: 'Shinmen Takezo evolves into Musashi Miyamoto, pursuing the path of the sword across feudal Japan in search of true strength.',
    cover_image_url: 'https://uploads.mangadex.org/covers/d8a959f7-648e-4c8d-8f23-f1f3f8e129f3/511fc404-e6b4-4204-bb10-e4a28f7b5271.jpg'
  }
];

export default function HeroBanner({ mangas = [], onSelectManga, intervalMs = 5000 }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const [items, setItems] = useState(FALLBACK_BANNERS);

  const shuffleArray = (arr) => [...arr].sort(() => 0.5 - Math.random());

  // Fetch featured titles or shuffle incoming mangas
  useEffect(() => {
    if (mangas && mangas.length > 0) {
      setItems(shuffleArray(mangas).slice(0, 6));
      setCurrentIndex(0);
    } else {
      fetch('http://localhost:8000/manga/featured')
        .then(res => res.json())
        .then(data => {
          if (Array.isArray(data) && data.length > 0) {
            setItems(shuffleArray(data));
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
      {/* Background Image Carousel Layer (Atmospheric Blurred Cover Backing - No Hover Scale) */}
      <div className="relative h-60 sm:h-64 md:h-72 w-full overflow-hidden">
        {items.map((item, idx) => {
          const imgSrc = item.banner_image || item.cover_image_url;

          return (
            <div
              key={item.id || idx}
              className={`absolute inset-0 bg-black/70 transition-opacity duration-1000 ease-in-out ${idx === currentIndex ? 'opacity-100 z-10' : 'opacity-0 z-0 pointer-events-none'
                }`}
            >
              {imgSrc && (
                <img
                  src={imgSrc}
                  alt={item.title}
                  referrerPolicy="no-referrer"
                  className="w-full h-full object-cover blur-xl opacity-50 scale-110"
                  loading="eager"
                  decoding="async"
                />
              )}
              {/* Dark Gradient Overlays */}
              <div className="absolute inset-0 bg-gradient-to-t from-[var(--bg-color)] via-black/40 to-black/30" />
              <div className="absolute inset-0 bg-gradient-to-r from-black/90 via-black/60 to-transparent" />
            </div>
          );
        })}
      </div>

      {/* Floating Info Overlay with Enlarged Exact Cover Art Badge */}
      <div className="absolute inset-0 z-20 p-4 sm:p-5 md:p-6 flex items-center gap-5 sm:gap-6 text-white drop-shadow-lg max-w-5xl pointer-events-none">
        {/* Exact Cover Thumbnail (Enlarged Height near Capsule Borders) */}
        {current.cover_image_url && (
          <div className="w-32 h-52 sm:w-38 sm:h-56 md:w-44 md:h-64 rounded-2xl overflow-hidden border-2 border-white/20 shadow-2xl shrink-0 bg-black/40">
            <img
              src={current.cover_image_url}
              alt={current.title}
              referrerPolicy="no-referrer"
              className="w-full h-full object-cover"
            />
          </div>
        )}

        {/* Text Content */}
        <div className="flex flex-col gap-1.5 min-w-0">
          <h2 className="font-serif-jp text-xl sm:text-2xl md:text-3xl font-extrabold leading-tight text-white group-hover:text-[var(--accent-vermillion)] transition-colors truncate">
            {current.title}
          </h2>

          <div className="flex flex-wrap items-center gap-2 text-xs font-mono text-white/80">
            {current.genres && current.genres.length > 0 && (
              <span>{Array.isArray(current.genres) ? current.genres.slice(0, 3).join(' • ') : current.genres}</span>
            )}
            {current.start_year && <span>• {current.start_year}</span>}
            {current.average_score && (
              <span className="text-[var(--accent-vermillion)] font-bold ml-1">
                ★ {(current.average_score / 10).toFixed(1)}
              </span>
            )}
          </div>

          {current.synopsis && (
            <p className="text-xs text-white/70 font-light line-clamp-2 md:line-clamp-3 leading-relaxed mt-1 font-serif-jp">
              {current.synopsis}
            </p>
          )}
        </div>
      </div>

      {/* Slide Navigation Controls */}
      <div className="absolute bottom-5 right-6 md:right-8 z-30 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          onClick={() => setIsPaused(!isPaused)}
          className="p-1.5 rounded-full bg-black/60 hover:bg-black/90 text-white/80 hover:text-white border border-white/20 text-[10px] font-mono transition-all cursor-pointer"
          title={isPaused ? "Play Autoplay" : "Pause Autoplay"}
        >
          {isPaused ? '▶' : '❚❚'}
        </button>

        <div className="flex items-center gap-1.5 bg-black/50 px-2.5 py-1.5 rounded-full border border-white/20 backdrop-blur-xs">
          {items.map((_, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setCurrentIndex(idx)}
              className={`w-2 h-2 rounded-full transition-all cursor-pointer ${idx === currentIndex
                  ? 'bg-[var(--accent-vermillion)] w-4'
                  : 'bg-white/40 hover:bg-white/80'
                }`}
              title={`Go to slide ${idx + 1}`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
