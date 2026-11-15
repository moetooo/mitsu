import { useCallback, useEffect, useState } from 'react';

/**
 * Tab state and the URL that mirrors it (FE-29 extraction).
 *
 * The four tabs are addressed by path (`/`, `/trending`, `/surprise`,
 * `/bookmarks`), with a one-way compatibility read for the legacy `#tab` form.
 * Two effects kept the two representations in sync: a popstate listener that
 * followed Back/Forward, and a writer that replaced the path whenever the tab
 * changed. Both live here now, so no other code has to remember that `activeTab`
 * and `location.pathname` are the same fact.
 *
 * What a tab *does* on entry (a fresh draw, a page-1 refresh, a scroll) is not
 * routing: it stays with the component that owns those effects.
 */
export const VALID_TABS = ['explore', 'trending', 'surprise', 'bookmarks'];

export const getTabFromPath = (path) => {
  const clean = (path || '').replace(/^\/+|\/+$/g, '').split('/')[0].toLowerCase();
  return VALID_TABS.includes(clean) ? clean : 'explore';
};

export const tabToPath = (tab) => (tab === 'explore' ? '/' : `/${tab}`);

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

  // Keep the path in step with the tab, without a hash.
  useEffect(() => {
    const targetPath = tabToPath(activeTab);
    if (window.location.pathname !== targetPath || window.location.hash) {
      window.history.replaceState({ tab: activeTab }, '', targetPath);
    }
  }, [activeTab]);

  /** Switch tabs and record it, so Back returns here. */
  const pushTab = useCallback((tabId) => {
    setActiveTab(tabId);
    window.history.pushState({ tab: tabId }, '', tabToPath(tabId));
  }, []);

  return { activeTab, setActiveTab, pushTab };
}
