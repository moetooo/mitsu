import { useRef, useState } from 'react';
import { API_ROUTES } from '../config';

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
 * - one in-flight flag shared by the sentinel and any manual load-more (FE-31);
 * - `resultKey` identifies what is on screen, so the grid resets its sort pill
 *   for a new search and keeps it when the same set grows (FE-15).
 */
export default function useSearch({ beginRequest, requestLimit = 12, allowNsfw = false }) {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [mangas, setMangas] = useState([]);
  const [searched, setSearched] = useState(false);
  const [titleSuggestion, setTitleSuggestion] = useState(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState(null);
  const [resultKey, setResultKey] = useState('');

  const inFlightRef = useRef(false);

  const search = async (e, customQuery = null, pageNum = 1, customFilters = null) => {
    if (e) e.preventDefault();
    const searchQuery = customQuery !== null ? customQuery : query;
    const activeFilters = customFilters !== null ? customFilters : {};
    if (!searchQuery.trim()) return false;

    const { controller, isCurrent } = beginRequest('search');
    setLoading(true);
    setSearched(true);
    setError(null);
    if (pageNum === 1) {
      setPage(1);
      setResultKey(`${searchQuery}|${JSON.stringify(activeFilters)}`);
    }

    try {
      const res = await fetch(API_ROUTES.recommend, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          query: searchQuery,
          filters: { ...activeFilters, nsfw: allowNsfw },
          limit: requestLimit,
          page: pageNum,
        }),
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
        setError('The recommendation service did not answer. The titles you saw before are still here.');
        // A failed first page must not leave the previous query's rows on screen
        // as if they were this query's results.
        if (pageNum === 1) setMangas([]);
      }
      return false;
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  const loadMore = async (filters) => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    const nextPage = page + 1;
    try {
      const arrived = await search(null, query, nextPage, filters);
      if (arrived) setPage(nextPage);
    } finally {
      inFlightRef.current = false;
    }
  };

  /** `#tag` from a card or the detail modal: same path as a typed query. */
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
    titleSuggestion,
    clearSuggestion,
    page,
    hasMore,
    error,
    resultKey,
    search,
    loadMore,
    searchForTag,
  };
}
