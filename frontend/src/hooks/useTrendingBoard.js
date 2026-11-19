import { useCallback, useEffect, useRef, useState } from 'react';
import { API_ROUTES } from '../config';

/** The three formats Explore's rail can show, one at a time. */
export const TRENDING_FORMATS = [
  { format: 'manga', label: 'Manga' },
  { format: 'manhwa', label: 'Manhwa' },
  { format: 'manhua', label: 'Manhua' }
];

/** Ten rows: the rail has no Load More and no page to hand over to. */
export const BOARD_SIZE = 10;

/**
 * The Explore Trending rail's rows: the top ten of one format.
 *
 * The toggle picks the format; there is no paging, no page counter and no
 * `hasMore`, because ten rows is the whole answer. Each format is one request
 * against the catalogue's own ranking (`app/services/trending.py`), cached
 * server-side under `manga:trending:{format}:all:1:10`.
 *
 * Two rules this hook keeps:
 * - a format already fetched is served from the local cache, so flipping
 *   Manga → Manhwa → Manga costs two requests, not three;
 * - a superseded response never writes to state, so a slow first selection
 *   cannot land under the label of a newer one.
 *
 * Failure is silent on purpose: a broken "TRENDING" heading is worse than a rail
 * with no covers, so the section simply stops. Nothing is cached on failure, so
 * re-selecting that format retries instead of staying empty forever.
 */
export default function useTrendingBoard({ active = true, format = 'manga', limit = BOARD_SIZE } = {}) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  const cacheRef = useRef(new Map());
  const seqRef = useRef(0);

  const request = useCallback(
    async (wanted) => {
      const res = await fetch(
        API_ROUTES.trending(1, limit, `&format_type=${encodeURIComponent(wanted)}`)
      );
      if (!res.ok) return null;
      const data = await res.json();
      return Array.isArray(data) ? data.slice(0, limit) : [];
    },
    [limit]
  );

  useEffect(() => {
    if (!active) return undefined;

    const cached = cacheRef.current.get(format);
    if (cached) {
      setRows(cached);
      setLoading(false);
      return undefined;
    }

    const seq = ++seqRef.current;
    setRows([]);
    setLoading(true);

    request(format)
      .then(found => {
        if (seq !== seqRef.current || !found) return;
        cacheRef.current.set(format, found);
        setRows(found);
      })
      .catch(() => {
        // Aborted or failed: leave the rail empty and let a later try retry.
      })
      .finally(() => {
        if (seq === seqRef.current) setLoading(false);
      });

    return () => {
      // Newest format wins: the callbacks above check `seq` before writing.
      seqRef.current += 1;
    };
  }, [active, format, request]);

  return { rows, loading };
}
