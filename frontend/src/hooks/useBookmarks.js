import { useCallback, useEffect, useMemo, useState } from 'react';
import { readJSON, writeJSON } from '../utils/storage';
import { toggleBookmark, toStoredBookmarks } from '../utils/bookmarks';

/**
 * Saved titles (FE-29 extraction of FE-18).
 *
 * The blob is projected and capped on the way in as well as on the way out, so a
 * hand-edited or legacy list cannot load thousands of entries. Add/remove, the
 * display projection and `MAX_BOOKMARKS` all live in `utils/bookmarks.js`; this
 * hook owns only the state and its persistence.
 */
export const BOOKMARK_KEYS = ['mitsu_bookmarks', 'mangamind_bookmarks'];

export default function useBookmarks() {
  const [bookmarks, setBookmarks] = useState(() => {
    const saved = readJSON(BOOKMARK_KEYS, []);
    return Array.isArray(saved) ? toStoredBookmarks(saved) : [];
  });

  useEffect(() => {
    if (Array.isArray(bookmarks)) writeJSON('mitsu_bookmarks', toStoredBookmarks(bookmarks));
  }, [bookmarks]);

  const toggle = useCallback((mangaToToggle) => {
    setBookmarks(prev => toggleBookmark(prev, mangaToToggle));
  }, []);

  const clear = useCallback(() => setBookmarks([]), []);

  const isBookmarked = useCallback(
    (id) => bookmarks.some(entry => entry.id === id),
    [bookmarks]
  );

  return useMemo(
    () => ({ bookmarks, toggleBookmark: toggle, clearBookmarks: clear, isBookmarked }),
    [bookmarks, toggle, clear, isBookmarked]
  );
}
