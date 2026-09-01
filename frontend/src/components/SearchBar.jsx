import { useState, useEffect, useRef } from 'react';

const RECENT_QUERIES_KEY = 'mitsu_recent_queries';
const MAX_RECENT = 5;

function getRecentQueries() {
  try {
    const raw = localStorage.getItem(RECENT_QUERIES_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRecentQuery(query) {
  if (!query || !query.trim()) return;
  const trimmed = query.trim();
  const existing = getRecentQueries().filter(q => q.toLowerCase() !== trimmed.toLowerCase());
  const updated = [trimmed, ...existing].slice(0, MAX_RECENT);
  localStorage.setItem(RECENT_QUERIES_KEY, JSON.stringify(updated));
}

function removeRecentQuery(queryToRemove) {
  const updated = getRecentQueries().filter(q => q !== queryToRemove);
  localStorage.setItem(RECENT_QUERIES_KEY, JSON.stringify(updated));
}

export default function SearchBar({ 
  query, 
  setQuery, 
  onSearch, 
  loading, 
  isFilterOpen, 
  setIsFilterOpen, 
  hasActiveFilters,
  activeFilterCount = 0,
  focusStyle = 'glow',
  onSurpriseMe
}) {
  const [isFocused, setIsFocused] = useState(false);
  const [showRecent, setShowRecent] = useState(false);
  const [recentQueries, setRecentQueries] = useState(getRecentQueries);
  const dropdownRef = useRef(null);
  const inputRef = useRef(null);

  // Refresh recent queries from localStorage when dropdown opens
  useEffect(() => {
    if (showRecent) {
      setRecentQueries(getRecentQueries());
    }
  }, [showRecent]);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setShowRecent(false);
      }
    }
    if (showRecent) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [showRecent]);

  const handleFocus = () => {
    setIsFocused(true);
    // Only show dropdown if input is empty or has little text, and there are recent queries
    if (getRecentQueries().length > 0) {
      setShowRecent(true);
    }
  };

  const handleBlur = () => {
    setIsFocused(false);
    // Delay hiding to allow click on pills
    setTimeout(() => setShowRecent(false), 200);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (query && query.trim()) {
      saveRecentQuery(query);
      setRecentQueries(getRecentQueries());
    }
    setShowRecent(false);
    onSearch(e);
  };

  const handleRecentClick = (recentQuery) => {
    setQuery(recentQuery);
    setShowRecent(false);
    // Trigger search with the selected recent query
    saveRecentQuery(recentQuery);
    setRecentQueries(getRecentQueries());
    onSearch(null, recentQuery);
  };

  const handleRemoveRecent = (e, queryToRemove) => {
    e.stopPropagation();
    removeRecentQuery(queryToRemove);
    setRecentQueries(getRecentQueries());
  };

  const handleClearAllRecent = (e) => {
    e.stopPropagation();
    localStorage.removeItem(RECENT_QUERIES_KEY);
    setRecentQueries([]);
    setShowRecent(false);
  };

  const focusClassMap = {
    glow: 'focus-within:ring-2 focus-within:ring-[var(--accent-vermillion)]/60 focus-within:border-[var(--accent-vermillion)] focus-within:shadow-[0_0_18px_rgba(195,61,46,0.25)]',
    vermillion: 'focus-within:border-[var(--accent-vermillion)]',
    brush: 'focus-within:border-[var(--accent-indigo)]',
    subtle: 'focus-within:border-[var(--accent-indigo)] focus-within:bg-[var(--surface-hover)]',
    none: 'focus-within:border-[var(--border-color)]'
  };

  // Filter recent queries based on current input (show all when empty)
  const filteredRecent = query && query.trim()
    ? recentQueries.filter(q => q.toLowerCase().includes(query.trim().toLowerCase()) && q.toLowerCase() !== query.trim().toLowerCase())
    : recentQueries;

  return (
    <div className="max-w-3xl mx-auto relative group" ref={dropdownRef}>
      
      {/* Search Input Container */}
      <form 
        onSubmit={handleSubmit} 
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
          {activeFilterCount > 0 && (
            <span className="ml-1 px-1.5 py-0.2 text-[10px] font-mono font-bold rounded-full bg-[var(--accent-vermillion)] text-white shadow-xs">
              {activeFilterCount}
            </span>
          )}
        </button>

        <div className="h-5 w-[1px] bg-[var(--border-color)]" />

        {/* Input Field with Mincho Font Placeholder */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onFocus={handleFocus}
          onBlur={handleBlur}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Describe plot, mood, or themes... (e.g. dark fantasy action)"
          className="w-full bg-transparent px-4 py-4 text-sm md:text-base font-serif-jp focus:outline-none placeholder:text-[var(--text-muted)] text-[var(--text-color)]"
          autoComplete="off"
        />

        {/* Feature 09: Instant Search Clear ("X") Button */}
        {query && query.length > 0 && (
          <button
            type="button"
            onClick={() => {
              setQuery('');
            }}
            className="p-1.5 mr-1 text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] transition-colors cursor-pointer rounded-full hover:bg-[var(--bg-color)] shrink-0"
            title="Clear Search"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}

        {/* Surprise Me Omikuji Button */}
        {onSurpriseMe && (
          <button
            type="button"
            onClick={onSurpriseMe}
            className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 mr-2 rounded-xl text-xs font-mono font-bold bg-[var(--bg-color)] border border-[var(--border-color)] text-[var(--text-color)] hover:border-[var(--accent-vermillion)] hover:text-[var(--accent-vermillion)] transition-all cursor-pointer shadow-xs shrink-0"
            title="Omikuji Fate Draw (Surprise Me)"
          >
            <span className="font-serif-jp text-xs text-[var(--accent-vermillion)]">籤</span>
            <span>Surprise Me</span>
          </button>
        )}

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

      {/* Feature 10: Recent Queries Dropdown */}
      {showRecent && filteredRecent.length > 0 && (
        <div
          className="absolute left-0 right-0 top-full mt-2 z-50 bg-[var(--surface-color)] border border-[var(--border-color)] rounded-xl shadow-lg overflow-hidden"
          style={{ animation: 'recentDropdownIn 0.15s ease-out' }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border-color)]">
            <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
              Recent Searches
            </span>
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={handleClearAllRecent}
              className="text-[10px] font-mono text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] transition-colors cursor-pointer"
            >
              Clear All
            </button>
          </div>

          {/* Recent Query Pills */}
          <div className="px-3 py-2.5 flex flex-wrap gap-2">
            {filteredRecent.map((rq, idx) => (
              <button
                key={`${rq}-${idx}`}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => handleRecentClick(rq)}
                className="group/pill inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-mono bg-[var(--bg-color)] border border-[var(--border-color)] text-[var(--text-color)] hover:border-[var(--accent-vermillion)] hover:text-[var(--accent-vermillion)] transition-all cursor-pointer"
              >
                <svg className="w-3 h-3 text-[var(--text-muted)] group-hover/pill:text-[var(--accent-vermillion)] shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="truncate max-w-[180px]">{rq}</span>
                <span
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={(e) => handleRemoveRecent(e, rq)}
                  className="ml-0.5 p-0.5 rounded-full text-[var(--text-muted)] hover:text-[var(--accent-vermillion)] hover:bg-[var(--surface-hover)] transition-colors"
                  title="Remove"
                >
                  <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
