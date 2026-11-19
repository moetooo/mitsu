import { useCallback, useEffect, useState } from 'react';
import { VALID_TABS, getTabFromPath, parseSimilarPath, tabToPath } from '../utils/routeState';

// Re-exported so the public API of this hook stays where callers/tests expect
// it; the grammar itself lives in `utils/routeState.js` now, next to the query
// parameter one.
export { VALID_TABS, getTabFromPath, tabToPath };

/**
 * Tab state and the URL that mirrors it (FE-29 extraction).
 *
 * The tabs are addressed by path (`/`, `/surprise`, `/bookmarks`), with a one-way
 * compatibility read for the legacy `#tab` form. There is no trending route: the
 * ranking lives in Explore's rail, so `/trending` reads as Explore.
 * Two effects kept the two representations in sync: a popstate listener that
 * followed Back/Forward, and a writer that replaced the path whenever the tab
 * changed. Both live here now, so no other code has to remember that `activeTab`
 * and `location.pathname` are the same fact.
 *
 * What a tab *does* on entry (a fresh draw, a page-1 refresh, a scroll) is not
 * routing: it stays with the component that owns those effects.
 */
export const getInitialTab = () => {
  if (typeof window === 'undefined') return 'explore';
  // Graceful backward-compatibility cleanup if arriving via a legacy '#tab'
  if (window.location.hash) {
    const hash = window.location.hash.replace('#', '').toLowerCase();
    if (VALID_TABS.includes(hash)) {
      window.history.replaceState({ tab: hash }, '', tabToPath(hash));
      return hash;
    }
  }
  return getTabFromPath(window.location.pathname);
};

export default function useTabRouting() {
  const [activeTab, setActiveTab] = useState(getInitialTab);

  // Browser Back/Forward.
  useEffect(() => {
    const handlePopState = () => setActiveTab(getTabFromPath(window.location.pathname));
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  // Keep the path in step with the tab, without a hash. The search string is
  // preserved: it carries the explore feed's query/filters/sort/page, and
  // dropping it here is what made Back from another tab lose the search.
  useEffect(() => {
    // `/similar/...` is a different destination, not a tab. Rewriting it here
    // would bounce the full "You Might Also Like" page to Explore on mount.
    if (parseSimilarPath(window.location.pathname)) return undefined;

    const targetPath = tabToPath(activeTab);
    if (window.location.pathname !== targetPath || window.location.hash) {
      window.history.replaceState({ tab: activeTab }, '', targetPath + window.location.search);
    }
  }, [activeTab]);

  /** Switch tabs and record it, so Back returns here. */
  const pushTab = useCallback((tabId) => {
    setActiveTab(tabId);
    window.history.pushState({ tab: tabId }, '', tabToPath(tabId) + window.location.search);
  }, []);

  return { activeTab, setActiveTab, pushTab };
}
