import { useState, useEffect, useRef, useMemo, lazy, Suspense } from 'react';
import Header from './components/Header';
import SearchBar from './components/SearchBar';
import MangaGrid from './components/MangaGrid';
import ErrorBanner from './components/ErrorBanner';
const BookmarksView = lazy(() => import('./components/BookmarksView'));
const SurpriseView = lazy(() => import('./components/SurpriseView'));
import HeroBanner from './components/HeroBanner';
import BackToTop from './components/BackToTop';
import { API_ROUTES } from './config';
import { loadVocabulary, FALLBACK_GROUPS, FALLBACK_FORMATS } from './utils/vocabulary';
import useSettings from './hooks/useSettings';
import useBookmarks from './hooks/useBookmarks';

// Feature 75: Lazy-Load Heavy Modals (React.lazy + Suspense dynamic bundle code-splitting)
const FilterDrawer = lazy(() => import('./components/FilterDrawer'));
const MangaDetailModal = lazy(() => import('./components/MangaDetailModal'));
const SettingsModal = lazy(() => import('./components/SettingsModal'));


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
  format_type: null
};


const VALID_TABS = ['explore', 'trending', 'surprise', 'bookmarks'];

const newSessionId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : 'session_' + Math.random().toString(36).substring(2, 9));

const getTabFromPath = (path) => {
  const clean = (path || '').replace(/^\/+|\/+$/g, '').split('/')[0].toLowerCase();
  return VALID_TABS.includes(clean) ? clean : 'explore';
};

const getInitialTab = () => {
  if (typeof window !== 'undefined') {
    // Graceful backward-compatibility cleanup if arriving via legacy '#tab'
    if (window.location.hash) {
      const hash = window.location.hash.replace('#', '').toLowerCase();
      if (VALID_TABS.includes(hash)) {
        const cleanPath = hash === 'explore' ? '/' : `/${hash}`;
        window.history.replaceState({ tab: hash }, '', cleanPath);
        return hash;
      }
    }
    return getTabFromPath(window.location.pathname);
  }
  return 'explore';
};

