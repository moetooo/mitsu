import { useCallback, useEffect, useState } from 'react';
import { parseSimilarPath, similarPath } from '../utils/routeState';

/**
 * The full "You Might Also Like" destination (`/similar/{id}`).
 *
 * It is a page, not a tab: pushing it must leave the tab path helper alone, and
 * Back must return to the results the user came from. `useTabRouting` and
 * `useRouteSync` both ignore this path (see `parseSimilarPath`).
 *
 * `close` prefers `history.back()` only when this entry was opened from the app
 * (`state.fromSimilar`). A refresh or a shared link has no previous in-app
 * entry, so it navigates to Explore instead of leaving the site.
 */
export default function useSimilarRoute() {
  const [similarId, setSimilarId] = useState(() =>
    typeof window === 'undefined' ? null : parseSimilarPath(window.location.pathname)
  );

  useEffect(() => {
    const handlePopState = () => setSimilarId(parseSimilarPath(window.location.pathname));
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const openSimilar = useCallback((id) => {
    if (!Number.isInteger(id) || id <= 0) return false;
    window.history.pushState(
      { tab: 'explore', fromSimilar: true },
      '',
      similarPath(id)
    );
    setSimilarId(id);
    return true;
  }, []);

  /** State-only clear for a tab click: `pushTab` has already written the path. */
  const clearSimilar = useCallback(() => setSimilarId(null), []);

  const closeSimilar = useCallback(() => {
    setSimilarId(null);
    if (window.history.state && window.history.state.fromSimilar) {
      window.history.back();
      return;
    }
    window.history.pushState({ tab: 'explore' }, '', '/');
    // A pushState does not fire popstate, but Explore's state still has to be
    // restored from the URL this just wrote (a deep link has no search state).
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, []);

  return { similarId, openSimilar, clearSimilar, closeSimilar };
}
