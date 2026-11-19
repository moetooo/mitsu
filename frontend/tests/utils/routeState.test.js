import { describe, it, expect } from 'vitest';
import { INITIAL_FILTERS } from '@/utils/filters';
import { parseRoute, serializeRoute, withoutPage, tabToPath, getTabFromPath, similarPath, parseSimilarPath } from '@/utils/routeState';

const baseFilters = () => ({ ...INITIAL_FILTERS });

describe('routeState parse/serialize (URL sync)', () => {
  it('round-trips a full explore route', () => {
    const route = {
      tab: 'explore',
      q: 'dark fantasy',
      filters: {
        ...baseFilters(),
        status: ['FINISHED'],
        genres: ['Action', 'Fantasy'],
        exclude_genres: ['Horror'],
        format_type: ['MANGA', 'ONE_SHOT'],
        min_year: 1990,
        max_year: 2024,
        min_score: 70,
        min_chapters: 10,
        max_chapters: 200,
        min_match_pct: 0.35
      },
      sort: 'relevance',
      page: 3
    };

    const url = serializeRoute(route);
    const parsed = parseRoute('/', url.split('?')[1] || '');

    expect(parsed.q).toBe('dark fantasy');
    expect(parsed.filters).toMatchObject(route.filters);
    expect(parsed.sort).toBe('relevance');
    expect(parsed.page).toBe(3);
    expect(url.startsWith('/?')).toBe(true);
  });

  it('omits defaults so an untouched page is a bare path', () => {
    expect(serializeRoute({ tab: 'explore', q: '', filters: baseFilters(), sort: 'default', page: 1 })).toBe('/');
    // There is no trending route any more: an unknown tab has no path of its own.
    expect(serializeRoute({ tab: 'trending' })).toBe('/');
  });

  it('accepts the documented `tags` alias for genres', () => {
    const parsed = parseRoute('/', '?q=x&tags=Action%2CFantasy');
    expect(parsed.filters.genres).toEqual(['Action', 'Fantasy']);
  });

  it('clamps or drops malformed values instead of forwarding them', () => {
    const parsed = parseRoute(
      '/',
      '?sort=trending&page=-3&min_score=900&min_year=2030&max_year=1990&min_match_pct=4&genres=Action'
    );

    expect(parsed.sort).toBe('default');
    expect(parsed.page).toBe(1);
    expect(parsed.filters.min_score).toBe(0);
    expect(parsed.filters.min_year).toBeNull();
    expect(parsed.filters.max_year).toBeNull();
    expect(parsed.filters.min_match_pct).toBe(0);
    // Valid siblings survive a bad sort/page.
    expect(parsed.filters.genres).toEqual(['Action']);
  });

  it('deduplicates and caps repeated list parameters', () => {
    const values = Array.from({ length: 30 }, (_, index) => `tag-${index}`).join(',');
    const parsed = parseRoute('/', `?genres=Action&genres=Action&genres=${values}`);

    expect(parsed.filters.genres[0]).toBe('Action');
    expect(parsed.filters.genres.filter(tag => tag === 'Action')).toHaveLength(1);
    expect(parsed.filters.genres.length).toBeLessThanOrEqual(20);
  });

  it('maps tabs both ways and defaults unknown paths to explore', () => {
    expect(tabToPath('explore')).toBe('/');
    expect(tabToPath('bookmarks')).toBe('/bookmarks');
    expect(getTabFromPath('/trending')).toBe('explore');
    expect(getTabFromPath('/nope')).toBe('explore');
    expect(parseRoute('/trending', '').tab).toBe('explore');
  });

  it('withoutPage keeps every other criterion', () => {
    const route = parseRoute('/', '?q=x&sort=popularity&page=4');
    expect(withoutPage(route)).toMatchObject({ q: 'x', sort: 'popularity', page: 1 });
  });
});

describe('missing numeric parameters stay missing', () => {
  it('does not turn a missing chapter bound into 0', () => {
    const route = parseRoute('/', '');
    expect(route.filters.min_chapters).toBeNull();
    expect(route.filters.max_chapters).toBeNull();
  });

  it('drops a legacy ?min_chapters=0 and does not write it back', () => {
    const route = parseRoute('/', '?min_chapters=0&max_chapters=0');
    expect(route.filters.min_chapters).toBeNull();
    expect(route.filters.max_chapters).toBeNull();
    expect(serializeRoute(route)).not.toContain('chapters');
  });

  it('keeps a real chapter bound', () => {
    const route = parseRoute('/', '?min_chapters=5&max_chapters=100');
    expect(route.filters.min_chapters).toBe(5);
    expect(route.filters.max_chapters).toBe(100);
    expect(serializeRoute(route)).toContain('min_chapters=5');
  });
});

describe('similar destination path', () => {
  it('parses only a positive integer id', () => {
    expect(parseSimilarPath('/similar/79475')).toBe(79475);
    expect(parseSimilarPath('/similar/79475/')).toBe(79475);
    expect(parseSimilarPath('/similar/0')).toBeNull();
    expect(parseSimilarPath('/similar/abc')).toBeNull();
    expect(parseSimilarPath('/similar/1/extra')).toBeNull();
    expect(parseSimilarPath('/')).toBeNull();
    expect(parseSimilarPath('')).toBeNull();
  });

  it('round-trips through similarPath', () => {
    expect(similarPath(12)).toBe('/similar/12');
    expect(parseSimilarPath(similarPath(12))).toBe(12);
  });

  it('is not a tab, so a tab path never resolves to it', () => {
    expect(getTabFromPath('/similar/12')).toBe('explore');
    expect(tabToPath('explore')).not.toContain('similar');
  });
});
