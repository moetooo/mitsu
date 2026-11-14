/**
 * Universal Manga Cover Image Cache & Decoded State Tracker
 * Prevents re-shimmering for already-loaded covers across component mounts (Search Grid, Surprise Me, Modal, Hero)
 */

// FE-27: bounded. This used to accumulate every cover URL the session ever
// loaded -- a browse with infinite scroll adds hundreds per minute and nothing
// ever removed one. Insertion order is the recency order, so the oldest entry is
// evicted first and a re-load moves the URL to the back.
const MAX_CACHED_COVERS = 400;

export const loadedCoverCache = new Set();

export const isCoverCached = (url) => {
  return Boolean(url && loadedCoverCache.has(url));
};

export const markCoverCached = (url) => {
  if (!url) return;
  if (loadedCoverCache.has(url)) loadedCoverCache.delete(url);
  else if (loadedCoverCache.size >= MAX_CACHED_COVERS) {
    loadedCoverCache.delete(loadedCoverCache.values().next().value);
  }
  loadedCoverCache.add(url);
};
