import { useState } from 'react';

const GENRE_OPTIONS = [
  "Action", "Adventure", "Comedy", "Drama", "Fantasy", "Horror", 
  "Mystery", "Psychological", "Romance", "Sci-Fi", "Slice of Life", 
  "Sports", "Supernatural", "Thriller", "Isekai", "Mecha", "Tragedy"
];

export default function FilterDrawer({ filters, setFilters, isOpen, onClose, onReset }) {
  if (!isOpen) return null;

  const toggleGenre = (g, type) => {
    setFilters(prev => {
      const currentIncluded = prev.genres || [];
      const currentExcluded = prev.exclude_genres || [];

      if (type === 'include') {
        const nextIncluded = currentIncluded.includes(g) 
          ? currentIncluded.filter(item => item !== g) 
          : [...currentIncluded, g];
        const nextExcluded = currentExcluded.filter(item => item !== g);
        return { ...prev, genres: nextIncluded, exclude_genres: nextExcluded };
      } else {
        const nextExcluded = currentExcluded.includes(g) 
          ? currentExcluded.filter(item => item !== g) 
          : [...currentExcluded, g];
        const nextIncluded = currentIncluded.filter(item => item !== g);
        return { ...prev, exclude_genres: nextExcluded, genres: nextIncluded };
      }
    });
  };

  const toggleStatus = (st) => {
    setFilters(prev => {
      const current = prev.status || [];
      const next = current.includes(st) ? current.filter(s => s !== st) : [...current, st];
      return { ...prev, status: next };
    });
  };

  return (
    <div className="bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] rounded-3xl p-6 md:p-8 space-y-6 shadow-xl animate-in slide-in-from-top duration-200">
      <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-4">
        <div className="flex items-center gap-2">
          <span className="text-[var(--accent-vermillion)] font-serif-jp text-sm">❖</span>
          <h3 className="text-base font-serif-jp font-bold tracking-wide">Advanced Search Filters</h3>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={onReset}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] font-mono px-3 py-1 rounded-full hover:bg-[var(--bg-color)] transition-colors"
          >
            Reset Filters
          </button>
          <button 
            onClick={onClose}
            className="p-1 text-[var(--text-muted)] hover:text-[var(--text-color)] rounded-full hover:bg-[var(--bg-color)]"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        
        {/* Status & Origin */}
        <div className="space-y-4">
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">Publishing Status</label>
            <div className="flex flex-wrap gap-2">
              {['FINISHED', 'RELEASING', 'CANCELLED', 'HIATUS'].map(st => (
                <button
                  key={st}
                  type="button"
                  onClick={() => toggleStatus(st)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-mono border transition-all ${
                    (filters.status || []).includes(st)
                      ? 'bg-[var(--accent-vermillion)] border-[var(--accent-vermillion)] text-white font-bold'
                      : 'bg-[var(--bg-color)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-2">Origin Format</label>
            <div className="flex flex-wrap gap-2">
              {[
                { id: null, label: 'All Formats' },
                { id: 'Manga', label: 'Manga (JP)' },
                { id: 'Manhwa', label: 'Manhwa (KR)' },
                { id: 'Manhua', label: 'Manhua (CN)' }
              ].map(fmt => {
                const currentFmts = Array.isArray(filters.format_type) 
                  ? filters.format_type 
                  : (filters.format_type ? [filters.format_type] : []);
                
                const isSelected = fmt.id === null 
                  ? currentFmts.length === 0 
                  : currentFmts.includes(fmt.id);

                const handleFormatClick = () => {
                  if (fmt.id === null) {
                    setFilters(prev => ({ ...prev, format_type: null }));
                  } else {
                    let next;
                    if (currentFmts.includes(fmt.id)) {
                      next = currentFmts.filter(f => f !== fmt.id);
                    } else {
                      next = [...currentFmts, fmt.id];
                    }
                    setFilters(prev => ({ ...prev, format_type: next.length > 0 ? next : null }));
                  }
                };

                return (
                  <button
                    key={fmt.label}
                    type="button"
                    onClick={handleFormatClick}
                    className={`px-3 py-1.5 rounded-xl text-xs font-mono border transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-[var(--accent-vermillion)] border-[var(--accent-vermillion)] text-white font-bold shadow-sm'
                        : 'bg-[var(--bg-color)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
                    }`}
                  >
                    {fmt.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>




        {/* Range Controls */}
        <div className="space-y-4">
          <div>
            <div className="flex justify-between text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider mb-1">
              <span>Minimum Score</span>
              <span className="text-[var(--accent-vermillion)] font-mono">{filters.min_score || 0}%</span>
            </div>
            <input 
              type="range" 
              min="0" 
              max="95" 
              value={filters.min_score || 0}
              onChange={(e) => setFilters(prev => ({ ...prev, min_score: Number(e.target.value) }))}
              className="w-full accent-[var(--accent-vermillion)] cursor-pointer"
            />
          </div>

          <div>
            <div className="flex justify-between text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider mb-1">
              <span>Minimum Match Similarity</span>
              <span className="text-[var(--accent-vermillion)] font-mono">{Math.round((filters.min_match_pct || 0) * 100)}%</span>
            </div>
            <input 
              type="range" 
              min="0" 
              max="0.80" 
              step="0.05"
              value={filters.min_match_pct || 0}
              onChange={(e) => setFilters(prev => ({ ...prev, min_match_pct: Number(e.target.value) }))}
              className="w-full accent-[var(--accent-vermillion)] cursor-pointer"
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[11px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1">Min Year</label>
              <input 
                type="number"
                placeholder="2000"
                value={filters.min_year || ''}
                onChange={(e) => setFilters(prev => ({ ...prev, min_year: e.target.value ? Number(e.target.value) : null }))}
                className="w-full bg-[var(--bg-color)] border border-[var(--border-color)] rounded-xl px-3 py-1.5 text-xs text-[var(--text-color)] focus:outline-none focus:border-[var(--accent-vermillion)]"
              />
            </div>
            <div>
              <label className="text-[11px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1">Max Year</label>
              <input 
                type="number"
                placeholder="2026"
                value={filters.max_year || ''}
                onChange={(e) => setFilters(prev => ({ ...prev, max_year: e.target.value ? Number(e.target.value) : null }))}
                className="w-full bg-[var(--bg-color)] border border-[var(--border-color)] rounded-xl px-3 py-1.5 text-xs text-[var(--text-color)] focus:outline-none focus:border-[var(--accent-vermillion)]"
              />
            </div>
          </div>
        </div>

        {/* NSFW & Chapters */}
        <div className="space-y-4">
          <div>
            <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1">Minimum Chapters</label>
            <input 
              type="number"
              placeholder="e.g. 20"
              value={filters.min_chapters || ''}
              onChange={(e) => setFilters(prev => ({ ...prev, min_chapters: e.target.value ? Number(e.target.value) : null }))}
              className="w-full bg-[var(--bg-color)] border border-[var(--border-color)] rounded-xl px-3 py-2 text-xs text-[var(--text-color)] focus:outline-none focus:border-[var(--accent-vermillion)]"
            />
          </div>

          <div className="flex items-center justify-between p-3 bg-[var(--bg-color)] border border-[var(--border-color)] rounded-2xl">
            <div>
              <span className="text-xs font-sans-jp font-bold text-[var(--text-color)] block">NSFW / Adult Titles</span>
              <span className="text-[10px] text-[var(--text-muted)]">Allow 18+ explicit titles</span>
            </div>
            <button
              type="button"
              onClick={() => setFilters(prev => ({ ...prev, nsfw: !prev.nsfw }))}
              className={`w-10 h-5 rounded-full transition-colors p-0.5 cursor-pointer flex items-center ${
                filters.nsfw ? 'bg-[var(--accent-vermillion)] justify-end' : 'bg-[var(--border-color)] justify-start'
              }`}
            >
              <div className="w-4 h-4 rounded-full bg-white shadow-sm" />
            </button>
          </div>
        </div>
      </div>

      {/* Genres Selection */}
      <div className="space-y-2 border-t border-[var(--border-color)] pt-4">
        <div className="flex items-center justify-between">
          <label className="text-xs font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
            Genres (Click to Include / Exclude)
          </label>
        </div>
        <div className="flex flex-wrap gap-2 pt-1">
          {GENRE_OPTIONS.map(g => {
            const isInc = (filters.genres || []).includes(g);
            const isExc = (filters.exclude_genres || []).includes(g);

            return (
              <button
                key={g}
                type="button"
                onClick={() => {
                  if (!isInc && !isExc) toggleGenre(g, 'include');
                  else if (isInc) toggleGenre(g, 'exclude');
                  else toggleGenre(g, 'exclude');
                }}
                className={`px-3 py-1 rounded-full text-xs font-serif-jp border transition-all cursor-pointer ${
                  isInc
                    ? 'bg-[var(--accent-vermillion)] border-[var(--accent-vermillion)] text-white font-bold'
                    : isExc
                    ? 'bg-black/30 border-red-500 text-red-400 line-through'
                    : 'bg-[var(--bg-color)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
                }`}
              >
                #{g}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
