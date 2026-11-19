import { INITIAL_FILTERS } from './filters';

/**
 * The one place the explore state has a URL spelling.
 *
 * Why this exists: query, filters, sort and page used to live only in React
 * state, so a refresh, a bookmark or Back/Forward forgot all four. This module
 * is the grammar (parse/serialize) and nothing else — no React, no history, no
 * network — so it can be unit-tested and reused by the hook and by App.
 *
 * Canonical form omits defaults (empty lists, 0 floors, `sort=default`,
 * `page=1`). That keeps URLs short and makes history entries stable: a request
 * that changes nothing writes nothing.
 */

// `explore` owns the catalogue entirely: its arrival state is the Trending rail,
// and there is no separate trending route to land on any more. A `/trending`
// bookmark therefore reads as Explore, which shows the same ranking.
export const VALID_TABS = ['explore', 'surprise', 'bookmarks'];
export const SORT_IDS = ['default', 'relevance', 'popularity'];

const MAX_QUERY_LENGTH = 300;
const MAX_LIST_ITEMS = 20;
const MAX_ITEM_LENGTH = 50;

const asText = (value) => (typeof value === 'string' ? value.trim() : '');

const asList = (value) => {
  const parts = Array.isArray(value) ? value : [value];
  const out = [];
  for (const part of parts) {
    if (typeof part !== 'string') continue;
    for (const piece of part.split(',')) {
      const clean = piece.trim().slice(0, MAX_ITEM_LENGTH);
      if (clean && !out.includes(clean)) out.push(clean);
      if (out.length >= MAX_LIST_ITEMS) return out;
    }
  }
  return out;
};

const clampInt = (value, min, max) => {
  // `Number(null)` is 0, which silently turned a missing `?min_chapters=` into
  // a real 0-0 chapter range on every fresh load.
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  const rounded = Math.round(number);
  return rounded >= min && rounded <= max ? rounded : null;
};

const clampFloat = (value, min, max) => {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return number >= min && number <= max ? number : null;
};

export const tabToPath = (tab) => (tab === 'explore' ? '/' : `/${tab}`);

/**
 * The full "You Might Also Like" page has its own path, not a tab.
 *
 * `/similar/79475` is deliberately outside the tab grammar: it is a destination
 * pushed from a title card, and both `useTabRouting` and `useRouteSync` must
 * leave it alone instead of treating it as Explore and rewriting it to `/`.
 */
export const similarPath = (id) => `/similar/${Number(id)}`;

export const parseSimilarPath = (path) => {
  const match = /^\/similar\/(\d+)\/?$/.exec(path || '');
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isInteger(id) && id > 0 ? id : null;
};

export const getTabFromPath = (path) => {
  const clean = (path || '').replace(/^\/+|\/+$/g, '').split('/')[0].toLowerCase();
  return VALID_TABS.includes(clean) ? clean : 'explore';
};

/**
 * Read one route out of a location. Anything malformed is dropped rather than
 * forwarded to the API: the server also validates, but a bad bookmark should
 * render a sane page, not a 422.
 */
export function parseRoute(pathname = '/', search = '') {
  const params = new URLSearchParams(search);

  const filters = { ...INITIAL_FILTERS };

  filters.status = asList(params.getAll('status'));
  // `tags` is the readable alias the feature was described with; `genres` is
  // the name the drawer and the API already use.
  filters.genres = asList([
    ...params.getAll('genres'),
    ...params.getAll('tags')
  ]);
  filters.exclude_genres = asList(params.getAll('exclude_genres'));

  const formats = asList([...params.getAll('format'), ...params.getAll('format_type')]);
  filters.format_type = formats.length === 0 ? null : formats.length === 1 ? formats[0] : formats;

  filters.min_year = clampInt(params.get('min_year'), 1900, 2100);
  filters.max_year = clampInt(params.get('max_year'), 1900, 2100);
  if (filters.min_year && filters.max_year && filters.min_year > filters.max_year) {
    filters.min_year = null;
    filters.max_year = null;
  }

  filters.min_score = clampInt(params.get('min_score'), 0, 100) ?? 0;
  // 1 is the smallest real bound; 0 in an old URL means "unset".
  filters.min_chapters = clampInt(params.get('min_chapters'), 1, 10000);
  filters.max_chapters = clampInt(params.get('max_chapters'), 1, 10000);
  if (
    filters.min_chapters !== null &&
    filters.max_chapters !== null &&
    filters.min_chapters > filters.max_chapters
  ) {
    filters.min_chapters = null;
    filters.max_chapters = null;
  }
  filters.min_match_pct = clampFloat(params.get('min_match_pct'), 0, 1) ?? 0;

  const rawSort = params.get('sort');
  const sort = SORT_IDS.includes(rawSort) ? rawSort : 'default';
  const page = clampInt(params.get('page'), 1, 100) ?? 1;
  const q = asText(params.get('q')).slice(0, MAX_QUERY_LENGTH);

  return { tab: getTabFromPath(pathname), q, filters, sort, page };
}

const appendList = (params, key, value) => {
  const items = asList(value);
  if (items.length > 0) params.set(key, items.join(','));
};

/** The canonical URL for a route, defaults omitted. */
export function serializeRoute({ tab = 'explore', q = '', filters = INITIAL_FILTERS, sort = 'default', page = 1 } = {}) {
  const params = new URLSearchParams();
  // An unknown tab has no path of its own; the canonical one is Explore.
  const cleanTab = VALID_TABS.includes(tab) ? tab : 'explore';
  const cleanQuery = asText(q).slice(0, MAX_QUERY_LENGTH);
  if (cleanQuery) params.set('q', cleanQuery);

  appendList(params, 'genres', filters.genres);
  appendList(params, 'exclude_genres', filters.exclude_genres);
  appendList(params, 'status', filters.status);
  appendList(params, 'format', filters.format_type);

  if (filters.min_year) params.set('min_year', String(filters.min_year));
  if (filters.max_year) params.set('max_year', String(filters.max_year));
  if (filters.min_score > 0) params.set('min_score', String(filters.min_score));
  if (filters.min_chapters > 0) params.set('min_chapters', String(filters.min_chapters));
  if (filters.max_chapters > 0) params.set('max_chapters', String(filters.max_chapters));
  if (filters.min_match_pct > 0) params.set('min_match_pct', String(filters.min_match_pct));

  const cleanSort = SORT_IDS.includes(sort) ? sort : 'default';
  if (cleanSort !== 'default') params.set('sort', cleanSort);

  const cleanPage = clampInt(page, 1, 100) ?? 1;
  if (cleanPage > 1) params.set('page', String(cleanPage));

  const query = params.toString();
  return tabToPath(cleanTab) + (query ? `?${query}` : '');
}

/** Same route, minus the page: every criteria change starts a new result set. */
export const withoutPage = (route) => ({ ...route, page: 1 });
