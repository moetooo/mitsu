import { useState, useEffect } from 'react';

const hoverBorderMap = {
  vermillion: 'hover:border-[var(--accent-vermillion)]',
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
  hoverAccent = 'vermillion'
}) {
  const [similar, setSimilar] = useState([]);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [copied, setCopied] = useState(false);

  const matchPct = manga?.similarity_score !== undefined ? Math.round(manga.similarity_score * 100) : null;
  const activeHover = hoverBorderMap[hoverAccent] || hoverBorderMap.vermillion;

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

  useEffect(() => {
    if (manga) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [manga]);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    if (!manga) {
      setSimilar([]);
      return;
    }
    
    let isMounted = true;
    const fetchSimilar = async () => {
      setLoadingSimilar(true);
      try {
        const res = await fetch(`http://localhost:8000/manga/${manga.id}/similar?limit=6`);
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
  }, [manga]);

  if (!manga) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-200">
      
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/80 backdrop-blur-sm transition-all"
        onClick={onClose}
      />
      
      {/* Washi/Sumi Japanese Modal Box */}
      <div className="relative bg-[var(--surface-color)] border border-[var(--border-color)] w-full max-w-5xl max-h-[90vh] overflow-hidden rounded-3xl shadow-2xl flex flex-col z-10 text-[var(--text-color)]">
        
        {/* Top Header Bar */}
        <div className="flex items-center justify-between px-6 py-3.5 border-b border-[var(--border-color)] bg-[var(--bg-color)]/50 shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-xs font-serif-jp text-[var(--accent-vermillion)]">❖</span>
            <span className="text-xs font-mono uppercase text-[var(--text-muted)] tracking-wider">Manga Details</span>
          </div>

          <div className="flex items-center gap-2.5">
            {/* Share Button Icon Only */}
            <button
              type="button"
              className={`p-2 text-[var(--text-muted)] hover:text-[var(--text-color)] bg-[var(--surface-color)] border border-[var(--border-color)] ${activeHover} rounded-full transition-colors cursor-pointer`}
              title="Share"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
              </svg>
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
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>
        
        {/* Scrollable Body */}
        <div className="flex flex-col md:flex-row md:items-start flex-grow overflow-y-auto overflow-x-hidden min-w-0 max-w-full custom-scrollbar min-h-0">
          
          {/* Clean Left Column (No Half-Length Border Lines or Double Card Boxes) */}
          <div className="w-full md:w-80 lg:w-[320px] shrink-0 p-5 md:p-6 flex flex-col gap-4 items-center md:items-stretch md:sticky md:top-0 h-fit">
            
            {/* Cover Image & Vertical Genre Stamp Container */}
            <div className="flex gap-3.5 w-full items-center justify-center">
              {/* Vertical Text Sidebar */}
              {manga.genres && manga.genres.length > 0 && (
                <div className="hidden sm:flex flex-col items-center py-2 select-none shrink-0">
                  <span className="vertical-text font-mono text-[10px] text-[var(--text-muted)] tracking-widest uppercase border-l border-[var(--border-color)] pl-1.5">
                    GENRES
                  </span>
                </div>
              )}

              {/* Framed Print Cover */}
              <div className="relative w-full max-w-[260px] md:max-w-none aspect-[2/3] rounded-2xl overflow-hidden border border-[var(--border-color)] shadow-lg bg-black/40">
                <img 
                  src={manga.cover_image_url} 
                  alt={manga.title}
                  referrerPolicy="no-referrer"
                  className="w-full h-full object-cover"
                />
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

            {/* AI Match Analysis Box */}
            {manga.llm_reasoning && (
              <div className="w-full max-w-[260px] md:max-w-none mx-auto bg-[var(--surface-color)] border-l-4 border-[var(--accent-vermillion)] p-4 rounded-r-2xl shadow-xs space-y-1">
                <span className="text-[10px] font-bold text-[var(--accent-vermillion)] uppercase tracking-wider font-mono block">
                  AI Match Analysis
                </span>
                <p className="text-xs text-[var(--text-color)] font-light leading-relaxed font-serif-jp italic">
                  "{manga.llm_reasoning}"
                </p>
              </div>
            )}
          </div>



          
          {/* Content Details */}
          <div className="p-6 md:p-8 flex flex-col gap-6 flex-grow min-w-0 max-w-full">

            
            <div>
              <h2 className="text-2xl md:text-4xl font-serif-jp font-bold text-[var(--text-color)] mb-3 leading-snug">
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
                  <span className="px-3 py-1 rounded-full bg-[var(--hanko-bg)] text-[var(--accent-vermillion)] border border-[var(--accent-vermillion)] font-bold">
                    ★ {(manga.average_score / 10).toFixed(1)} / 10
                  </span>
                )}
              </div>
            </div>

            {/* Synopsis */}
            <div className="space-y-1.5">
              <h3 className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
                Synopsis
              </h3>
              <p className="text-[var(--text-color)] text-xs md:text-sm leading-relaxed whitespace-pre-wrap font-light">
                {manga.synopsis || "No detailed synopsis available."}
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
                      className={`px-3 py-1 bg-[var(--bg-color)] ${activeHover} hover:text-[var(--accent-vermillion)] text-[var(--text-color)] text-xs rounded-full border border-[var(--border-color)] transition-all cursor-pointer font-serif-jp`}
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
                  More Like This
                </h3>
                <span className="text-[10px] text-[var(--text-muted)] font-mono">Click to preview</span>
              </div>

              {loadingSimilar ? (
                <div className="flex gap-3 overflow-x-auto pb-2 no-scrollbar">
                  {[1, 2, 3, 4].map(i => (
                    <div key={i} className="w-28 sm:w-32 h-44 shrink-0 bg-[var(--bg-color)] rounded-2xl animate-pulse border border-[var(--border-color)]" />
                  ))}
                </div>
              ) : similar.length > 0 ? (
                <div className="flex gap-3.5 overflow-x-auto pb-2 no-scrollbar">
                  {similar.map(s => (
                    <div 
                      key={s.id}
                      onClick={() => onSelectManga(s)}
                      className="w-28 sm:w-32 shrink-0 group relative aspect-[2/3] rounded-2xl overflow-hidden cursor-pointer border border-[var(--border-color)] hover:border-[var(--accent-vermillion)] transition-all duration-200 shadow-md bg-black"
                    >
                      <img 
                        src={s.cover_image_url} 
                        alt={s.title}
                        referrerPolicy="no-referrer"
                        className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-110"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-black via-black/30 to-transparent opacity-90 p-2.5 flex flex-col justify-end">
                        <span className="text-[11px] font-serif-jp font-bold text-white line-clamp-2 leading-tight">
                          {s.title}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-[var(--text-muted)] font-light">No similar titles found.</p>
              )}
            </div>

          </div>

        </div>

      </div>

    </div>
  );
}
