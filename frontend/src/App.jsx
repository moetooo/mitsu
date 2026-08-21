import { useState, useEffect } from 'react';
import Header from './components/Header';
import SearchBar from './components/SearchBar';
import FilterDrawer from './components/FilterDrawer';
import ComparisonSearch from './components/ComparisonSearch';
import MangaGrid from './components/MangaGrid';
import MangaDetailModal from './components/MangaDetailModal';
import SettingsModal from './components/SettingsModal';
import BookmarksView from './components/BookmarksView';
import HeroBanner from './components/HeroBanner';
import SurpriseView from './components/SurpriseView';

const INITIAL_FILTERS = {
  status: [],
  min_year: null,
  max_year: null,
  min_score: 0,
  min_chapters: null,
  max_chapters: null,
  min_match_pct: 0,
  genres: [],
  exclude_genres: [],
  format_type: null,
  nsfw: false
};

const INITIAL_SETTINGS = {
  theme: 'sumi', // 'sumi' (dark ink) | 'washi' (light paper) | 'amoled'
  fontStyle: 'serif', // 'serif' | 'sans' | 'mono' | 'display'
  stampStyle: 'crest',
  gridSize: 'standard',
  limit: 12,
  focusStyle: 'glow', // 'glow' | 'vermillion' | 'subtle' | 'none'
  hoverAccent: 'vermillion' // 'vermillion' | 'gold' | 'emerald' | 'mono' | 'indigo'
};


