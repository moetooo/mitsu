import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import Header from './components/layout/Header';
import SearchBar from './components/controls/SearchBar';
import MangaGrid from './components/manga/MangaGrid';
import ErrorBanner from './components/common/ErrorBanner';
const BookmarksView = lazy(() => import('./components/views/BookmarksView'));
const SimilarView = lazy(() => import('./components/views/SimilarView'));
const SurpriseView = lazy(() => import('./components/views/SurpriseView'));
import HeroBanner from './components/explore/HeroBanner';
import BackToTop from './components/common/BackToTop';
import TrendingSection from './components/explore/TrendingSection';
import { loadVocabulary, FALLBACK_GROUPS, FALLBACK_FORMATS } from './utils/vocabulary';
import { INITIAL_FILTERS, summarizeFilters } from './utils/filters';
import useSettings from './hooks/useSettings';
import useBookmarks from './hooks/useBookmarks';
import useTabRouting from './hooks/useTabRouting';
import useSearch from './hooks/useSearch';
import useSurprise from './hooks/useSurprise';
import useRouteSync from './hooks/useRouteSync';
import useSimilarRoute from './hooks/useSimilarRoute';
import useTrendingBoard from './hooks/useTrendingBoard';

// Feature 75: Lazy-Load Heavy Modals (React.lazy + Suspense dynamic bundle code-splitting)
const FilterDrawer = lazy(() => import('./components/controls/FilterDrawer'));
const MangaDetailModal = lazy(() => import('./components/manga/MangaDetailModal'));
const SettingsModal = lazy(() => import('./components/controls/SettingsModal'));



