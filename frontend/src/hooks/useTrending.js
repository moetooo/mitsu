import { useEffect, useRef, useState } from 'react';
import { API_ROUTES } from '../config';

/**
 * The Trending tab's feed (FE-29 extraction).
 *
 * Owns the rows, the page counter, the format/genre pills and their error and
 * loading state. The rules it keeps are the ones earlier stages paid for:
 *
 * - a failed page leaves the counter alone, so one failure does not skip a page
 *   nobody saw (FE-12);
 * - the sentinel and the list callback share one in-flight flag, so neither can
 *   spend a second request (FE-31);
 * - a superseded response never writes to state (FE-03 via `beginRequest`);
 * - a failed *first* page clears the rows rather than showing the previous
 *   filter's titles under the new heading (FE-25).
 */
export default function useTrending({ activeTab, beginRequest, limit = 12 }) {
  const [format, setFormat] = useState('all');
  const [genre, setGenre] = useState('all');
  const [page, setPage] = useState(1);
  const [mangas, setMangas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState(null);

  const inFlightRef = useRef(false);

  const fetchPage = async (pageNum = 1, append = false) => {
    if (activeTab !== 'trending') return false;
    const { controller, isCurrent } = beginRequest('trending');
    setLoading(true);
    if (pageNum === 1) setError(null);

    const formatParam = format !== 'all' ? `&format_type=${format}` : '';
    const genreParam = genre !== 'all' ? `&genre=${encodeURIComponent(genre)}` : '';
    const url = API_ROUTES.trending(pageNum, limit, formatParam, genreParam);

    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) throw new Error(`trending request failed: ${res.status}`);
      const data = await res.json();
      if (!isCurrent()) return false;

      const results = Array.isArray(data) ? data : [];
      if (pageNum === 1 && !append) {
        setMangas(results);
      } else {
        setMangas(prev => {
          const existingIds = new Set(prev.map(m => m.id));
          const uniqueNew = results.filter(m => !existingIds.has(m.id));
          return [...prev, ...uniqueNew];
        });
      }
      setHasMore(results.length >= limit);
      return true;
    } catch (err) {
      // A cancelled request is expected, not an error. A failed page leaves
      // hasMore alone and reports false so the page counter stays put.
      if (err.name === 'AbortError') return false;
      console.error('Trending fetch error:', err);
      if (isCurrent() && pageNum === 1) {
        setError('The catalogue did not answer. Try again in a moment.');
        setMangas([]);
      }
      return false;
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'trending') {
      setPage(1);
      fetchPage(1, false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, format, genre]);

  const loadMore = async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    const nextPage = page + 1;
    // The counter only moves once the page actually arrived.
    try {
      const ok = await fetchPage(nextPage, true);
      if (ok) setPage(nextPage);
    } finally {
      inFlightRef.current = false;
    }
  };

  /** Re-clicking the active Trending tab: page 1 again, rows replaced. */
  const refresh = () => {
    setPage(1);
    setHasMore(true);
    return fetchPage(1, false);
  };

  return {
    mangas,
    loading,
    hasMore,
    error,
    format,
    setFormat,
    genre,
    setGenre,
    page,
    loadMore,
    refresh,
    fetchPage,
    resultKey: `trending:${format}:${genre}`,
  };
}
