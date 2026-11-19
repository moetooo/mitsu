/**
 * Which cover URL to actually render, and what to do when it fails.
 *
 * The backend sends a ranked list (`cover_candidates`) plus the first entry as
 * `cover_image_url` for older clients. A single URL cannot survive one provider
 * dying: `uploads.mangadex.org` began answering 200 with an HTML challenge page
 * and every card using it showed a broken image. So the browser walks the list:
 *
 *   1. candidate[0] as-is
 *   2. candidate[0] again with a cache-buster (`?r=1`) - a transient failure or a
 *      cached bad response is the common case, not a dead host
 *   3. candidate[1], candidate[2] from the first step
 *   4. nothing left -> `dead: true`, the caller draws a generated tile, and the
 *      title is reported to the backend so the next cover check visits it first
 *
 * Only one retry per candidate: a host that is gone answers 403 on the second
 * request anyway, and retrying more would triple the requests on a screen with
 * 40 cards.
 */
import { useEffect, useMemo, useState } from 'react';
import { reportBrokenCover } from '../utils/coverReports';

/** Candidate URLs for a manga, best first, de-duplicated. */
export function coverCandidates(manga) {
  const list = Array.isArray(manga?.cover_candidates) ? manga.cover_candidates : [];
  const urls = list
    .map((candidate) => (typeof candidate === 'string' ? candidate : candidate?.url))
    .filter(Boolean);

  // A cached payload or a live provider row may carry only the legacy field.
  if (manga?.cover_image_url) urls.push(manga.cover_image_url);

  return [...new Set(urls)];
}

const bust = (url, attempt) => `${url}${url.includes('?') ? '&' : '?'}r=${attempt}`;

const STATE_FOR = (urls) => ({ index: 0, attempt: 0, dead: urls.length === 0 });

export function useCoverSource(manga) {
  const urls = useMemo(() => coverCandidates(manga), [manga?.cover_image_url, manga?.cover_candidates]);
  const key = urls.join('|');
  const [state, setState] = useState(() => STATE_FOR(urls));

  // React keys the hook instance to the card, but a card can also be reused for
  // a different manga (or the same manga after ingestion adds a candidate).
  useEffect(() => {
    setState(STATE_FOR(urls));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const currentUrl = urls[state.index] ?? null;
  const src = currentUrl && !state.dead ? (state.attempt ? bust(currentUrl, state.attempt) : currentUrl) : null;

  // Every consumer of this hook (card, hero, modal, roulette) reports through the
  // same path, so a title is reported once no matter how many places it appears.
  const dead = state.dead;
  useEffect(() => {
    if (dead) reportBrokenCover(manga?.id);
  }, [dead, manga?.id]);

  const handleError = () => {
    setState((prev) => {
      if (prev.attempt === 0) return { ...prev, attempt: 1 };
      if (prev.index + 1 < urls.length) return { index: prev.index + 1, attempt: 0, dead: false };
      return { ...prev, dead: true };
    });
  };

  return {
    src,
    dead,
    handleError,
    /** How many hosts are still untried after the current one. */
    remaining: urls.length - state.index - 1,
    candidates: urls,
  };
}

export default useCoverSource;
