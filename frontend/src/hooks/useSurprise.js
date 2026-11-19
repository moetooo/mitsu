import { useEffect, useRef, useState } from 'react';
import { API_ROUTES } from '../config';

// A per-draw session id: the roulette dedupes by session, so a fresh draw starts
// a new one.
const newSessionId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : 'session_' + Math.random().toString(36).substring(2, 9);

// FE-10: recent ids only. The list is serialized into every request body, so an
// unbounded one grows into the multi-KB range after a long session.
const MAX_SEEN_IDS = 200;

/**
 * The Surprise Me discovery queue (FE-29 extraction of FE-10/FE-17/FE-25/FE-28).
 *
 * The app owns the queue: one list of rows, one seen-id list, one session id. The
 * view asks for more and renders; it never fetches, dedupes or keeps a second
 * copy of the same titles (that is what used to append, skip and re-show rows).
 *
 * The invariants that travel with the code:
 * - falsy rows are dropped at insertion, not in the view, because a hole in the
 *   queue shifts every later offset against the current index (FE-28);
 * - the seen-id list is capped (FE-10) and is the session's own memory;
 * - a non-forced draw joins the request already in flight, so a deep link plus
 *   the view's fallback is one POST, and a fresh draw starts a new session and a
 *   new queue key (FE-17: the ref is the only owner of the session id);
 * - a 404 says "nothing matches these filters" once, instead of drawing forever
 *   (FE-25), and is cleared on the next attempt;
 * - the queue is reset when the filters change while the tab is open, because
 *   the queued titles were drawn under the old filters.
 */
export default function useSurprise({ activeTab, beginRequest, filters, query, allowNsfw = false }) {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(false);
  const [key, setKey] = useState(0);
  const [error, setError] = useState(null);
  const [exhausted, setExhausted] = useState(false);

  const seenIdsRef = useRef([]);
  const sessionIdRef = useRef(newSessionId());
  const inFlightRef = useRef(null);
  // B-05: the signature the queue was drawn under. Entering the tab re-runs the
  // filter effect, and comparing signatures (instead of "have we mounted yet")
  // is what stops entry from being mistaken for a filter change.
  const drawnFiltersSignatureRef = useRef(null);
  const filterDrawPendingRef = useRef(false);

  const appendRows = (rows) => {
    const clean = (Array.isArray(rows) ? rows : []).filter((row) => row && row.id != null);
    if (clean.length === 0) return 0;

    const seen = seenIdsRef.current;
    for (const row of clean) if (!seen.includes(row.id)) seen.push(row.id);
    if (seen.length > MAX_SEEN_IDS) seen.splice(0, seen.length - MAX_SEEN_IDS);

    // Dedupe against the queue *and* within the batch: the batch endpoint can
    // return the same id twice, and two rows with one id is both a duplicated
    // card and a React key collision.
    let added = 0;
    setQueue((prev) => {
      const known = new Set(prev.map((row) => row.id));
      const fresh = [];
      for (const candidate of clean) {
        if (known.has(candidate.id)) continue;
        known.add(candidate.id);
        fresh.push(candidate);
      }
      added = fresh.length;
      return [...prev, ...fresh];
    });
    return added;
  };

  const runSurprise = async (forceFresh) => {
    setLoading(true);
    setExhausted(false);
    setError(null);
    const currSeen = forceFresh ? [] : seenIdsRef.current;
    const currentSession = forceFresh ? newSessionId() : sessionIdRef.current;

    if (forceFresh) {
      sessionIdRef.current = currentSession;
    }

    const { controller, isCurrent } = beginRequest('surprise');

    // Small anticipation delay (~550ms) so "Discovering Titles..." is visibly displayed
    const minDelayPromise = new Promise((resolve) => setTimeout(resolve, 550));

    try {
      const [res] = await Promise.all([
        fetch(API_ROUTES.roulette, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          body: JSON.stringify({
            query: query || null,
            filters: { ...filters, nsfw: allowNsfw },
            seen_ids: currSeen,
            session_id: currentSession,
            limit: 40,
          }),
        }),
        minDelayPromise,
      ]);
      if (!isCurrent()) return null;
      if (res.status === 404) {
        // Nothing matches the filters. Say it once instead of drawing forever.
        setExhausted(true);
        return null;
      }
      if (!res.ok) throw new Error(`roulette request failed: ${res.status}`);
      const data = await res.json();
      if (!isCurrent()) return null;
      return data;
    } catch (err) {
      if (err.name === 'AbortError' || !isCurrent()) return null;
      console.error('Failed to draw roulette recommendation:', err);
      setError('Could not reach the recommendation service.');
      return null;
    } finally {
      if (isCurrent()) setLoading(false);
    }
  };

  // Single-flight: the tab effect and the view's own fallback both call this on
  // a deep link or a Back navigation, and both used to POST. A second non-forced
  // call now joins the request that is already in flight.
  const draw = (forceFresh = false) => {
    if (!forceFresh && inFlightRef.current) return inFlightRef.current;
    if (forceFresh) {
      // A fresh draw starts a new queue and a new session; the key remount is
      // what resets the view's presentation index.
      setQueue([]);
      seenIdsRef.current = [];
      sessionIdRef.current = newSessionId();
      setKey((k) => k + 1);
    }
    const promise = runSurprise(forceFresh)
      .then((row) => {
        if (row) appendRows([row]);
        return row;
      })
      .finally(() => {
        if (inFlightRef.current === promise) inFlightRef.current = null;
      });
    inFlightRef.current = promise;
    return promise;
  };

  /** The view asks for more; it never fetches or dedupes on its own (FE-10). */
  const fetchBatch = async (count = 5) => {
    try {
      const res = await fetch(API_ROUTES.rouletteBatch, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filters: { ...filters, nsfw: allowNsfw },
          seen_ids: seenIdsRef.current,
          session_id: sessionIdRef.current,
          count: count,
        }),
      });
      if (!res.ok) throw new Error(`roulette batch failed: ${res.status}`);
      const items = await res.json();
      return appendRows(items) > 0 ? items : [];
    } catch (err) {
      console.error('Failed to fetch roulette batch:', err);
      return [];
    }
  };

  // Entering the tab with an empty queue draws once.
  useEffect(() => {
    if (activeTab === 'surprise' && queue.length === 0 && !loading) {
      draw();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, queue.length]);

  // A filter change invalidates the queue: the queued titles were drawn under the
  // old filters. This used to live in the view (debounced, and each copy reset a
  // different half of the state); the queue owner has to reset it.
  const filtersSignature = JSON.stringify(filters);
  useEffect(() => {
    if (activeTab !== 'surprise') {
      // A redraw scheduled here cannot run while the tab is closed. Adopt the
      // signature only if none was pending, so coming back never leaves a queue
      // built under filters the user has since changed.
      if (!filterDrawPendingRef.current) drawnFiltersSignatureRef.current = filtersSignature;
      return undefined;
    }
    if (drawnFiltersSignatureRef.current === null) {
      drawnFiltersSignatureRef.current = filtersSignature;
      return undefined;
    }
    if (drawnFiltersSignatureRef.current === filtersSignature) return undefined;

    filterDrawPendingRef.current = true;
    const timer = setTimeout(() => {
      filterDrawPendingRef.current = false;
      drawnFiltersSignatureRef.current = filtersSignature;
      draw(true);
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersSignature, activeTab]);

  return {
    queue,
    loading,
    key,
    error,
    exhausted,
    draw,
    fetchBatch,
    seenIds: seenIdsRef,
  };
}
