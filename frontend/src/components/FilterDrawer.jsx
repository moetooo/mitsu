import { useState } from 'react';

const GENRE_OPTIONS = [
  "Action", "Adventure", "Comedy", "Drama", "Fantasy", "Horror", 
  "Mystery", "Psychological", "Romance", "Sci-Fi", "Slice of Life", 
  "Sports", "Supernatural", "Thriller", "Isekai", "Mecha", "Tragedy"
];

function DualRangeSliderPanel({ title, minVal, maxVal, absoluteMin, absoluteMax, step = 1, ticks, onChangeMin, onChangeMax, minLabel = "Min", maxLabel = "Max" }) {
  const minPercent = Math.max(0, Math.min(100, ((minVal - absoluteMin) / (absoluteMax - absoluteMin)) * 100));
  const maxPercent = Math.max(0, Math.min(100, ((maxVal - absoluteMin) / (absoluteMax - absoluteMin)) * 100));

  return (
    <div className="bg-[var(--bg-color)]/60 border border-[var(--border-color)] rounded-xl p-2.5 space-y-2 shadow-xs">
      {/* Compact Header */}
      <div className="flex items-center justify-between text-[10px] font-mono font-bold tracking-wider text-[var(--text-color)] uppercase">
        <span>{title}</span>
        <span className="text-[var(--accent-vermillion)] font-mono text-[9px] font-bold">
          {minVal <= absoluteMin && maxVal >= absoluteMax 
            ? 'Any' 
            : `${minVal} - ${maxVal >= absoluteMax ? absoluteMax + '+' : maxVal}`}
        </span>
      </div>

      {/* Dual Slider Track */}
      <div className="space-y-1">
        <div className="relative w-full h-1.5 bg-[var(--surface-color)] border border-[var(--border-color)] rounded-full">
          {/* Active Dynamic Accent Track Fill */}
          <div 
            className="absolute top-0 bottom-0 bg-[var(--accent-vermillion)] rounded-full"
            style={{ left: `${minPercent}%`, right: `${100 - maxPercent}%` }}
          />

          {/* Dual Range Inputs */}
          <input
            type="range"
            min={absoluteMin}
            max={absoluteMax}
            step={step}
            value={minVal}
            onChange={(e) => {
              const val = Math.min(Number(e.target.value), maxVal - step);
              onChangeMin(val);
            }}
            className="absolute top-1/2 -translate-y-1/2 w-full h-1.5 opacity-0 cursor-pointer z-30"
          />
          <input
            type="range"
            min={absoluteMin}
            max={absoluteMax}
            step={step}
            value={maxVal}
            onChange={(e) => {
              const val = Math.max(Number(e.target.value), minVal + step);
              onChangeMax(val);
            }}
            className="absolute top-1/2 -translate-y-1/2 w-full h-1.5 opacity-0 cursor-pointer z-30"
          />

          {/* Visual Handles */}
          <div 
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-[var(--bg-color)] border-2 border-[var(--accent-vermillion)] shadow-xs pointer-events-none z-20"
            style={{ left: `${minPercent}%` }}
          />
          <div 
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-[var(--bg-color)] border-2 border-[var(--accent-vermillion)] shadow-xs pointer-events-none z-20"
            style={{ left: `${maxPercent}%` }}
          />
        </div>

        {/* Tick Markers */}
        <div className="relative w-full flex justify-between px-0.5 pt-0.5">
          {ticks.map((t, idx) => (
            <div key={idx} className="flex flex-col items-center">
              <div className="w-0.5 h-1 bg-[var(--border-color)] mb-0.5" />
              <span className="text-[8px] font-mono text-[var(--text-muted)]">{t.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

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
    <div className="bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] rounded-2xl p-4 md:p-5 space-y-3.5 shadow-xl animate-in slide-in-from-top duration-200">
      {/* Drawer Header */}
      <div className="flex items-center justify-between border-b border-[var(--border-color)] pb-2.5">
        <div className="flex items-center gap-2">
          <span className="text-[var(--accent-vermillion)] font-serif-jp text-xs">❖</span>
          <h3 className="text-sm font-serif-jp font-bold tracking-wide">Advanced Search Filters</h3>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={onReset}
            className="text-[11px] text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] font-mono px-2.5 py-0.5 rounded-full hover:bg-[var(--bg-color)] transition-colors"
          >
            Reset Filters
          </button>
          <button 
            onClick={onClose}
            className="p-1 text-[var(--text-muted)] hover:text-[var(--text-color)] rounded-full hover:bg-[var(--bg-color)]"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>

      {/* Main Filter Options 3-Column Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5 items-start">
        
        {/* Col 1: Status & Origin Format */}
        <div className="space-y-3">
          <div>
            <label className="text-[10px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1.5">Publishing Status</label>
            <div className="flex flex-wrap gap-1.5">
              {['FINISHED', 'RELEASING', 'CANCELLED', 'HIATUS'].map(st => (
                <button
                  key={st}
                  type="button"
                  onClick={() => toggleStatus(st)}
                  className={`px-2.5 py-1 rounded-lg text-[11px] font-mono border transition-all cursor-pointer ${
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
            <label className="text-[10px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider block mb-1.5">Origin Format</label>
            <div className="flex flex-wrap gap-1.5">
              {[
                { id: null, label: 'All' },
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
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-mono border transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-[var(--accent-vermillion)] border-[var(--accent-vermillion)] text-white font-bold shadow-xs'
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

        {/* Col 2: Chapter Ranges */}
        <DualRangeSliderPanel
          title="CHAPTER RANGES"
          minVal={filters.min_chapters || 1}
          maxVal={filters.max_chapters || 500}
          absoluteMin={1}
          absoluteMax={500}
          step={5}
          ticks={[
            { val: 1, label: '1' },
            { val: 50, label: '50' },
            { val: 100, label: '100' },
            { val: 250, label: '250' },
            { val: 500, label: '500+' }
          ]}
          onChangeMin={(val) => setFilters(prev => ({ ...prev, min_chapters: val <= 1 ? null : val }))}
          onChangeMax={(val) => setFilters(prev => ({ ...prev, max_chapters: val >= 500 ? null : val }))}
        />

        {/* Col 3: Publication Year Ranges & NSFW */}
        <div className="space-y-2">
          <DualRangeSliderPanel
            title="PUBLICATION YEAR"
            minVal={filters.min_year || 1970}
            maxVal={filters.max_year || 2026}
            absoluteMin={1970}
            absoluteMax={2026}
            step={1}
            ticks={[
              { val: 1970, label: '1970' },
              { val: 1985, label: '1985' },
              { val: 2000, label: '2000' },
              { val: 2015, label: '2015' },
              { val: 2026, label: '2026' }
            ]}
            onChangeMin={(val) => setFilters(prev => ({ ...prev, min_year: val <= 1970 ? null : val }))}
            onChangeMax={(val) => setFilters(prev => ({ ...prev, max_year: val >= 2026 ? null : val }))}
          />

          <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-color)]/60 border border-[var(--border-color)] rounded-xl">
            <span className="text-[11px] font-sans-jp font-bold text-[var(--text-color)]">NSFW / 18+ Titles</span>
            <button
              type="button"
              onClick={() => setFilters(prev => ({ ...prev, nsfw: !prev.nsfw }))}
              className={`w-8 h-4 rounded-full transition-colors p-0.5 cursor-pointer flex items-center ${
                filters.nsfw ? 'bg-[var(--accent-vermillion)] justify-end' : 'bg-[var(--border-color)] justify-start'
              }`}
            >
              <div className="w-3 h-3 rounded-full bg-white shadow-xs" />
            </button>
          </div>
        </div>

      </div>

      {/* Genres Selection */}
      <div className="space-y-1.5 border-t border-[var(--border-color)] pt-2.5">
        <div className="flex items-center justify-between">
          <label className="text-[10px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
            Genres (Include / Exclude)
          </label>
        </div>
        <div className="flex flex-wrap gap-1.5 pt-0.5">
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
                className={`px-2 py-0.5 rounded-full text-[11px] font-serif-jp border transition-all cursor-pointer ${
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
