import { useCallback, useEffect, useRef } from 'react';
import { parseRoute, parseSimilarPath, serializeRoute } from '../utils/routeState';

/**
 * Keeps the explore state (query, filters, sort, page) mirrored in the URL and
 * feeds the URL back on refresh / bookmark / Back / Forward.
 *
 * The hook deliberately does not own the app's state: App is the only place
 * that knows query/filters/sort and how to fetch. This hook owns exactly two
 * things a component should not hand-roll — the history write and the
 * popstate/initial read — so there is one listener and one writer.
 *
 * `onRestore(route, meta)` is called once on mount (deep link or a plain `/`)
 * and on every popstate. `commit(route, { replace })` is the only writer:
 * pushState for a new intent (search/filter/sort), replaceState for paging.
 */
export default function useRouteSync({ onRestore }) {
  const restoreRef = useRef(onRestore);
  restoreRef.current = onRestore;

  const didInitialRestore = useRef(false);

  useEffect(() => {
    if (didInitialRestore.current) return;
    didInitialRestore.current = true;
    // The full similar page has no Explore criteria; restoring here would reset
    // the search state behind it before the user ever comes back.
    if (parseSimilarPath(window.location.pathname)) return;
    // Ref guard, not a dependency: StrictMode re-runs this effect on the same
    // instance and a second restore would duplicate the first page request.
    restoreRef.current(
      parseRoute(window.location.pathname, window.location.search),
      { source: 'initial' }
    );
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      if (parseSimilarPath(window.location.pathname)) return;
      restoreRef.current(
        parseRoute(window.location.pathname, window.location.search),
        { source: 'popstate' }
      );
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const commit = useCallback((route, { replace = false } = {}) => {
    const url = serializeRoute(route);
    const current = window.location.pathname + window.location.search;
    if (url === current) return false;

    const state = { tab: route.tab, route: true };
    if (replace) window.history.replaceState(state, '', url);
    else window.history.pushState(state, '', url);
    return true;
  }, []);

  return { commit };
}
