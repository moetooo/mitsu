import { describe, it, expect } from 'vitest';
import { INITIAL_FILTERS, summarizeFilters } from '@/utils/filters';

// The summary replaced three hand-written field lists (App's `hasActiveFilters`,
// App's `activeFilterCount`, and the drawer's per-category counters). The point of
// the test is that both answers move together and match the badge the user sees.
describe('summarizeFilters', () => {
  it('reports nothing for the empty filter set', () => {
    expect(summarizeFilters(INITIAL_FILTERS)).toEqual({ active: false, count: 0 });
    expect(summarizeFilters(undefined)).toEqual({ active: false, count: 0 });
  });

  it('counts one per set value, not one per field group', () => {
    const summary = summarizeFilters({
      ...INITIAL_FILTERS,
      status: ['FINISHED', 'RELEASING'],
      genres: ['Action', 'Drama'],
      exclude_genres: ['Horror'],
      format_type: 'Manhwa'
    });

    // 2 status + 2 genres + 1 excluded + 1 format
    expect(summary).toEqual({ active: true, count: 6 });
  });

  it('treats a chapter or year bound as one filter each, however it is written', () => {
    expect(summarizeFilters({ ...INITIAL_FILTERS, max_chapters: 50 }).count).toBe(1);
    expect(summarizeFilters({ ...INITIAL_FILTERS, min_chapters: 5, max_chapters: 50 }).count).toBe(1);
    expect(summarizeFilters({ ...INITIAL_FILTERS, min_year: 1990 }).count).toBe(1);
    expect(summarizeFilters({ ...INITIAL_FILTERS, max_year: 2020 }).count).toBe(1);
  });

  it('ignores zero-valued numeric filters, which are the "off" state', () => {
    expect(summarizeFilters({ ...INITIAL_FILTERS, min_score: 0, min_match_pct: 0 })).toEqual({
      active: false,
      count: 0
    });
    expect(summarizeFilters({ ...INITIAL_FILTERS, min_score: 70 }).count).toBe(1);
  });
});
