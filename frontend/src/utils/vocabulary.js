// FE-23: one client vocabulary, served by the backend.
//
// Hand-copied lists lived in the UI (the filter drawer's categories, and the
// trending pills that have since been deleted) while the server kept the real
// taxonomy in `app/enrichment/vocabulary.py`. They drifted: the pills offered
// "Yaoi" and "Yuri", which are synonyms the catalogue does not store as genres.
//
// `GET /vocabulary` is the source. The frozen list below is a *fallback* for the
// failure case only (offline, older backend): it keeps the drawer usable instead
// of empty, and it is deliberately short and stable so it cannot become a fourth
// taxonomy.

import { API_ROUTES } from '../config';
import { readJSON, writeJSON } from './storage';

const CACHE_KEY = 'mitsu_vocabulary';

// A cached list can go stale in two ways: the taxonomy changes, or an option is
// re-flagged `filterable: false` because the catalogue stopped backing it. The
// version is only known *after* asking the server, so a cache entry with no
// fetch time cannot be checked at all - which is how a browser kept offering
// ten dead tags long after the server stopped offering them. Entries are now
// time-boxed, and an entry written by the previous shape (no `fetchedAt`) is
// treated as stale, so the fix reaches the browsers that already cached it.
const CACHE_MAX_AGE_MS = 12 * 60 * 60 * 1000;

// Taglines are presentation, not taxonomy, so they live here keyed by the
// server's category id.
const TAGLINES = {
  genre: 'Story Archetypes',
  demographic: 'Target Demographics',
  relationship: 'Romance • BL • GL',
  theme: 'Themes & Settings',
  setting: 'World & Setting',
  trope: 'Story Tropes'
};

export const FALLBACK_GROUPS = [
  {
    id: 'genre',
    name: 'Core Genres',
    tagline: TAGLINES.genre,
    options: [
      'Action', 'Adventure', 'Comedy', 'Drama', 'Fantasy', 'Horror', 'Mystery',
      'Psychological', 'Romance', 'Sci-Fi', 'Slice of Life', 'Supernatural',
      'Thriller', 'Tragedy'
    ]
  },
  {
    id: 'demographic',
    name: 'Demographics',
    tagline: TAGLINES.demographic,
    options: ['Shounen', 'Shoujo', 'Seinen', 'Josei']
  },
  {
    id: 'relationship',
    name: 'Romance & Relationships',
    tagline: TAGLINES.relationship,
    options: ["Boys' Love", "Girls' Love", 'Romance']
  }
];

export const FALLBACK_FORMATS = [
  { slug: 'manga', value: 'Manga', label: 'Manga', filterable: true },
  { slug: 'manhwa', value: 'Manhwa', label: 'Manhwa', filterable: true },
  { slug: 'manhua', value: 'Manhua', label: 'Manhua', filterable: true }
];

// Server shape -> the shape the drawer renders. Kept here so there is exactly one
// translation and the components never learn the wire format.
export function toGroups(categories) {
  if (!Array.isArray(categories)) return [];
  return categories
    .map(group => {
      if (!group || !Array.isArray(group.options)) return null;
      // Same rule the formats get: an option the catalogue cannot answer
      // (`filterable: false`) is not offered, because the pill would only ever
      // produce an empty shelf. The server decides, the drawer just obeys.
      const options = group.options
        .filter(option => option && option.filterable !== false)
        .map(option => option.value)
        .filter(Boolean);
      return { id: group.id, name: group.label || group.id, options };
    })
    .filter(group => group && group.options.length > 0)
    .map(group => ({
      ...group,
      tagline: TAGLINES[group.id] || group.name
    }));
}

export function toFormats(formats) {
  if (!Array.isArray(formats)) return [];
  return formats.filter(format => format && format.filterable !== false && format.value);
}

export function normalizeVocabulary(body) {
  const groups = toGroups(body && body.categories);
  const formats = toFormats(body && body.formats);
  return {
    version: body && body.version ? body.version : 1,
    groups: groups.length > 0 ? groups : FALLBACK_GROUPS,
    formats: formats.length > 0 ? formats : FALLBACK_FORMATS,
    fromServer: groups.length > 0
  };
}

let inflight = null;

// A cache entry is a first paint, not the final word: it is used only while it
// is young enough that the served taxonomy has probably not moved.
function freshCache() {
  const cached = readJSON(CACHE_KEY, null);
  if (!cached || !cached.version || !Array.isArray(cached.groups)) return null;
  if (typeof cached.fetchedAt !== 'number') return null;
  if (Date.now() - cached.fetchedAt > CACHE_MAX_AGE_MS) return null;
  return cached;
}

// Fetches once per session, and reuses the cached list only while it is fresh.
// On success the answer is written back with the time it was fetched, so the
// next session knows how old it is instead of trusting it forever.
export async function loadVocabulary() {
  const cached = freshCache();
  if (cached) {
    return { ...cached, fromServer: true };
  }

  if (inflight) return inflight;

  inflight = (async () => {
    try {
      const res = await fetch(API_ROUTES.vocabulary);
      if (!res.ok) throw new Error(`vocabulary request failed: ${res.status}`);
      const body = await res.json();
      const vocabulary = normalizeVocabulary(body);
      if (vocabulary.fromServer) {
        writeJSON(CACHE_KEY, {
          version: vocabulary.version,
          groups: vocabulary.groups,
          formats: vocabulary.formats,
          fetchedAt: Date.now()
        });
      }
      return vocabulary;
    } catch (error) {
      // Fallback, not a silent lie: the caller keeps a usable drawer and the
      // reason is visible in the console.
      console.warn('Vocabulary unavailable, using the built-in list:', error && error.message);
      return normalizeVocabulary(null);
    } finally {
      inflight = null;
    }
  })();

  return inflight;
}

export function resetVocabularyCache() {
  inflight = null;
}
