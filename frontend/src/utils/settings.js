// FE-22: settings come from localStorage, which the user (or another tab, or a
// half-finished write) can put anything into. They are then sent to the API as
// request parameters, so an out-of-range `limit` was a client-side 422 generator:
// the JSON parse was guarded but the values never were.
//
// This normalises once, and the request sites clamp again. The server bounds
// limit too (API-04), so this is defence in depth rather than the only guard.

export const DEFAULT_SETTINGS = {
  // 'washi' (paper) | 'amoled'. Dark Ink was removed: the paper theme is the
  // default now, so a blob that still says 'sumi' normalises back to it.
  theme: 'washi',
  fontStyle: 'serif', // 'serif' | 'sans' | 'mono' | 'display'
  gridSize: 'standard',
  // Rose is the site accent. The palette picker is gone, so both values are fixed
  // here: a blob written by an older build (accent: 'gold') normalises back to rose
  // instead of leaving one user on a colour the UI can no longer change.
  hoverAccent: 'rose',
  accent: 'rose',
  allowNsfw: false, // Global 18+ content permission
  nsfwBlur: true, // Mature/NSFW cover blur safety toggle
  surpriseImageLength: 60 // Surprise card image length % (30-100)
};

// Every enum the UI can render. A value outside them falls back to the default,
// so the CSS attributes and the card maps never receive an unknown key.
const ENUMS = {
  theme: ['washi', 'amoled'],
  fontStyle: ['serif', 'sans', 'mono', 'display'],
  gridSize: ['compact', 'standard', 'large'],
  // `accent`/`hoverAccent` are deliberately absent: they are single values now, so
  // normalizeSettings ignores whatever an old blob stored and keeps the default.
};

// The API's own bounds (app/models.py). The surprise image length is the only
// numeric preference left: the page size is `PAGE_SIZE`, not a setting.
export const SETTINGS_RANGES = {
  surpriseImageLength: { min: 30, max: 100 }
};

// One page per Load More click, in one place. This used to be two settings
// (`limit` and `batchSize`) plus a three-button chooser in the modal: two knobs
// for one question, "how fast do I see more?", and up to four variants of every
// trending cache key. The number is fixed here; the server still bounds what it
// will build (`trending.MAX_PAGE_LIMIT` = 48).
export const PAGE_SIZE = 12;

const BOOLEANS = ['allowNsfw', 'nsfwBlur'];

export function clampNumber(value, { min, max }, fallback) {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}


export function normalizeSettings(raw) {
  const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const next = { ...DEFAULT_SETTINGS };

  for (const field of Object.keys(ENUMS)) {
    if (typeof source[field] === 'string' && ENUMS[field].includes(source[field])) {
      next[field] = source[field];
    }
  }

  for (const field of Object.keys(SETTINGS_RANGES)) {
    next[field] = clampNumber(source[field], SETTINGS_RANGES[field], DEFAULT_SETTINGS[field]);
  }

  for (const field of BOOLEANS) {
    next[field] = typeof source[field] === 'boolean' ? source[field] : DEFAULT_SETTINGS[field];
  }

  return next;
}
