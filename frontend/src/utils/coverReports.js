/**
 * Tell the backend that a cover will not render.
 *
 * The reader knows a cover is broken before any server-side check does: the URL
 * was valid when it was stored. One report per title per session, fire and
 * forget - a failed report must never surface as an error to the user, and the
 * backend dedupes anyway (one row per title per day).
 */
import { API_ROUTES } from '../config';

const reported = new Set();
let enabled = true;

/** Tests disable this so a rendered card cannot make outbound requests. */
export function setCoverReportingEnabled(next) {
  enabled = next;
}

export function reportBrokenCover(mangaId) {
  if (!enabled || !mangaId || reported.has(mangaId)) return;

  reported.add(mangaId);

  try {
    const request = fetch(API_ROUTES.brokenCover(mangaId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'all_candidates_failed' }),
      // The report usually fires while the page is being closed or navigated away
      // from; keepalive lets it finish.
      keepalive: true,
    });
    // No await, no error handling above this line: the caller is an image error
    // handler and has nothing useful to do with the outcome.
    Promise.resolve(request).catch(() => {});
  } catch {
    /* a blocked fetch (extensions, offline) is not worth a console entry */
  }
}

/** Test seam: forget which titles were reported. */
export function __resetCoverReports() {
  reported.clear();
}
