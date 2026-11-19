import { useCallback, useEffect, useRef, useState } from 'react';
import { API_ROUTES } from '../config';
import { PAGE_SIZE } from '../utils/settings';

/**
 * The paged "You Might Also Like" feed.
 *
 * The endpoint answers `{results, has_more}`, so the button's end state is
 * known without asking for an empty page. Like `useSearch`, a superseded
 * response never writes (sequence + AbortController), and appends dedupe by id
 * because the live ANN ranking can overlap between page boundaries.
 */
export default function useSimilar({ mangaId, requestLimit = PAGE_SIZE, allowNsfw = false }) {
  const [mangas, setMangas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(0);
  const [failedPage, setFailedPage] = useState(null);
  const [hasMore, setHasMore] = useState(false);

  const seqRef = useRef(0);
  const abortRef = useRef(null);

  const request = useCallback(
    async (pageNum, replace) => {
      if (!mangaId) return false;
      const seq = ++seqRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setSearched(true);
      setError(null);
      try {
        const res = await fetch(
          API_ROUTES.similarPages(mangaId, pageNum, requestLimit, allowNsfw),
          { signal: controller.signal }
        );
        if (!res.ok) throw new Error(`similar request failed: ${res.status}`);
        const data = await res.json();
        if (seq !== seqRef.current) return false;

        const rows = data.results || [];
        setMangas(prev => {
          if (replace) return rows;
          const seen = new Set(prev.map(item => item.id));
          return [...prev, ...rows.filter(item => !seen.has(item.id))];
        });
        setPage(pageNum);
        setFailedPage(null);
        setHasMore(Boolean(data.has_more));
        return true;
      } catch (err) {
        if (err.name === 'AbortError') return false;
        if (seq === seqRef.current) {
          setError('Could not load similar titles. The list you had is still here.');
          setFailedPage(pageNum);
          if (replace) setMangas([]);
        }
        return false;
      } finally {
        if (seq === seqRef.current) setLoading(false);
      }
    },
    [mangaId, requestLimit, allowNsfw]
  );

  useEffect(() => {
    if (!mangaId) {
      setMangas([]);
      setSearched(false);
      setHasMore(false);
      setPage(0);
      return undefined;
    }
    setMangas([]);
    setPage(0);
    setHasMore(false);
    request(1, true);
    return () => abortRef.current?.abort();
  }, [mangaId, request]);

  const loadMore = useCallback(() => {
    if (!hasMore || loading) return false;
    return request(page + 1, false);
  }, [hasMore, loading, page, request]);

  const retry = useCallback(() => {
    // Retry the page that failed, not the last page that succeeded: a failed
    // Load More must not be turned into a reload of page 1.
    const target = failedPage ?? (page > 0 ? page : 1);
    return request(target, target <= 1);
  }, [failedPage, page, request]);

  return { mangas, loading, searched, error, page, hasMore, loadMore, retry };
}
