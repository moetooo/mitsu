export default function MangaCard({ 
  manga, 
  onClick, 
  isBookmarked, 
  onToggleBookmark,
  gridSize = 'standard',
  hoverAccent = 'vermillion'
}) {
  const matchPct = manga.similarity_score !== undefined ? Math.round(manga.similarity_score * 100) : null;

  const hoverBorderMap = {
    vermillion: 'hover:border-[var(--accent-vermillion)]',
    gold: 'hover:border-[#e6a15c]',
    emerald: 'hover:border-[#4e9f78]',
    mono: 'hover:border-[var(--text-color)]',
    indigo: 'hover:border-[var(--accent-indigo)]'
  };

  return (
    <div
      onClick={() => onClick(manga)}
      className={`manga-card-item group relative bg-[var(--surface-color)] border border-[var(--border-color)] rounded-2xl p-3 cursor-pointer shadow-sm hover:shadow-md ${hoverBorderMap[hoverAccent] || hoverBorderMap.vermillion} transition-all duration-150 ease-out hover:scale-[1.02] flex flex-col justify-between`}
    >

      {/* Framed Print Cover Container */}
      <div className="relative aspect-[2/3] w-full rounded-xl overflow-hidden bg-black/20 border border-[var(--border-color)]">
        {manga.cover_image_url ? (
          <img
            src={manga.cover_image_url}
            alt={manga.title}
            referrerPolicy="no-referrer"
            className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-105"
            loading="lazy"
            decoding="async"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] font-serif-jp text-xs">
            No Cover
          </div>
        )}
        
        {/* Subtle Dark Bottom Gradient */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-80 group-hover:opacity-90 transition-opacity" />

        {/* Finalized Circular Ink Crest (Symmetrical 28px x 28px Circle) */}
        {matchPct !== null && (
          <div className="absolute top-2.5 right-2.5 stamp-crest z-10">
            <span>{matchPct}%</span>
          </div>
        )}

        {/* Bookmark Button (Symmetrical 28px x 28px Circle) */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleBookmark(manga);
          }}
          className={`absolute top-2.5 left-2.5 w-7 h-7 rounded-full flex items-center justify-center border transition-all z-20 cursor-pointer ${
            isBookmarked 
              ? 'bg-[var(--accent-vermillion)] text-white border-[var(--accent-vermillion)] scale-105 shadow-sm' 
              : 'bg-black/60 text-white/80 border-white/20 hover:text-white hover:bg-black/90'
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
        <div>
          <h3 
            title={manga.title}
            className="font-serif-jp font-bold text-xs md:text-sm text-[var(--text-color)] line-clamp-2 leading-snug group-hover:text-[var(--accent-vermillion)] transition-colors h-[2.5rem] overflow-hidden flex items-start"
          >
            {manga.title}
          </h3>
        </div>



        <div className="flex items-center gap-2 text-[11px] text-[var(--text-muted)] font-mono">
          {manga.start_year && <span>{manga.start_year}</span>}
          {manga.status && <span>• {manga.status}</span>}
          {manga.average_score && (
            <span className="ml-auto text-[var(--accent-vermillion)] font-bold">
              ★ {(manga.average_score / 10).toFixed(1)}
            </span>
          )}
        </div>

        {/* Why this match reasoning */}
        {manga.llm_reasoning && (
          <div className="pt-1.5 border-t border-[var(--border-color)]">
            <span className="text-[9px] font-bold text-[var(--accent-indigo)] uppercase tracking-wider block font-mono">
              AI Reasoning
            </span>
            <p className="text-[var(--text-muted)] text-[11px] leading-relaxed line-clamp-2 font-light">
              {manga.llm_reasoning}
            </p>
          </div>
        )}
      </div>

    </div>
  );
}