export default function App() {
  const [activeTab, setActiveTab] = useState('explore'); // 'explore' | 'trending' | 'surprise' | 'bookmarks'
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [mangas, setMangas] = useState([]);
  const [selectedManga, setSelectedManga] = useState(null);
  const [searched, setSearched] = useState(false);

  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [isFilterOpen, setIsFilterOpen] = useState(false);

  // Surprise Me Discovery States
  const [surpriseManga, setSurpriseManga] = useState(null);
  const [loadingSurprise, setLoadingSurprise] = useState(false);
  const [seenRouletteIds, setSeenRouletteIds] = useState([]);

  const [settings, setSettings] = useState(() => {
    const saved = localStorage.getItem('mitsu_settings') || localStorage.getItem('mangamind_settings');
    return saved ? JSON.parse(saved) : INITIAL_SETTINGS;
  });

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  // LocalStorage Bookmarks state
  const [bookmarks, setBookmarks] = useState(() => {
    const saved = localStorage.getItem('mitsu_bookmarks') || localStorage.getItem('mangamind_bookmarks');
    return saved ? JSON.parse(saved) : [];
  });

  // Trending Section Divided State & Filters
  const [trendingFormat, setTrendingFormat] = useState('all'); // 'all' | 'manga' | 'manhwa' | 'manhua'
  const [trendingGenre, setTrendingGenre] = useState('all'); // 'all' | 'Action' | 'Fantasy' | ...
  const [isTop10, setIsTop10] = useState(false);
  const [trendingPage, setTrendingPage] = useState(1);
  const [trendingMangas, setTrendingMangas] = useState([]);
  const [loadingTrending, setLoadingTrending] = useState(false);
  const [hasMoreTrending, setHasMoreTrending] = useState(true);

  const [sessionId] = useState(() => {
    return typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : 'session_' + Math.random().toString(36).substring(2, 9);
  });

  const handleSurpriseMe = async () => {
    setLoadingSurprise(true);

    try {
      const res = await fetch('http://localhost:8000/roulette', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query || null,
          filters: filters,
          seen_ids: seenRouletteIds,
          session_id: sessionId,
          limit: 40
        })
      });
      if (res.ok) {
        const data = await res.json();
        setSurpriseManga(data);
        setSeenRouletteIds(prev => [...prev, data.id]);
        return data;
      }
    } catch (err) {
      console.error('Failed to draw roulette recommendation:', err);
    } finally {
      setLoadingSurprise(false);
    }
    return null;
  };

  const fetchRouletteBatch = async (count = 5) => {
    try {
      const res = await fetch('http://localhost:8000/roulette/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filters: filters,
          seen_ids: seenRouletteIds,
          session_id: sessionId,
          count: count
        })
      });
      if (res.ok) {
        const items = await res.json();
        if (Array.isArray(items) && items.length > 0) {
          const ids = items.map(i => i.id);
          setSeenRouletteIds(prev => [...prev, ...ids]);
          return items;
        }
      }
    } catch (err) {
      console.error('Failed to fetch roulette batch:', err);
    }
    return [];
  };

  useEffect(() => {
    if (activeTab === 'surprise' && !surpriseManga && !loadingSurprise) {
      handleSurpriseMe();
    }
  }, [activeTab]);

  const fetchTrendingData = (pageNum = 1, append = false) => {
    if (activeTab !== 'trending') return;
    setLoadingTrending(true);

    const limit = 12;
    const formatParam = trendingFormat !== 'all' ? `&format_type=${trendingFormat}` : '';
    const genreParam = trendingGenre !== 'all' ? `&genre=${encodeURIComponent(trendingGenre)}` : '';

    const url = `http://localhost:8000/manga/trending?page=${pageNum}&limit=${limit}${formatParam}${genreParam}`;

    fetch(url)
      .then(res => res.json())
      .then(data => {
        const results = Array.isArray(data) ? data : [];
        if (pageNum === 1 && !append) {
          setTrendingMangas(results);
        } else {
          setTrendingMangas(prev => {
            const existingIds = new Set(prev.map(m => m.id));
            const uniqueNew = results.filter(m => !existingIds.has(m.id));
            return [...prev, ...uniqueNew];
          });
        }
        setHasMoreTrending(results.length >= limit);
      })
      .catch(err => console.error("Trending fetch error:", err))
      .finally(() => setLoadingTrending(false));
  };

  useEffect(() => {
    if (activeTab === 'trending') {
      setTrendingPage(1);
      fetchTrendingData(1, false);
    }
  }, [activeTab, trendingFormat, trendingGenre]);

  const handleLoadMoreTrending = () => {
    const nextPage = trendingPage + 1;
    setTrendingPage(nextPage);
    fetchTrendingData(nextPage, true);
  };

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', settings.theme || 'sumi');
    document.documentElement.setAttribute('data-title-font', settings.fontStyle || 'serif');
    document.documentElement.setAttribute('data-accent', settings.accent || settings.hoverAccent || 'vermillion');
    localStorage.setItem('mitsu_settings', JSON.stringify(settings));
  }, [settings]);


  useEffect(() => {
    localStorage.setItem('mitsu_bookmarks', JSON.stringify(bookmarks));
  }, [bookmarks]);

  const hasActiveFilters =
    (filters.status && filters.status.length > 0) ||
    filters.min_year ||
    filters.max_year ||
    filters.min_score > 0 ||
    filters.min_chapters ||
    filters.min_match_pct > 0 ||
    (filters.genres && filters.genres.length > 0) ||
    (filters.exclude_genres && filters.exclude_genres.length > 0) ||
    filters.format_type ||
    filters.nsfw;

  const activeFilterCount = [
    (filters.status && filters.status.length > 0) ? filters.status.length : 0,
    filters.min_year ? 1 : 0,
    filters.max_year ? 1 : 0,
    filters.min_score > 0 ? 1 : 0,
    filters.min_chapters ? 1 : 0,
    filters.min_match_pct > 0 ? 1 : 0,
    (filters.genres && filters.genres.length > 0) ? filters.genres.length : 0,
    (filters.exclude_genres && filters.exclude_genres.length > 0) ? filters.exclude_genres.length : 0,
    filters.format_type ? 1 : 0,
    filters.nsfw ? 1 : 0
  ].reduce((a, b) => a + b, 0);

  const handleToggleBookmark = (mangaToToggle) => {
    setBookmarks(prev => {
      const exists = prev.some(b => b.id === mangaToToggle.id);
      if (exists) {
        return prev.filter(b => b.id !== mangaToToggle.id);
      } else {
        return [...prev, mangaToToggle];
      }
    });
  };

  const handleSearch = async (e, customQuery = null, pageNum = 1, customFilters = null) => {
    if (e) e.preventDefault();
    const searchQuery = customQuery !== null ? customQuery : query;
    const activeFilters = customFilters !== null ? customFilters : filters;
    if (!searchQuery.trim()) return;

    setLoading(true);
    setSearched(true);
    if (pageNum === 1) setPage(1);

    try {
      const res = await fetch('http://localhost:8000/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: searchQuery,
          filters: activeFilters,
          limit: settings.limit,
          page: pageNum
        })
      });
      const data = await res.json();

      const newResults = data.results || [];
      if (pageNum === 1) {
        setMangas(newResults);
      } else {
        setMangas(prev => {
          const existingIds = new Set(prev.map(m => m.id));
          const uniqueNew = newResults.filter(m => !existingIds.has(m.id));
          return [...prev, ...uniqueNew];
        });
      }

      setHasMore(newResults.length >= settings.limit);
    } catch (err) {
      console.error('Search error:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    handleSearch(null, query, nextPage, filters);
  };

  const handleTagClick = (tag) => {
    const tagQuery = `#${tag}`;
    setQuery(tagQuery);
    setSelectedManga(null);
    setActiveTab('explore');
    handleSearch(null, tagQuery, 1, filters);
  };

  return (
    <div className="min-h-screen bg-[var(--bg-color)] text-[var(--text-color)] washi-paper-overlay font-sans-jp transition-colors duration-200">
      
      {/* Dynamic Main Site Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        bookmarkCount={bookmarks.length}
        onOpenSettings={() => setIsSettingsOpen(true)}
        theme={settings.theme}
      />

      <div className="max-w-7xl mx-auto px-4 md:px-8 py-6 space-y-8">

        {/* EXPLORE TAB VIEW */}
        {activeTab === 'explore' && (
          <>
            <div className="pt-2">
              <HeroBanner
                mangas={mangas}
                onSelectManga={(manga) => setSelectedManga(manga)}
                intervalMs={5000}
              />
            </div>

            <div className="space-y-6">
              <SearchBar
                activeFilterCount={activeFilterCount}
                query={query}
                setQuery={setQuery}
                onSearch={(e, sq) => handleSearch(e, sq, 1)}
                loading={loading}
                isFilterOpen={isFilterOpen}
                setIsFilterOpen={setIsFilterOpen}
                hasActiveFilters={hasActiveFilters}
                focusStyle={settings.focusStyle || 'glow'}
              />


              <FilterDrawer
                filters={filters}
                setFilters={setFilters}
                isOpen={isFilterOpen}
                onClose={() => setIsFilterOpen(false)}
                onReset={() => setFilters(INITIAL_FILTERS)}
              />
            </div>

            <main className="pb-20">
              <MangaGrid
                mangas={mangas}
                loading={loading}
                onCardClick={setSelectedManga}
                bookmarks={bookmarks}
                onToggleBookmark={handleToggleBookmark}
                gridSize={settings.gridSize}
                stampStyle={settings.stampStyle || 'crest'}
                hoverAccent={settings.hoverAccent || 'vermillion'}
                hasMore={hasMore}
                onLoadMore={handleLoadMore}
              />
            </main>

          </>
        )}


        {/* TRENDING TAB VIEW */}
        {activeTab === 'trending' && (
          <div className="pt-4 pb-20 space-y-6">
            
            {/* Header & Sub-Tabs Navigation */}
            <div className="flex flex-col gap-4 border-b border-[var(--border-color)] pb-5">
              <div className="flex flex-col gap-1">
                <div className="flex items-center gap-2">
                  <svg className="w-5 h-5 text-[var(--accent-vermillion)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.879 16.121A3 3 0 1012.015 11L11 14H9c0 .768.293 1.536.879 2.121z" />
                  </svg>
                  <h2 className="font-serif-jp text-xl md:text-2xl font-bold text-[var(--text-color)]">
                    Trending Collections
                  </h2>
                </div>
                <p className="text-xs text-[var(--text-muted)] font-mono">
                  Live trending releases directly from AniList divided by origin format & genre.
                </p>
              </div>

              {/* Format Origin Sub-Tabs (Aesthetic Floating Capsule) */}
              <div className="inline-flex max-w-full items-center gap-1 bg-[var(--surface-color)]/80 backdrop-blur-md border border-[var(--border-color)] p-1 rounded-full overflow-x-auto no-scrollbar shadow-xs self-start">
                {[
                  { id: 'all', label: 'All Formats' },
                  { id: 'manga', label: 'Manga', tag: 'JP' },
                  { id: 'manhwa', label: 'Manhwa', tag: 'KR' },
                  { id: 'manhua', label: 'Manhua', tag: 'CN' }
                ].map(sub => (
                  <button
                    key={sub.id}
                    onClick={() => setTrendingFormat(sub.id)}
                    className={`px-3.5 py-1.5 rounded-full text-xs font-mono transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
                      trendingFormat === sub.id
                        ? 'bg-[var(--accent-vermillion)] text-white font-bold shadow-xs'
                        : 'text-[var(--text-muted)] hover:text-[var(--text-color)] hover:bg-[var(--bg-color)]/60'
                    }`}
                  >
                    <span>{sub.label}</span>
                    {sub.tag && (
                      <span className={`text-[9px] px-1.5 py-0.5 rounded-md font-bold font-mono tracking-wider ${
                        trendingFormat === sub.id 
                          ? 'bg-white/20 text-white' 
                          : 'bg-[var(--bg-color)] text-[var(--text-muted)] border border-[var(--border-color)]'
                      }`}>
                        {sub.tag}
                      </span>
                    )}
                  </button>
                ))}
              </div>

              {/* Genre Pills Filter Row */}
              <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pt-1">
                <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-wider shrink-0 mr-1">
                  Genre:
                </span>
                {[
                  "all", "Action", "Adventure", "Comedy", "Drama", "Fantasy", 
                  "Horror", "Romance", "Sci-Fi", "Slice of Life", "Supernatural", "Isekai"
                ].map(g => (
                  <button
                    key={g}
                    type="button"
                    onClick={() => setTrendingGenre(g)}
                    className={`px-3 py-1 rounded-full text-xs font-mono border transition-all cursor-pointer whitespace-nowrap ${
                      trendingGenre === g
                        ? 'bg-[var(--accent-indigo)] border-[var(--accent-indigo)] text-white font-bold shadow-xs'
                        : 'bg-[var(--surface-color)] border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
                    }`}
                  >
                    {g === 'all' ? 'All Genres' : `#${g}`}
                  </button>
                ))}
              </div>
            </div>

            {/* FORMAT CATALOG GRID VIEW */}
            <MangaGrid
              mangas={trendingMangas}
              loading={loadingTrending}
              hasSearched={true}
              onCardClick={setSelectedManga}
              bookmarks={bookmarks}
              onToggleBookmark={handleToggleBookmark}
              gridSize={settings.gridSize || 'standard'}
              stampStyle={settings.stampStyle || 'crest'}
              hoverAccent={settings.hoverAccent || 'vermillion'}
              hideDivider={true}
              showRank={true}
              showMatchPct={false}
              hasMore={hasMoreTrending}
              onLoadMore={handleLoadMoreTrending}
            />
          </div>
        )}

        {/* SURPRISE ME TAB VIEW */}
        {activeTab === 'surprise' && (
          <SurpriseView
            manga={surpriseManga}
            loading={loadingSurprise}
            onRefresh={handleSurpriseMe}
            fetchBatch={fetchRouletteBatch}
            filters={filters}
            bookmarks={bookmarks}
            onToggleBookmark={handleToggleBookmark}
            onSelectManga={setSelectedManga}
          />
        )}

        {/* BOOKMARKS TAB VIEW */}
        {activeTab === 'bookmarks' && (
          <div className="pt-4 pb-20">
            <BookmarksView
              bookmarks={bookmarks}
              onSelectManga={setSelectedManga}
              onToggleBookmark={handleToggleBookmark}
              onClearAll={() => setBookmarks([])}
              gridSize={settings.gridSize || 'standard'}
              hoverAccent={settings.hoverAccent || 'vermillion'}
            />
          </div>
        )}

      </div>

      {/* Manga Detail Modal */}
      <MangaDetailModal
        manga={selectedManga}
        onClose={() => setSelectedManga(null)}
        onSelectTag={handleTagClick}
        onSelectManga={setSelectedManga}
        isBookmarked={selectedManga ? bookmarks.some(b => b.id === selectedManga.id) : false}
        onToggleBookmark={handleToggleBookmark}
        hoverAccent={settings.hoverAccent || 'vermillion'}
      />

      {/* Settings Modal */}
      <SettingsModal
        settings={settings}
        setSettings={setSettings}
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />

    </div>
  );
}
