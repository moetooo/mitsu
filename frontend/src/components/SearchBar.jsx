import { useState } from 'react';

export default function SearchBar({ 
  query, 
  setQuery, 
  onSearch, 
  loading, 
  isFilterOpen, 
  setIsFilterOpen, 
  hasActiveFilters,
  focusStyle = 'glow'
}) {
  const [isFocused, setIsFocused] = useState(false);

  const focusClassMap = {
    glow: 'focus-within:ring-2 focus-within:ring-[var(--accent-vermillion)]/60 focus-within:border-[var(--accent-vermillion)] focus-within:shadow-[0_0_18px_rgba(195,61,46,0.25)]',
    vermillion: 'focus-within:border-[var(--accent-vermillion)]',
    brush: 'focus-within:border-[var(--accent-indigo)]',
    subtle: 'focus-within:border-[var(--accent-indigo)] focus-within:bg-[var(--surface-hover)]',
    none: 'focus-within:border-[var(--border-color)]'
  };

  return (
    <div className="max-w-3xl mx-auto relative group">
      
      {/* Search Input Container */}
      <form 
        onSubmit={(e) => { e.preventDefault(); onSearch(e); }} 
        className={`relative flex items-center bg-[var(--surface-color)] border border-[var(--border-color)] rounded-2xl shadow-sm transition-all duration-200 ${focusClassMap[focusStyle] || focusClassMap.glow}`}
      >
        
        {/* Filter Toggle Button */}
        <button
          type="button"
          onClick={() => setIsFilterOpen(!isFilterOpen)}
          className={`pl-4 pr-3 py-3.5 flex items-center gap-2 text-xs font-bold transition-colors cursor-pointer ${
            hasActiveFilters ? 'text-[var(--accent-vermillion)]' : 'text-[var(--text-muted)] hover:text-[var(--text-color)]'
          }`}
          title="Filter Search Options"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
          </svg>
          <span className="hidden sm:inline font-sans-jp">Filters</span>
        </button>

        <div className="h-5 w-[1px] bg-[var(--border-color)]" />

        {/* Input Field with Mincho Font Placeholder */}
        <input
          type="text"
          value={query}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Describe plot, mood, or themes... (e.g. dark fantasy action)"
          className="w-full bg-transparent px-4 py-4 text-sm md:text-base font-serif-jp focus:outline-none placeholder:text-[var(--text-muted)] text-[var(--text-color)]"
        />

        {/* Vermillion Circular Search Button */}
        <button 
          type="submit"
          disabled={loading}
          aria-label="Search"
          title="Search"
          className="mr-2.5 w-10 h-10 rounded-full bg-[var(--accent-vermillion)] hover:opacity-90 text-white flex items-center justify-center transition-all active:scale-95 disabled:opacity-50 cursor-pointer shadow-sm shrink-0"
        >
          {loading ? (
            <svg className="w-4 h-4 animate-spin text-white" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          ) : (
            <svg className="w-4.5 h-4.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          )}
        </button>

        {/* Optional Brush Line Focus Style */}
        {focusStyle === 'brush' && (
          <div className={`absolute bottom-0 left-0 right-0 h-[2px] overflow-hidden transition-all duration-300 pointer-events-none ${isFocused ? 'opacity-100' : 'opacity-0'}`}>
            <svg className="w-full h-full text-[var(--accent-vermillion)]" preserveAspectRatio="none" viewBox="0 0 100 2">
              <path d="M0 1 Q 25 0, 50 1 T 100 1" stroke="currentColor" strokeWidth="2" fill="none" />
            </svg>
          </div>
        )}
      </form>
    </div>
  );
}