export default function App() {
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [mangas, setMangas] = useState([]);
  const [selectedManga, setSelectedManga] = useState(null);
  const [searched, setSearched] = useState(false);
  // "Did you mean <title>?" -- offered beside thematic results, never instead
  // of them. The API only sends this for a query that is not an exact title.
  const [titleSuggestion, setTitleSuggestion] = useState(null);

  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [isFilterOpen, setIsFilterOpen] = useState(false);

  // ---- Surprise Me: the App owns the discovery queue (FE-10) --------------
  // This used to be a single `surpriseManga` plus a seen-id array, while
  // SurpriseView kept its own copy of the same titles, its own seen-id Set and
  // its own refill timer. Two owners of one queue is why a draw could be
  // appended twice, skipped, or shown from a stale index.
  const [surpriseQueue, setSurpriseQueue] = useState([]);
  const [loadingSurprise, setLoadingSurprise] = useState(false);
  const [surpriseKey, setSurpriseKey] = useState(0);
  // FE-25: a failed draw must not look like "nothing matched".
  const [surpriseError, setSurpriseError] = useState(null);
  // FE-10: recent ids only. The list is serialized into every request body, so
  // an unbounded one grows into the multi-KB range after a long session.
  const MAX_SEEN_IDS = 200;
  const seenRouletteIdsRef = useRef([]);

  // FE-29: preferences, their DOM attributes and their persistence are one hook.
  const { settings, updateSettings, requestLimit } = useSettings();

  // FE-23: genres, themes and formats come from the served vocabulary. The frozen
  // fallback is what the drawer renders before the request lands (or if it fails),
  // so there is one client source and no fourth hand-copied list.
  const [vocabulary, setVocabulary] = useState({
    groups: FALLBACK_GROUPS,
    formats: FALLBACK_FORMATS
  });
  useEffect(() => {
    let alive = true;
    loadVocabulary().then(next => {
      if (alive) setVocabulary(next);
    });
    return () => {
      alive = false;
    };
  }, []);

  const trendingFormatOptions = useMemo(
    () => [
      { id: 'all', label: 'All Formats' },
      ...vocabulary.formats.map(format => ({ id: format.slug, label: format.label }))
    ],
    [vocabulary.formats]
  );

  const trendingGenreOptions = useMemo(() => {
    const genres = vocabulary.groups.find(group => group.id === 'genre');
    return ['all', ...(genres ? genres.options : [])];
  }, [vocabulary.groups]);

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  // FE-25: "no titles found" and "the request failed" are different answers, and
  // the grid used to give the first for both. One message per fetch path.
  const [searchError, setSearchError] = useState(null);
  const [trendingError, setTrendingError] = useState(null);
  // FE-15: identity of what is on screen. The grid resets its sort pill when it
  // changes, and keeps it when the same set just grows by a page.
  const [searchResultKey, setSearchResultKey] = useState('');

  // FE-29: saved titles, their projection/cap and their persistence are one hook.
  const { bookmarks, toggleBookmark: handleToggleBookmark, clearBookmarks, isBookmarked } =
    useBookmarks();

  // Trending Section Divided State & Filters
  const [trendingFormat, setTrendingFormat] = useState('all'); // 'all' | 'manga' | 'manhwa' | 'manhua'
  const [trendingGenre, setTrendingGenre] = useState('all'); // 'all' | 'Action' | 'Fantasy' | ...
  const [trendingPage, setTrendingPage] = useState(1);
  const [trendingMangas, setTrendingMangas] = useState([]);
  const [loadingTrending, setLoadingTrending] = useState(false);
  // Starts false: the sentinel only exists once page 1 has said there is more.
  // It used to start true, so the observer could ask for page 2 while page 1 was
  // still in flight and spend an AniList request nobody needed.
  const [hasMoreTrending, setHasMoreTrending] = useState(false);

  // FE-17: the session id lived in state *and* a ref that mirrored it, so the
  // state was write-only. The ref is the single owner.
  const sessionIdRef = useRef(newSessionId());

  // One sequence number and one AbortController per request channel. A newer
  // request cancels the older one, and a response whose sequence is stale is
  // never allowed to write to state — a slow page 1 cannot overwrite page 3.
  const requestRef = useRef({ search: 0, trending: 0, surprise: 0 });
  const abortRef = useRef({ search: null, trending: null, surprise: null });
  const surpriseInFlightRef = useRef(null);
  // One in-flight load-more per feed. The sentinel and the virtualized list's
  // row callback can both fire, and neither should spend a second request.
  const loadMoreInFlightRef = useRef({ search: false, trending: false });
  // Set when the roulette answers 404: nothing matches the current filters.
  const [surpriseExhausted, setSurpriseExhausted] = useState(false);

  const beginRequest = (channel) => {
    abortRef.current[channel]?.abort();
    const controller = new AbortController();
    abortRef.current[channel] = controller;
    const seq = ++requestRef.current[channel];
    return { controller, isCurrent: () => requestRef.current[channel] === seq };
  };

  // Falsy rows are dropped here, at insertion, not in the view: a hole in the
  // queue shifts every later offset against currentIndex (FE-28).
  const appendSurpriseRows = (rows) => {
    const clean = (Array.isArray(rows) ? rows : []).filter(row => row && row.id != null);
    if (clean.length === 0) return 0;

    const seen = seenRouletteIdsRef.current;
    for (const row of clean) if (!seen.includes(row.id)) seen.push(row.id);
    if (seen.length > MAX_SEEN_IDS) seen.splice(0, seen.length - MAX_SEEN_IDS);

    setSurpriseQueue(prev => {
      const known = new Set(prev.map(row => row.id));
      return [...prev, ...clean.filter(row => !known.has(row.id))];
    });
    return clean.length;
  };

  const runSurprise = async (forceFresh) => {
    setLoadingSurprise(true);
    setSurpriseExhausted(false);
    setSurpriseError(null);
    const currSeen = forceFresh ? [] : seenRouletteIdsRef.current;
    const currentSession = forceFresh ? newSessionId() : sessionIdRef.current;

    if (forceFresh) {
      sessionIdRef.current = currentSession;
    }

    const { controller, isCurrent } = beginRequest('surprise');

    // Small anticipation delay (~550ms) so "Discovering Titles..." is visibly displayed
    const minDelayPromise = new Promise(resolve => setTimeout(resolve, 550));

    try {
      const [res] = await Promise.all([
        fetch(API_ROUTES.roulette, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({
            query: query || null,
            filters: { ...filters, nsfw: settings.allowNsfw },
            seen_ids: currSeen,
            session_id: currentSession,
            limit: 40
          })
        }),
        minDelayPromise
      ]);
      if (!isCurrent()) return null;
      if (res.status === 404) {
        // Nothing matches the filters. Say it once instead of drawing forever.
        setSurpriseExhausted(true);
        return null;
      }
      if (!res.ok) throw new Error(`roulette request failed: ${res.status}`);
      const data = await res.json();
      if (!isCurrent()) return null;
      return data;
    } catch (err) {
      if (err.name === 'AbortError' || !isCurrent()) return null;
      console.error('Failed to draw roulette recommendation:', err);
      setSurpriseError('Could not reach the recommendation service.');
      return null;
    } finally {
      if (isCurrent()) setLoadingSurprise(false);
    }
  };

  // Single-flight: the tab effect and the view's own fallback both call this on
  // a deep link or a Back navigation, and both used to POST. A second non-forced
  // call now joins the request that is already in flight.
  const handleSurpriseMe = (forceFresh = false) => {
    if (!forceFresh && surpriseInFlightRef.current) return surpriseInFlightRef.current;
    if (forceFresh) {
      // A fresh draw starts a new queue and a new session; the key remount is
      // what resets the view's presentation index.
      setSurpriseQueue([]);
      seenRouletteIdsRef.current = [];
      sessionIdRef.current = newSessionId();
      setSurpriseKey(k => k + 1);
    }
    const promise = runSurprise(forceFresh)
      .then(row => {
        if (row) appendSurpriseRows([row]);
        return row;
      })
      .finally(() => {
        if (surpriseInFlightRef.current === promise) surpriseInFlightRef.current = null;
      });
    surpriseInFlightRef.current = promise;
    return promise;
  };

  // The view asks for more; it never fetches or dedupes on its own (FE-10).
  const fetchRouletteBatch = async (count = 5) => {
    try {
      const res = await fetch(API_ROUTES.rouletteBatch, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filters: { ...filters, nsfw: settings.allowNsfw },
          seen_ids: seenRouletteIdsRef.current,
          session_id: sessionIdRef.current,
          count: count
        })
      });
      if (!res.ok) throw new Error(`roulette batch failed: ${res.status}`);
      const items = await res.json();
      return appendSurpriseRows(items) > 0 ? items : [];
    } catch (err) {
      console.error('Failed to fetch roulette batch:', err);
      return [];
    }
  };

  // Listen for browser Back/Forward navigation (popstate)
  useEffect(() => {
    const handlePopState = () => {
      const tab = getTabFromPath(window.location.pathname);
      setActiveTab(tab);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // Keep active tab synced to clean URL path without '#'
  useEffect(() => {
    const targetPath = activeTab === 'explore' ? '/' : `/${activeTab}`;
    if (window.location.pathname !== targetPath || window.location.hash) {
      window.history.replaceState({ tab: activeTab }, '', targetPath);
    }
  }, [activeTab]);

  // Combined tab navigation and re-click to re-roll
  const handleTabClick = (tabId) => {
    if (tabId === activeTab) {
      // User is already on this section and re-clicked the active tab
      if (tabId === 'surprise') {
        // Aesthetic re-roll / fresh start
        handleSurpriseMe(true);
      } else if (tabId === 'trending') {
        // The row list is replaced from page 1, so the counter goes back with it;
        // otherwise the next load-more asks for page N+1 over a page-1 list.
        setTrendingPage(1);
        setHasMoreTrending(true);
        fetchTrendingData(1, false);
      } else if (tabId === 'explore' || tabId === 'bookmarks') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    } else {
      setActiveTab(tabId);
      const targetPath = tabId === 'explore' ? '/' : `/${tabId}`;
      window.history.pushState({ tab: tabId }, '', targetPath);
      if (tabId === 'surprise') {
        handleSurpriseMe(true);
      }
    }
  };

  useEffect(() => {
    if (activeTab === 'surprise' && surpriseQueue.length === 0 && !loadingSurprise) {
      handleSurpriseMe();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, surpriseQueue.length]);

  // A filter change invalidates the queue: the queued titles were drawn under
  // the old filters. This used to live in the view (debounced, and each copy
  // reset a different half of the state); the queue owner has to reset it.
  const filtersSignature = JSON.stringify(filters);
  const filtersMountedRef = useRef(false);
  useEffect(() => {
    if (!filtersMountedRef.current) {
      filtersMountedRef.current = true;
      return;
    }
    if (activeTab !== 'surprise') return;
    const timer = setTimeout(() => handleSurpriseMe(true), 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersSignature, activeTab]);

  const fetchTrendingData = async (pageNum = 1, append = false) => {
    if (activeTab !== 'trending') return false;
    const { controller, isCurrent } = beginRequest('trending');
    setLoadingTrending(true);
    if (pageNum === 1) setTrendingError(null);

    const limit = 12;
    const formatParam = trendingFormat !== 'all' ? `&format_type=${trendingFormat}` : '';
    const genreParam = trendingGenre !== 'all' ? `&genre=${encodeURIComponent(trendingGenre)}` : '';

    const url = API_ROUTES.trending(pageNum, limit, formatParam, genreParam);

    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error(`trending request failed: ${res.status}`);
      const data = await res.json();
      if (!isCurrent()) return false;

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
      return true;
    } catch (err) {
      // A cancelled request is expected, not an error. A failed page leaves
      // hasMoreTrending alone and reports false so the page counter stays put.
      if (err.name === 'AbortError') return false;
      console.error('Trending fetch error:', err);
      if (isCurrent() && pageNum === 1) {
        setTrendingError('The catalogue did not answer. Try again in a moment.');
        setTrendingMangas([]);
      }
      return false;
    } finally {
      if (isCurrent()) setLoadingTrending(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'trending') {
      setTrendingPage(1);
      fetchTrendingData(1, false);
    }
  }, [activeTab, trendingFormat, trendingGenre]);

  const handleLoadMoreTrending = async () => {
    if (loadMoreInFlightRef.current.trending) return;
    loadMoreInFlightRef.current.trending = true;
    const nextPage = trendingPage + 1;
    // The counter only moves once the page actually arrived. Advancing it first
    // meant one failed request permanently skipped a page nobody ever saw.
    try {
      const ok = await fetchTrendingData(nextPage, true);
      if (ok) setTrendingPage(nextPage);
    } finally {
      loadMoreInFlightRef.current.trending = false;
    }
  };

  // FE-29: the DOM attributes and the storage write moved into useSettings with
  // the value they belong to.

  const hasActiveFilters =
    (filters.status && filters.status.length > 0) ||
    filters.min_year ||
    filters.max_year ||
    filters.min_score > 0 ||
    filters.min_chapters ||
    filters.max_chapters ||
    filters.min_match_pct > 0 ||
    (filters.genres && filters.genres.length > 0) ||
    (filters.exclude_genres && filters.exclude_genres.length > 0) ||
    filters.format_type;


  const activeFilterCount = [
    (filters.status && filters.status.length > 0) ? filters.status.length : 0,
    filters.min_year ? 1 : 0,
    filters.max_year ? 1 : 0,
    filters.min_score > 0 ? 1 : 0,
    (filters.min_chapters || filters.max_chapters) ? 1 : 0,
    filters.min_match_pct > 0 ? 1 : 0,
    (filters.genres && filters.genres.length > 0) ? filters.genres.length : 0,
    (filters.exclude_genres && filters.exclude_genres.length > 0) ? filters.exclude_genres.length : 0,
    filters.format_type ? 1 : 0
  ].reduce((a, b) => a + b, 0);

  const handleSearch = async (e, customQuery = null, pageNum = 1, customFilters = null) => {
    if (e) e.preventDefault();
    const searchQuery = customQuery !== null ? customQuery : query;
    const activeFilters = customFilters !== null ? customFilters : filters;
    if (!searchQuery.trim()) return false;

    const { controller, isCurrent } = beginRequest('search');
    setLoading(true);
    setSearched(true);
    setSearchError(null);
    if (pageNum === 1) {
      setPage(1);
      setSearchResultKey(`${searchQuery}|${JSON.stringify(activeFilters)}`);
    }

    try {
      const res = await fetch(API_ROUTES.recommend, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          query: searchQuery,
          filters: { ...activeFilters, nsfw: settings.allowNsfw },
          limit: requestLimit,
          page: pageNum
        })
      });
      if (!res.ok) throw new Error(`recommend request failed: ${res.status}`);
      const data = await res.json();
      // A superseded page must not append: it would duplicate or reorder rows.
      if (!isCurrent()) return false;

      const newResults = data.results || [];
      if (pageNum === 1) {
        setMangas(newResults);
        // A suggestion belongs to page 1 only; later pages must not resurrect it.
        setTitleSuggestion(data.title_suggestion || null);
      } else {
        setMangas(prev => {
          const existingIds = new Set(prev.map(m => m.id));
          const uniqueNew = newResults.filter(m => !existingIds.has(m.id));
          return [...prev, ...uniqueNew];
        });
      }

      setHasMore(newResults.length >= requestLimit);
      return true;
    } catch (err) {
      if (err.name === 'AbortError') return false;
      console.error('Search error:', err);
      if (isCurrent()) {
        setSearchError('The recommendation service did not answer. The titles you saw before are still here.');
        // A failed first page must not leave the previous query's rows on screen
        // as if they were this query's results.
        if (pageNum === 1) setMangas([]);
      }
      return false;
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  // Option B: Search triggers strictly on explicit Enter keypress or Search button submission.
  // Debounced auto-search on typing has been removed.

  const handleLoadMore = async () => {
    if (loadMoreInFlightRef.current.search) return;
    loadMoreInFlightRef.current.search = true;
    const nextPage = page + 1;
    try {
      const ok = await handleSearch(null, query, nextPage, filters);
      if (ok) setPage(nextPage);
    } finally {
      loadMoreInFlightRef.current.search = false;
    }
  };

  const handleTagClick = (tag) => {
    const tagQuery = `#${tag}`;
    setQuery(tagQuery);
    setSelectedManga(null);
    setActiveTab('explore');
    window.history.pushState({ tab: 'explore' }, '', '/');
    handleSearch(null, tagQuery, 1, filters);
  };

  return (
    <div className={`min-h-screen bg-[var(--bg-color)] text-[var(--text-color)] washi-paper-overlay font-sans-jp transition-colors duration-200 ${
      activeTab === 'surprise' ? 'h-screen max-h-screen overflow-hidden' : ''
    }`}>
      
      {/* Dynamic Main Site Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onSelectTab={handleTabClick}
        bookmarkCount={Array.isArray(bookmarks) ? bookmarks.length : 0}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      {/* FE-24: no `key={activeTab}`. It re-created the whole tab subtree on every
          switch, which threw away state that lived below it (and used to re-seed
          SurpriseView's own queue). Conditional rendering already swaps the
          content; the one thing lost is replaying the fade-in per switch, which
          is cheaper than the remount it paid for. */}
      <div 
        className={`animate-tab-fade-in max-w-7xl mx-auto px-4 md:px-8 ${
        activeTab === 'surprise' ? 'py-0 h-[calc(100vh-76px)] overflow-hidden flex flex-col items-center justify-center' : 'py-6 space-y-8'
      }`}>

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
                onSurpriseMe={() => handleTabClick('surprise')}
              />

              <Suspense fallback={null}>
                <FilterDrawer
                  filters={filters}
                  setFilters={setFilters}
                  categories={vocabulary.groups}
                  isOpen={isFilterOpen}
                  onClose={() => setIsFilterOpen(false)}
                  onReset={() => setFilters(INITIAL_FILTERS)}
                />
              </Suspense>
            </div>

            <main className="pb-20">
              {/* "Did you mean <title>?" -- the close title this query nearly
                  matches, offered as a choice instead of replacing the results.
                  Clicking it searches the exact title, which takes the fast
                  path and returns things similar to that series. */}
              {searched && titleSuggestion && (
                <div className="px-4 sm:px-8 pt-4">
                  <button
                    type="button"
                    onClick={() => {
                      setQuery(titleSuggestion.title);
                      handleSearch(null, titleSuggestion.title, 1, filters);
                    }}
                    className="group flex w-full items-center gap-3 rounded-lg border border-[var(--border-color)] bg-[var(--surface-color)] px-4 py-3 text-left transition-colors hover:border-[var(--accent-indigo)] sm:w-auto"
                    aria-label={`Did you mean ${titleSuggestion.title}? Search that title instead`}
                  >
                    <span className="font-mono text-[11px] uppercase tracking-widest text-[var(--text-muted)]">
                      Did you mean
                    </span>
                    {titleSuggestion.cover_image_url && (
                      <img
                        src={titleSuggestion.cover_image_url}
                        alt=""
                        aria-hidden="true"
                        className="h-10 w-7 flex-none rounded object-cover"
                        loading="lazy"
                      />
                    )}
                    <span className="font-semibold text-[var(--text-color)] group-hover:text-[var(--accent-indigo)]">
                      {titleSuggestion.title}
                    </span>
                    {titleSuggestion.start_year ? (
                      <span className="font-mono text-xs text-[var(--text-muted)]">
                        {titleSuggestion.start_year}
                      </span>
                    ) : null}
                    <span className="ml-auto font-mono text-xs text-[var(--accent-indigo)]">
                      Search →
                    </span>
                  </button>
                </div>
              )}
              <ErrorBanner
                message={searchError}
                label="Search failed"
                onRetry={() => handleSearch(null, query, 1, filters)}
              />
              <MangaGrid
                resultKey={searchResultKey}
                mangas={mangas}
                loading={loading}
                hasSearched={searched}
                onCardClick={setSelectedManga}
                bookmarks={bookmarks}
                onToggleBookmark={handleToggleBookmark}
                gridSize={settings.gridSize}
                stampStyle={settings.stampStyle || 'crest'}
                hoverAccent={settings.hoverAccent || 'vermillion'}
                nsfwBlur={settings.nsfwBlur !== false}
                hasMore={hasMore}
                onLoadMore={handleLoadMore}
                infiniteScroll={false}
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
              <div
                role="group"
                aria-label="Trending format"
                className="inline-flex max-w-full items-center gap-1 bg-[var(--surface-color)]/80 backdrop-blur-md border border-[var(--border-color)] p-1 rounded-full overflow-x-auto no-scrollbar shadow-xs self-start"
              >
                {trendingFormatOptions.map(sub => (
                  <button
                    key={sub.id}
                    type="button"
                    onClick={() => setTrendingFormat(sub.id)}
                    aria-pressed={trendingFormat === sub.id}
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
              <div
                role="group"
                aria-label="Trending genre"
                className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pt-1"
              >
                <span className="text-[10px] font-mono text-[var(--text-muted)] uppercase tracking-wider shrink-0 mr-1">
                  Genre:
                </span>
                {trendingGenreOptions.map(g => (
                  <button
                    key={g}
                    type="button"
                    onClick={() => setTrendingGenre(g)}
                    aria-pressed={trendingGenre === g}
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
            <ErrorBanner
              message={trendingError}
              label="Catalogue unavailable"
              onRetry={() => fetchTrendingData(1, false)}
            />
            <MangaGrid
              resultKey={`trending:${trendingFormat}:${trendingGenre}`}
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
              infiniteScroll={settings.infiniteScroll !== false}
            />
          </div>
        )}

        {/* SURPRISE ME TAB VIEW */}
        {activeTab === 'surprise' && (
          <>
            <Suspense fallback={null}>
              <SurpriseView
                key={surpriseKey}
                items={surpriseQueue}
                loading={loadingSurprise}
                error={surpriseError}
                onRetry={() => handleSurpriseMe(true)}
                onNeedMore={fetchRouletteBatch}
                filters={filters}
                isFilterOpen={isFilterOpen}
                onOpenFilter={() => setIsFilterOpen(true)}
                bookmarks={bookmarks}
                onToggleBookmark={handleToggleBookmark}
                imageLength={settings.surpriseImageLength || 60}
                exhausted={surpriseExhausted}
              />
            </Suspense>

            {/* Universal DRY Filter Drawer in Surprise Me */}
            {isFilterOpen && (
              <div 
                onClick={() => setIsFilterOpen(false)}
                className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md animate-in fade-in duration-200"
              >
                <div 
                  onClick={(e) => e.stopPropagation()}
                  className="w-full max-w-3xl max-h-[88vh] overflow-y-auto rounded-2xl shadow-2xl"
                >
                  <Suspense fallback={null}>
                    <FilterDrawer
                      filters={filters}
                      setFilters={setFilters}
                      isOpen={true}
                      onClose={() => setIsFilterOpen(false)}
                      onReset={() => setFilters(INITIAL_FILTERS)}
                    />
                  </Suspense>
                </div>
              </div>
            )}
          </>
        )}

        {/* BOOKMARKS TAB VIEW */}
        {activeTab === 'bookmarks' && (
          <div className="pt-4 pb-20">
            <Suspense fallback={null}>
              <BookmarksView
                bookmarks={bookmarks}
                onSelectManga={setSelectedManga}
                onToggleBookmark={handleToggleBookmark}
                onClearAll={clearBookmarks}
                gridSize={settings.gridSize || 'standard'}
                hoverAccent={settings.hoverAccent || 'vermillion'}
              />
            </Suspense>
          </div>
        )}

      </div>

      {/* Feature 75: Lazy-Loaded Manga Detail Modal */}
      <Suspense fallback={null}>
        <MangaDetailModal
          manga={selectedManga}
          onClose={() => setSelectedManga(null)}
          onSelectTag={handleTagClick}
          onSelectManga={setSelectedManga}
          isBookmarked={selectedManga ? isBookmarked(selectedManga.id) : false}
          onToggleBookmark={handleToggleBookmark}
          hoverAccent={settings.hoverAccent || 'vermillion'}
          nsfwBlur={settings.nsfwBlur !== false}
          allowNsfw={settings.allowNsfw}
        />
      </Suspense>

      {/* Feature 75: Lazy-Loaded Settings Modal */}
      <Suspense fallback={null}>
        <SettingsModal
          settings={settings}
          setSettings={updateSettings}
          isOpen={isSettingsOpen}
          onClose={() => setIsSettingsOpen(false)}
        />
      </Suspense>

      {/* Feature 08: Back to Top Floating Button */}
      <BackToTop />

    </div>
  );
}
