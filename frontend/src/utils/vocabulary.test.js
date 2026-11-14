import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  normalizeVocabulary,
  toGroups,
  toFormats,
  loadVocabulary,
  resetVocabularyCache,
  FALLBACK_GROUPS,
  FALLBACK_FORMATS
} from './vocabulary';

// FE-23: three hand-copied option lists vs the real taxonomy on the server.
// These tests pin the client to the served list and the fallback to a fallback.

const SERVED = {
  version: 3,
  categories: [
    {
      id: 'genre',
      label: 'Core Genres',
      options: [
        { slug: 'action', value: 'Action', label: 'Action' },
        { slug: 'sci_fi', value: 'Sci-Fi', label: 'Sci-Fi' }
      ]
    },
    {
      id: 'relationship',
      label: 'Romance & Relationships',
      options: [{ slug: 'boys_love', value: "Boys' Love", label: "Boys' Love" }]
    }
  ],
  formats: [
    { slug: 'manga', value: 'Manga', label: 'Manga', filterable: true },
    { slug: 'webtoon', value: 'Webtoon', label: 'Webtoon', filterable: false }
  ]
};

beforeEach(() => {
  localStorage.clear();
  resetVocabularyCache();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('normalizeVocabulary', () => {
  it('keeps the served groups and their values', () => {
    const vocabulary = normalizeVocabulary(SERVED);
    expect(vocabulary.fromServer).toBe(true);
    expect(vocabulary.version).toBe(3);
    expect(vocabulary.groups[0]).toEqual({
      id: 'genre',
      name: 'Core Genres',
      tagline: 'Story Archetypes',
      options: ['Action', 'Sci-Fi']
    });
    // The apostrophe survives: the catalogue matches this exact string.
    expect(vocabulary.groups[1].options).toEqual(["Boys' Love"]);
  });

  it('drops formats the catalogue cannot filter on', () => {
    const vocabulary = normalizeVocabulary(SERVED);
    expect(vocabulary.formats.map(f => f.slug)).toEqual(['manga']);
  });

  it('falls back to the built-in list for junk and adds nothing of its own', () => {
    for (const junk of [null, undefined, {}, { categories: [] }, { categories: 'nope' }]) {
      const vocabulary = normalizeVocabulary(junk);
      expect(vocabulary.fromServer).toBe(false);
      expect(vocabulary.groups).toEqual(FALLBACK_GROUPS);
      expect(vocabulary.formats).toEqual(FALLBACK_FORMATS);
    }
  });

  it('toGroups skips empty groups instead of rendering an empty section', () => {
    expect(toGroups([{ id: 'x', label: 'X', options: [] }])).toEqual([]);
    expect(toGroups('nope')).toEqual([]);
  });

  it('toFormats tolerates a missing filterable flag', () => {
    expect(toFormats([{ slug: 'manhwa', value: 'Manhwa' }])).toHaveLength(1);
    expect(toFormats([{ slug: 'x', value: 'X', filterable: false }])).toHaveLength(0);
  });
});

describe('loadVocabulary', () => {
  it('uses the endpoint once and caches the answer by version', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => SERVED });
    vi.stubGlobal('fetch', fetchMock);

    const first = await loadVocabulary();
    expect(first.fromServer).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Second call is served from the localStorage cache, not the network.
    resetVocabularyCache();
    const second = await loadVocabulary();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(second.groups[0].options).toEqual(['Action', 'Sci-Fi']);

    vi.unstubAllGlobals();
  });

  it('falls back without throwing when the request fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

    const vocabulary = await loadVocabulary();
    expect(vocabulary.fromServer).toBe(false);
    expect(vocabulary.groups).toEqual(FALLBACK_GROUPS);
    expect(warn).toHaveBeenCalled();

    vi.unstubAllGlobals();
  });

  it('falls back on a non-ok response instead of rendering an empty drawer', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));

    const vocabulary = await loadVocabulary();
    expect(vocabulary.fromServer).toBe(false);

    vi.unstubAllGlobals();
  });
});
