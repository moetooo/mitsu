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

const INITIAL_FILTERS = {
  status: [],
  min_year: null,
  max_year: null,
  min_score: 0,
  min_chapters: null,
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
  const [activeTab, setActiveTab] = useState('explore'); // 'explore' | 'compare' | 'bookmarks'
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [mangas, setMangas] = useState([]);
  const [selectedManga, setSelectedManga] = useState(null);
  const [searched, setSearched] = useState(false);

  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [isFilterOpen, setIsFilterOpen] = useState(false);

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

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', settings.theme || 'sumi');
    document.documentElement.setAttribute('data-title-font', settings.fontStyle || 'serif');
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
      console.error("Search API Exception:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleLoadMore = () => {
    const nextPage = page + 1;
    setPage(nextPage);
    handleSearch(null, query, nextPage);
  };

  const handleTagClick = (tag) => {
    setQuery(tag);
    setActiveTab('explore');
    setSelectedManga(null);
    const updatedFilters = { ...filters, genres: [tag] };
    setFilters(updatedFilters);
    handleSearch(null, tag, 1, updatedFilters);
  };



  return (
    <div className="min-h-screen bg-[var(--bg-color)] text-[var(--text-color)] font-sans-jp washi-paper-overlay relative transition-colors duration-200">

      {/* Main Header Bar */}
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
            {/* Manga Wallpaper Art Hero Carousel */}
            <div className="pt-2">
              <HeroBanner
                mangas={mangas}
                onSelectManga={(manga) => setSelectedManga(manga)}
                intervalMs={5000}
              />
            </div>

            <div className="space-y-6">
              <SearchBar
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
            <div className="flex flex-col gap-1 border-b border-[var(--border-color)] pb-4">
              <div className="flex items-center gap-2">
                <span className="text-xl">🔥</span>
                <h2 className="font-serif-jp text-xl md:text-2xl font-bold text-[var(--text-color)]">
                  Trending Titles
                </h2>
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                Most popular active releases and highly rated series in the Mitsu collection.
              </p>
            </div>

            <MangaGrid
              mangas={mangas.filter(m => (m.start_year && m.start_year >= 2020) || m.status === 'RELEASING')}
              loading={loading}
              hasSearched={true}
              onCardClick={setSelectedManga}
              bookmarks={bookmarks}
              onToggleBookmark={handleToggleBookmark}
              cardDensity={settings.cardDensity || 'standard'}
              hoverAccent={settings.hoverAccent || 'vermillion'}
            />
          </div>
        )}

        {/* BOOKMARKS TAB VIEW */}
        {activeTab === 'bookmarks' && (
          <div className="pt-4 pb-20">
            <BookmarksView
              bookmarks={bookmarks}
              onSelectManga={setSelectedManga}
              onToggleBookmark={handleToggleBookmark}
              onClearAll={() => setBookmarks([])}
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
