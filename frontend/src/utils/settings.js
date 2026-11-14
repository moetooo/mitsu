// FE-22: settings come from localStorage, which the user (or another tab, or a
// half-finished write) can put anything into. They are then sent to the API as
// request parameters, so an out-of-range `limit` was a client-side 422 generator:
// the JSON parse was guarded but the values never were.
//
// This normalises once, and the request sites clamp again. The server bounds
// limit too (API-04), so this is defence in depth rather than the only guard.

export const DEFAULT_SETTINGS = {
  theme: 'sumi', // 'sumi' (dark ink) | 'washi' (light paper) | 'amoled'
  fontStyle: 'serif', // 'serif' | 'sans' | 'mono' | 'display'
  stampStyle: 'crest',
  gridSize: 'standard',
  limit: 12,
  batchSize: 24, // Dynamic load batch size
  focusStyle: 'glow', // 'glow' | 'vermillion' | 'subtle' | 'none'
  hoverAccent: 'vermillion', // 'vermillion' | 'gold' | 'emerald' | 'mono' | 'indigo' | 'rose'
  accent: 'vermillion',
  allowNsfw: false, // Global 18+ content permission
  nsfwBlur: true, // Mature/NSFW cover blur safety toggle
  infiniteScroll: true,
  surpriseImageLength: 60 // Surprise card image length % (30-100)
};

// Every enum the UI can render. A value outside them falls back to the default,
// so the CSS attributes and the card maps never receive an unknown key.
const ENUMS = {
  theme: ['sumi', 'washi', 'amoled'],
  fontStyle: ['serif', 'sans', 'mono', 'display'],
  stampStyle: ['crest', 'hanko'],
  gridSize: ['compact', 'standard', 'large'],
  focusStyle: ['glow', 'vermillion', 'subtle', 'none'],
  hoverAccent: ['vermillion', 'gold', 'emerald', 'mono', 'indigo', 'rose'],
  accent: ['vermillion', 'gold', 'emerald', 'mono', 'indigo', 'rose']
};

// The API's own bounds (app/models.py): recommend 1-50, roulette 1-100. The
// client asks for at most 50 so both requests stay valid with one number.
export const SETTINGS_RANGES = {
  limit: { min: 1, max: 50 },
  batchSize: { min: 1, max: 50 },
  surpriseImageLength: { min: 30, max: 100 }
};

const BOOLEANS = ['allowNsfw', 'nsfwBlur', 'infiniteScroll'];

export function clampNumber(value, { min, max }, fallback) {
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(max, Math.max(min, Math.round(number)));
}

// What the request bodies use. Anything the user's storage got wrong becomes a
// valid request instead of a 422.
export function clampLimit(value) {
  return clampNumber(value, SETTINGS_RANGES.limit, DEFAULT_SETTINGS.limit);
}

export function clampBatchSize(value) {
  return clampNumber(value, SETTINGS_RANGES.batchSize, DEFAULT_SETTINGS.batchSize);
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
