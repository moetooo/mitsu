import { useRef, useState } from 'react';
import { API_ROUTES } from '../config';
import { PAGE_SIZE } from '../utils/settings';

/**
 * The Explore feed: the query, the rows, the page counter and the suggestion
 * (FE-29 extraction).
 *
 * Search is explicit only - Enter or the button, never typed-ahead (the debounce
 * was removed deliberately, so there is no effect here to re-add it).
 *
 * The rules that came with the code and are covered by tests:
 * - a superseded response never appends or replaces, so a slow page 1 cannot
 *   land on top of a newer query (FE-03);
 * - a failed page 1 clears the rows; a failed later page leaves them, and the
 *   message says which of the two happened (FE-25);
 * - the counter only advances when the page actually arrived (FE-12);
 * - one in-flight flag shared by any manual load-more (FE-31);
 * - the sort is a server order over the whole result set, so a new sort, query
 *   or filter set is always page 1 (FE-15 -> FE-34);
 * - an empty query with filters is a browse, not a no-op: "Manhwa, ranked" is a
 *   real request, and it is the one the drawer's Apply makes. With *no* filters
 *   it is no longer a request at all — Explore's arrival state is the Trending
 *   rail, so there is nothing for a bare catalogue page to sit under.
 * - page 1 owns the request identity: Load More and a URL restore replay the
 *   committed criteria, never an unsubmitted draft.
 */
export default function useSearch({ beginRequest, requestLimit = PAGE_SIZE, allowNsfw = false }) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [mangas, setMangas] = useState([]);
  const [searched, setSearched] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState(null);
  const [resultKey, setResultKey] = useState('');
  const [sort, setSortState] = useState('default');
  // What page 1 committed, exposed so routing can write the same criteria to
  // the URL (a sort or Load More must not mirror an unsubmitted draft).
  const [lastRequest, setLastRequest] = useState({ query: '', filters: {}, sort: 'default' });

  const inFlightRef = useRef(false);
  const lastResultsCountRef = useRef(0);
  // What page 1 was actually asked for. Load More and a restored page send this
  // instead of whatever is on screen now: editing the input without submitting
  // must not change the filters/query page 2 is fetched with.
  const criteriaRef = useRef({ query: '', filters: {}, sort: 'default' });

  const search = async (e, customQuery = null, pageNum = 1, customFilters = null, customSort = null) => {
    if (e) e.preventDefault();
    const committed = criteriaRef.current;
    const isFirstPage = pageNum === 1;

    // Page 1 reads the caller's intent; later pages replay the committed one.
    const searchQuery = isFirstPage
      ? (customQuery !== null ? customQuery : query)
      : committed.query;
    const activeFilters = customFilters !== null ? customFilters : committed.filters;
    const activeSort = isFirstPage
      ? (customSort !== null ? customSort : sort)
      : committed.sort;

    // **An empty query is a request, not a no-op.** It means "browse the
    // catalogue": with filters set that is filter-only discovery, and with none
    // set it is the popularity x score ranking the served catalogue opens on
    // (the server documents both in `RecommendRequest.query`). This used to
    // return early, which is why the app needed a separate Trending endpoint to
    // show anything before a word was typed.
    const { controller, isCurrent } = beginRequest('search');
    setLoading(true);
    setSearched(true);
    setError(null);
    if (isFirstPage) {
      criteriaRef.current = { query: searchQuery, filters: activeFilters, sort: activeSort };
      setLastRequest({ query: searchQuery, filters: activeFilters, sort: activeSort });
      setPage(1);
      setResultKey(`${searchQuery}|${JSON.stringify(activeFilters)}|${activeSort}`);
    }

    try {
      const res = await fetch(API_ROUTES.recommend, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          query: searchQuery,
          filters: { ...activeFilters, nsfw: allowNsfw },
          sort: activeSort,
          limit: requestLimit,
          page: pageNum,
        }),
      });
      if (!res.ok) throw new Error(`recommend request failed: ${res.status}`);
      const data = await res.json();
      // A superseded page must not append: it would duplicate or reorder rows.
      if (!isCurrent()) return false;

      const newResults = data.results || [];
      lastResultsCountRef.current = newResults.length;
      if (isFirstPage) {
        setMangas(newResults);
        // A suggestion belongs to page 1 only; later pages must not resurrect it.
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
        setError('The recommendation service did not answer. The titles you saw before are still here.');
        // A failed first page must not leave the previous query's rows on screen
        // as if they were this query's results.
        if (isFirstPage) setMangas([]);
      }
      return false;
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  const loadMore = async () => {
    if (inFlightRef.current) return false;
    inFlightRef.current = true;
    const nextPage = page + 1;
    let arrived = false;
    try {
      // `search` replays the committed criteria for page >= 2.
      arrived = await search(null, null, nextPage);
      if (arrived) setPage(nextPage);
    } finally {
      inFlightRef.current = false;
    }
    return arrived;
  };


  /**
   * A new order is a new request identity: always page 1, so the user never
   * lands on page 2 of a set they just re-sorted.
   */
  const setSort = (nextSort, filters = null) => {
    setSortState(nextSort);
    // Re-sort what is actually on screen, not an unsubmitted draft in the box.
    const committed = criteriaRef.current;
    const nextFilters = filters !== null ? filters : committed.filters;
    return search(null, committed.query, 1, nextFilters, nextSort);
  };

  /**
   * Restore a URL (refresh, bookmark, Back/Forward). Pages are replayed in
   * order because the API is page-based and only page 1 may be on screen alone.
   * Returns how many pages actually arrived; the caller rewrites a stale
   * `?page=` when this is short of the requested one.
   */
  const restore = async ({ query: nextQuery = '', filters: nextFilters = {}, sort: nextSort = 'default', page: nextPage = 1 }) => {
    setQuery(nextQuery);
    setSortState(nextSort);
    const target = Math.max(1, Math.min(10, Number(nextPage) || 1));
    let reached = 0;
    for (let n = 1; n <= target; n += 1) {
      const arrived = await search(null, nextQuery, n, nextFilters, nextSort);
      if (!arrived) break;
      // An empty page means the URL pointed past the end: stop and let the
      // caller replace `page` with the last page that had rows.
      if (n > 1 && lastResultsCountRef.current === 0) break;
      reached = n;
      if (n > 1) setPage(n);
    }
    return reached;
  };

  /**
   * Browse: page 1 of the catalogue with no query. `sort` stays whatever the
   * caller committed (`default` and `popularity` are both meaningful with no
   * query; `relevance` collapses to `default` server-side).
   */
  /** No criteria left: drop the result set instead of leaving stale rows. */
  const reset = () => {
    // Bump the request sequence so an in-flight response cannot repopulate it.
    beginRequest('search').controller.abort();
    criteriaRef.current = { query: '', filters: {}, sort: 'default' };
    setLastRequest({ query: '', filters: {}, sort: 'default' });
    setQuery('');
    setSortState('default');
    setLoading(false);
    setMangas([]);
    setSearched(false);
    setHasMore(false);
    setError(null);
    setPage(1);
    setResultKey('');
  };

  const searchForTag = (tag, filters) => {
    const tagQuery = `#${tag}`;
    setQuery(tagQuery);
    return search(null, tagQuery, 1, filters);
  };

  const clearSuggestion = () => setTitleSuggestion(null);

  return {
    query,
    setQuery,
    loading,
    mangas,
    searched,
    clearSuggestion,
    page,
    hasMore,
    error,
    resultKey,
    sort,
    lastRequest,
    search,
    setSort,
    loadMore,
    restore,
    reset,
    searchForTag,
  };
}