export default function App() {
  // FE-29: tab state, the URL that mirrors it and Back/Forward live in one hook.
  const { activeTab, setActiveTab, pushTab } = useTabRouting();
  // `/similar/{id}` is a destination pushed from a title card, not a tab. The
  // hook owns its history entry so Back returns to the results that were open.
  const { similarId, openSimilar, clearSimilar, closeSimilar } = useSimilarRoute();

  const [selectedManga, setSelectedManga] = useState(null);

  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [isFilterOpen, setIsFilterOpen] = useState(false);

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

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);


  // FE-29: saved titles, their projection/cap and their persistence are one hook.
  const { bookmarks, toggleBookmark: handleToggleBookmark, clearBookmarks, isBookmarked } =
    useBookmarks();


  // One sequence number and one AbortController per request channel. A newer
  // request cancels the older one, and a response whose sequence is stale is
  // never allowed to write to state — a slow page 1 cannot overwrite page 3.
  const requestRef = useRef({ search: 0, surprise: 0 });
  const abortRef = useRef({ search: null, surprise: null });

  const beginRequest = (channel) => {
    abortRef.current[channel]?.abort();
    const controller = new AbortController();
    abortRef.current[channel] = controller;
    const seq = ++requestRef.current[channel];
    return { controller, isCurrent: () => requestRef.current[channel] === seq };
  };

  // FE-29: the Explore feed - query, rows, page counter, suggestion - is one hook.
  // Explore does not browse the catalogue on arrival any more: the Trending rail
  // is the arrival content, and the grid belongs to a query (or a filter-only
  // browse) only.
  const {
    query,
    setQuery,
    loading,
    mangas,
    searched,
    hasMore,
    error: searchError,
    resultKey: searchResultKey,
    sort,
    page,
    lastRequest,
    search: handleSearch,
    setSort,
    loadMore: loadMoreSearch,
    restore: restoreSearch,
    reset: resetSearch,
    searchForTag
  } = useSearch({ beginRequest, requestLimit, allowNsfw: settings.allowNsfw });

  // The Explore rail's rows: the top ten of the format the toggle is on. The
  // toggle is local state on purpose — choosing a format changes what the rail
  // shows, not where the user is, so it writes no URL and no history entry.
  const [trendingFormat, setTrendingFormat] = useState('manga');
  const { rows: trendingItems, loading: trendingLoading } = useTrendingBoard({
    active: activeTab === 'explore',
    format: trendingFormat
  });

  // URL <-> state. The hook owns the history write and the popstate read; App
  // owns the state it restores (query/filters/sort live in three places).
  const routeRestoreRef = useRef(null);
  const { commit: commitRoute } = useRouteSync({
    onRestore: (route, meta) => routeRestoreRef.current?.(route, meta)
  });

  // FE-29: the Surprise Me queue - rows, seen ids, session, single-flight draw,
  // batch refill and the two invalidation effects - is one hook.
  const {
    queue: surpriseQueue,
    loading: loadingSurprise,
    key: surpriseKey,
    error: surpriseError,
    exhausted: surpriseExhausted,
    draw: handleSurpriseMe,
    fetchBatch: fetchRouletteBatch
  } = useSurprise({
    activeTab,
    beginRequest,
    filters,
    query,
    allowNsfw: settings.allowNsfw
  });

  // Combined tab navigation and re-click to re-roll
  // The logo means "start over", not "switch tab": a search, filters, a sort,
  // a similar page or a paged scroll must not survive a trip home.
  const handleHome = () => {
    setSelectedManga(null);
    clearSimilar();
    setActiveTab('explore');
    setQuery('');
    setFilters(INITIAL_FILTERS);
    // Home means "start over": Explore's arrival state is the Trending rail, not
    // a catalogue grid, so the result set is dropped rather than refetched.
    resetSearch();
    if (window.location.pathname !== '/' || window.location.search) {
      commitRoute({ tab: 'explore', q: '', filters: INITIAL_FILTERS, sort: 'default', page: 1 });
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleTabClick = (tabId) => {
    // A tab click leaves the full similar page, so the destination state must
    // clear before `pushTab` replaces the path.
    clearSimilar();
    if (tabId === activeTab) {
      // User is already on this section and re-clicked the active tab
      if (tabId === 'surprise') {
        // Aesthetic re-roll / fresh start
        handleSurpriseMe(true);
      } else if (tabId === 'explore' || tabId === 'bookmarks') {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    } else {
      pushTab(tabId);
      if (tabId === 'surprise') {
        handleSurpriseMe(true);
      }
    }
  };

  // FE-29: the DOM attributes and the storage write moved into useSettings with
  // the value they belong to.

  // The badge and the "are filters active" question come from one summary now:
  // the drawer stages a draft, so App and the drawer must agree on what counts.
  const { active: hasActiveFilters, count: activeFilterCount } = summarizeFilters(filters);

  // A result set with no committed query is the catalogue, not an answer to
  // anything, so its failure is the catalogue's failure. This is now only the
  // error banner's wording — the grid itself has one shape.
  const catalogueOnly = !(lastRequest.query || '').trim();

  // Applying is the only way a drawer filter reaches the results.
  //
  // It also runs the request: with a query in the box it searches immediately
  // with the applied filters, and with an empty box it browses the catalogue
  // with the filters alone. Clearing every filter returns to the arrival state:
  // no result set, so the Trending rail is the page again.
  const applyFilters = (next) => {
    setFilters(next);
    setIsFilterOpen(false);
    if (activeTab !== 'explore') return;

    if (query.trim() || summarizeFilters(next).active) {
      runSearch(null, query, 1, next, sort);
    } else {
      runSearch(null, '', 1, next, 'default');
    }
  };

  // A new intent (submit, filter Apply, tag, suggestion) is page 1 and one
  // history entry. The URL is written before the request: a failed request must
  // still leave the address bar describing what the user asked for.
  //
  // An empty box with no filters is not a request any more: it is the arrival
  // state, so it drops the result set (which brings the Trending rail back)
  // instead of leaving the previous query's rows under no query.
  const runSearch = (e, sq, pageNum = 1, nextFilters = filters, nextSort = sort) => {
    const effectiveQuery = sq !== null && sq !== undefined ? sq : query;
    if (!effectiveQuery.trim() && !summarizeFilters(nextFilters).active) {
      resetSearch();
      commitRoute({ tab: 'explore', q: '', filters: nextFilters, sort: 'default', page: 1 }, { replace: true });
      return false;
    }
    commitRoute({ tab: 'explore', q: effectiveQuery, filters: nextFilters, sort: nextSort, page: pageNum });
    return handleSearch(e, sq, pageNum, nextFilters, nextSort);
  };

  // A sort is a server order over whatever is on screen — a search *or* a
  // browse — so it needs no query to be meaningful.
  const handleSortChange = (nextSort) => {
    const committed = lastRequest;
    if (!searched) return;
    commitRoute({ tab: 'explore', q: committed.query, filters: committed.filters, sort: nextSort, page: 1 });
    setSort(nextSort, committed.filters);
  };

  const handleLoadMore = async () => {
    const arrived = await loadMoreSearch();
    if (arrived) {
      // Paging replaces the entry: Back should return to the search, not walk
      // through every page the user scrolled.
      commitRoute(
        { tab: 'explore', q: lastRequest.query, filters: lastRequest.filters, sort: lastRequest.sort, page: page + 1 },
        { replace: true }
      );
    }
  };

  // Option B: Search triggers strictly on explicit Enter keypress or Search button submission.
  // Debounced auto-search on typing has been removed.

  const handleTagClick = (tag) => {
    setSelectedManga(null);
    clearSimilar();
    // One history entry that also names the tab: `pushTab` here would create a
    // second entry and Back would need two presses for one click.
    setActiveTab('explore');
    commitRoute({ tab: 'explore', q: `#${tag}`, filters, sort, page: 1 });
    searchForTag(tag, filters);
  };

  // Refresh / bookmark / Back / Forward: rehydrate all four pieces of state and
  // replay pages 1..N. A URL page past the end is clamped and rewritten. A URL
  // with no query and no filters is `/` — the arrival state — and it restores the
  // Trending rail instead of a result set.
  const restoreRoute = (route) => {
    if (route.tab !== 'explore') {
      setActiveTab(route.tab);
      return;
    }
    setActiveTab('explore');
    setFilters(route.filters);
    setQuery(route.q);

    if (!route.q.trim() && !summarizeFilters(route.filters).active) {
      resetSearch();
      return;
    }

    restoreSearch({ query: route.q, filters: route.filters, sort: route.sort, page: route.page })
      .then((reached) => {
        // `reached === 0` means the replay was superseded or failed before
        // page 1: leave the URL alone rather than replacing a newer intent.
        if (reached > 0 && route.page !== reached) {
          commitRoute({ ...route, page: reached }, { replace: true });
        }
      });
  };
  routeRestoreRef.current = restoreRoute;

  return (
    <div className={`min-h-screen bg-[var(--bg-color)] text-[var(--text-color)] app-backdrop font-body transition-colors duration-200 ${
      activeTab === 'surprise' ? 'h-screen max-h-screen overflow-hidden' : ''
    }`}>
      
      {/* Dynamic Main Site Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onSelectTab={handleTabClick}
        bookmarkCount={Array.isArray(bookmarks) ? bookmarks.length : 0}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onHome={handleHome}
      />

      {/* FE-24: no `key={activeTab}`. It re-created the whole tab subtree on every
          switch, which threw away state that lived below it (and used to re-seed
          SurpriseView's own queue). Conditional rendering already swaps the
          content; the one thing lost is replaying the fade-in per switch, which
          is cheaper than the remount it paid for. */}
      {similarId ? (
        <Suspense fallback={null}>
          <SimilarView
            mangaId={similarId}
            onBack={closeSimilar}
            onCardClick={setSelectedManga}
            bookmarks={bookmarks}
            onToggleBookmark={handleToggleBookmark}
            gridSize={settings.gridSize || 'standard'}
            hoverAccent={settings.hoverAccent || 'vermillion'}
            nsfwBlur={settings.nsfwBlur !== false}
            allowNsfw={settings.allowNsfw}
            requestLimit={requestLimit}
          />
        </Suspense>
      ) : (
      <div 
        className={`animate-tab-fade-in max-w-7xl mx-auto px-4 md:px-8 ${
        activeTab === 'surprise' ? 'py-0 h-[calc(100vh-76px)] overflow-hidden flex flex-col items-center justify-center' : 'py-6 space-y-8'
      }`}>

        {/* EXPLORE TAB VIEW */}
        {activeTab === 'explore' && (
          <>
            <div className="pt-2">
              {/* The hero slides are the rail's rows until a result set exists:
                  same request, real covers on the first paint instead of the
                  four static posters, and it follows the format toggle. */}
              <HeroBanner
                mangas={searched ? mangas : (trendingItems.length > 0 ? trendingItems : mangas)}
                onSelectManga={(manga) => setSelectedManga(manga)}
                intervalMs={5000}
              />
            </div>

            <div className="space-y-6">
              <SearchBar
                activeFilterCount={activeFilterCount}
                query={query}
                setQuery={setQuery}
                onSearch={(e, sq) => runSearch(e, sq, 1, filters, sort)}
                loading={loading}
                isFilterOpen={isFilterOpen}
                setIsFilterOpen={setIsFilterOpen}
                hasActiveFilters={hasActiveFilters}
              />

              <Suspense fallback={null}>
                <FilterDrawer
                  filters={filters}
                  setFilters={setFilters}
                  onApply={applyFilters}
                  categories={vocabulary.groups}
                  isOpen={isFilterOpen}
                  onClose={() => setIsFilterOpen(false)}
                />
              </Suspense>
            </div>

            {/* The arrival section. Gone the moment a result set exists — a
                search or a filter-only browse — and back when it is cleared. */}
            {!searched && (
              <TrendingSection
                items={trendingItems}
                loading={trendingLoading}
                format={trendingFormat}
                onChangeFormat={setTrendingFormat}
                onSelect={setSelectedManga}
              />
            )}

            <main className="pb-20">
              <ErrorBanner
                message={searchError}
                label={catalogueOnly ? 'Catalogue unavailable' : 'Search failed'}
                onRetry={() => runSearch(null, query, 1, filters, sort)}
              />
              <MangaGrid
                resultKey={searchResultKey}
                mangas={mangas}
                loading={loading}
                hasSearched={searched}
                filtersActive={hasActiveFilters}
                onCardClick={setSelectedManga}
                bookmarks={bookmarks}
                onToggleBookmark={handleToggleBookmark}
                gridSize={settings.gridSize}
                hoverAccent={settings.hoverAccent || 'vermillion'}
                nsfwBlur={settings.nsfwBlur !== false}
                hasMore={hasMore}
                // No rank badges on a result set: numbering positions belongs
                // to the rail, not to an answer. A match percentage still means
                // something when there is a query to match against, and nothing
                // at all on a filter-only browse (no query, no similarity).
                showRank={false}
                showMatchPct={!catalogueOnly}
                sort={sort}
                queryActive={Boolean((lastRequest.query || '').trim())}
                onSortChange={handleSortChange}
                onLoadMore={() => handleLoadMore()}
              />
            </main>
          </>
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
                      onApply={applyFilters}
                      categories={vocabulary.groups}
                      isOpen={true}
                      onClose={() => setIsFilterOpen(false)}
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
      )}

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
          onOpenSimilar={(id) => {
            setSelectedManga(null);
            openSimilar(id);
          }}
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
