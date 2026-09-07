/**
 * Universal Manga Cover Image Cache & Decoded State Tracker
 * Prevents re-shimmering for already-loaded covers across component mounts (Search Grid, Surprise Me, Modal, Hero)
 */

export const loadedCoverCache = new Set();

export const isCoverCached = (url) => {
  return Boolean(url && loadedCoverCache.has(url));
};

export const markCoverCached = (url) => {
  if (url) {
    loadedCoverCache.add(url);
  }
};
