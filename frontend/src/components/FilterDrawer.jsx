import { useState, useMemo } from 'react';

export const FILTER_CATEGORIES = [
  {
    id: 'core',
    name: "Core Genres",
    tagline: "Story Archetypes",
    options: [
      "Action", "Adventure", "Comedy", "Drama", "Fantasy", 
      "Horror", "Mystery", "Psychological", "Sci-Fi", 
      "Slice of Life", "Supernatural", "Thriller", "Tragedy"
    ]
  },
  {
    id: 'demographics',
    name: "Demographics",
    tagline: "Target Demographics",
    options: [
      "Shounen", "Shoujo", "Seinen", "Josei"
    ]
  },
  {
    id: 'romance',
    name: "Romance & Relationships",
    tagline: "Romance • BL • GL",
    options: [
      "Romance", "Boys' Love", "Girls' Love", "Harem", "Reverse Harem", 
      "Love Triangle", "Ecchi"
    ]
  },
  {
    id: 'themes',
    name: "Themes & Settings",
    tagline: "Themes & Settings",
    options: [
      "Isekai", "Mecha", "Sports", "Historical", "Music", 
      "School Life", "Reincarnation", "Martial Arts", "Super Power", 
      "Survival", "Magic", "Crime", "Medical"
    ]
  }
];

const ALL_FILTER_OPTIONS = Array.from(new Set(FILTER_CATEGORIES.flatMap(c => c.options)));

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

  const [activeCategoryTab, setActiveCategoryTab] = useState('all');
  const [tagQuery, setTagQuery] = useState('');

  const displayedCategories = useMemo(() => {
    if (activeCategoryTab === 'all') return FILTER_CATEGORIES;
    return FILTER_CATEGORIES.filter(c => c.id === activeCategoryTab);
  }, [activeCategoryTab]);

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

        {/* Col 3: Publication Year Ranges */}
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
        </div>

      </div>

      {/* Categories & Genres Selection */}
      <div className="space-y-3 border-t border-[var(--border-color)] pt-3.5">
        {/* Header & Sub-Tabs */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-mono font-bold text-[var(--text-muted)] uppercase tracking-wider">
              Manga Categories & Genres
            </label>
          </div>

          {/* Tag search input (no emojis) */}
          <div className="relative w-full sm:w-48">
            <input 
              type="text"
              placeholder="Search genres and tags..."
              value={tagQuery}
              onChange={(e) => setTagQuery(e.target.value)}
              className="w-full bg-[var(--bg-color)] border border-[var(--border-color)] rounded-xl px-2.5 py-1 text-xs font-mono text-[var(--text-color)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-vermillion)] transition-colors"
            />
            {tagQuery && (
              <button 
                type="button"
                onClick={() => setTagQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)] hover:text-white cursor-pointer"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Category Navigation Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pb-1">
          <button
            type="button"
            onClick={() => setActiveCategoryTab('all')}
            className={`px-3 py-1 rounded-full text-[11px] font-mono whitespace-nowrap transition-all cursor-pointer flex items-center gap-1.5 ${
              activeCategoryTab === 'all'
                ? 'bg-[var(--text-color)] text-[var(--bg-color)] font-bold shadow-xs'
                : 'bg-[var(--bg-color)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
            }`}
          >
            <span>All Categories</span>
            <span className="text-[9px] opacity-75">({ALL_FILTER_OPTIONS.length})</span>
          </button>

          {FILTER_CATEGORIES.map(cat => {
            const catInc = cat.options.filter(o => (filters.genres || []).includes(o)).length;
            const catExc = cat.options.filter(o => (filters.exclude_genres || []).includes(o)).length;
            const catActive = catInc + catExc;

            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => setActiveCategoryTab(cat.id)}
                className={`px-3 py-1 rounded-full text-[11px] font-mono whitespace-nowrap transition-all cursor-pointer flex items-center gap-1.5 ${
                  activeCategoryTab === cat.id
                    ? 'bg-[var(--accent-vermillion)] text-white font-bold shadow-xs'
                    : 'bg-[var(--bg-color)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
                }`}
              >
                <span>{cat.name}</span>
                {catActive > 0 && (
                  <span className="w-4 h-4 rounded-full bg-white/20 text-[9px] font-bold flex items-center justify-center">
                    {catActive}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Categorized Pills Content */}
        <div className="space-y-3 pt-1">
          {displayedCategories.map(cat => {
            const filteredOptions = cat.options.filter(opt => {
              if (!tagQuery) return true;
              const q = tagQuery.toLowerCase().trim();
              const lower = opt.toLowerCase();
              if (lower.includes(q)) return true;
              if (lower === "boys' love" && (q === 'yaoi' || q === 'bl')) return true;
              if (lower === "girls' love" && (q === 'yuri' || q === 'gl')) return true;
              return false;
            });
            if (filteredOptions.length === 0) return null;

            return (
              <div key={cat.id} className="bg-[var(--bg-color)]/50 border border-[var(--border-color)]/60 rounded-xl p-3 space-y-2">
                {/* Category Header Bar (Clean typography, no icons/emojis) */}
                <div className="flex items-center justify-between pb-1 border-b border-[var(--border-color)]/40">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-serif-jp font-bold text-[var(--text-color)]">{cat.name}</span>
                    <span className="text-[9px] font-mono text-[var(--text-muted)] px-2 py-0.5 rounded-md bg-[var(--surface-color)] border border-[var(--border-color)]/60">
                      {cat.tagline}
                    </span>
                  </div>
                </div>

                {/* Options Pills Grid */}
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {filteredOptions.map(opt => {
                    const isInc = (filters.genres || []).includes(opt);
                    const isExc = (filters.exclude_genres || []).includes(opt);

                    return (
                      <button
                        key={opt}
                        type="button"
                        onClick={() => {
                          if (!isInc && !isExc) toggleGenre(opt, 'include');
                          else if (isInc) toggleGenre(opt, 'exclude');
                          else {
                            // Reset back to neutral
                            setFilters(prev => ({
                              ...prev,
                              genres: (prev.genres || []).filter(g => g !== opt),
                              exclude_genres: (prev.exclude_genres || []).filter(g => g !== opt)
                            }));
                          }
                        }}
                        title={isInc ? 'Included (click to exclude)' : isExc ? 'Excluded (click to reset)' : 'Click to include'}
                        className={`px-3 py-1 rounded-full text-xs font-serif-jp border transition-all cursor-pointer flex items-center justify-center select-none ${
                          isInc
                            ? 'bg-[var(--accent-vermillion)] border-[var(--accent-vermillion)] text-white font-bold shadow-xs'
                            : isExc
                            ? 'bg-red-950/40 border-red-500/70 text-red-300 line-through font-bold opacity-85'
                            : 'bg-[var(--surface-color)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)] hover:border-[var(--text-muted)]'
                        }`}
                      >
                        <span>#{opt}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>

        {/* Quick Reset for category filters when active */}
        {((filters.genres?.length || 0) > 0 || (filters.exclude_genres?.length || 0) > 0) && (
          <div className="flex justify-end pt-1 px-1">
            <button
              type="button"
              onClick={() => setFilters(prev => ({ ...prev, genres: [], exclude_genres: [] }))}
              className="text-[10px] font-mono text-[var(--accent-vermillion)] hover:underline cursor-pointer font-bold"
            >
              Clear Category Filters ({((filters.genres?.length || 0) + (filters.exclude_genres?.length || 0))})
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
