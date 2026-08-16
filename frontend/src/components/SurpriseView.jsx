import { useState } from 'react';

export default function SurpriseView({ 
  manga, 
  loading, 
  onRefresh, 
  bookmarks = [], 
  onToggleBookmark, 
  onSelectManga 
}) {
  const isBookmarked = manga ? (bookmarks || []).some(b => b.id === manga.id) : false;

  return (
    <div className="pt-4 pb-20 max-w-md mx-auto space-y-6 flex flex-col items-center justify-center min-h-[65vh] animate-in fade-in duration-300">
      
      {/* Centered Unique Spin Button */}
      <div className="flex justify-center w-full">
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="group relative inline-flex items-center justify-center gap-3 px-8 py-3.5 rounded-full bg-[var(--surface-color)]/90 backdrop-blur-md border border-[var(--border-color)] text-[var(--text-color)] hover:border-[var(--accent-vermillion)] shadow-sm hover:shadow-[0_0_25px_rgba(195,61,46,0.25)] transition-all duration-300 cursor-pointer disabled:opacity-60 active:scale-95"
        >
          {/* Animated Glowing Ring Backdrop */}
          <span className="absolute -inset-0.5 rounded-full bg-gradient-to-r from-[var(--accent-vermillion)] to-[var(--accent-indigo)] opacity-0 group-hover:opacity-20 blur-md transition-opacity duration-500" />
          
          {/* Icon Orb */}
          <div className="relative w-7 h-7 rounded-full bg-[var(--bg-color)] border border-[var(--border-color)] group-hover:border-[var(--accent-vermillion)] flex items-center justify-center text-[var(--accent-vermillion)] transition-all">
            <svg 
              className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-700'}`} 
              fill="none" 
              viewBox="0 0 24 24" 
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </div>

          <span className="relative font-mono text-xs font-bold tracking-wider uppercase text-[var(--text-color)]">
            {loading ? 'Drawing...' : 'Spin Surprise'}
          </span>

          <span className="relative text-[10px] font-mono text-[var(--accent-vermillion)] font-bold opacity-60 group-hover:opacity-100 transition-opacity">
            ✦
          </span>
        </button>
      </div>

      {/* Main Minimal Showcase Card */}
      {loading && !manga ? (
        <div className="w-full py-16 flex flex-col items-center justify-center space-y-3 bg-[var(--surface-color)]/40 border border-[var(--border-color)] rounded-2xl">
          <div className="w-8 h-8 border-2 border-[var(--accent-vermillion)] border-t-transparent rounded-full animate-spin" />
        </div>
      ) : manga ? (
        <div className="w-full bg-[var(--surface-color)]/80 backdrop-blur-md border border-[var(--border-color)] rounded-2xl p-6 shadow-md text-center space-y-5 transition-all duration-300">
          
          {/* Minimal Cover */}
          <div className="w-44 mx-auto aspect-2/3 rounded-xl overflow-hidden border border-[var(--border-color)] bg-[var(--bg-color)] shadow-sm">
            {manga.cover_image_url ? (
              <img 
                src={manga.cover_image_url} 
                alt={manga.title} 
                className="w-full h-full object-cover hover:scale-103 transition-transform duration-300"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-[var(--text-muted)] font-mono text-[10px]">
                No Image
              </div>
            )}
          </div>

          {/* Title Name Only */}
          <h3 className="font-serif-jp text-xl md:text-2xl font-bold text-[var(--text-color)] leading-snug px-2">
            {manga.title}
          </h3>

          {/* Minimal Action Controls (Save & Full Details) */}
          <div className="flex items-center justify-center gap-3 pt-2">
            <button
              type="button"
              onClick={() => onToggleBookmark(manga)}
              className={`px-4 py-2 rounded-xl text-xs font-mono transition-all cursor-pointer flex items-center gap-1.5 ${
                isBookmarked
                  ? 'bg-[var(--accent-vermillion)]/15 text-[var(--accent-vermillion)] font-bold border border-[var(--accent-vermillion)]'
                  : 'bg-[var(--bg-color)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
              }`}
            >
              <svg className="w-3.5 h-3.5" fill={isBookmarked ? "currentColor" : "none"} viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" />
              </svg>
              <span>{isBookmarked ? 'Saved' : 'Save'}</span>
            </button>

            {onSelectManga && (
              <button
                type="button"
                onClick={() => onSelectManga(manga)}
                className="px-4 py-2 rounded-xl text-xs font-mono border border-[var(--border-color)] bg-[var(--bg-color)] text-[var(--text-color)] hover:border-[var(--accent-vermillion)] transition-colors cursor-pointer"
              >
                Full Details
              </button>
            )}
          </div>

        </div>
      ) : null}

    </div>
  );
}
