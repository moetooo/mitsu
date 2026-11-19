import { useMemo } from 'react';

// Filter state lives in one shape and one summary.
//
// The same three questions were answered in three places with three different
// field lists: App's `hasActiveFilters`, App's `activeFilterCount`, and the
// drawer's own per-category counts. The drawer now edits a draft and stages it
// behind an Apply button, so it needs the same count the badge shows; rather
// than adding a fourth list, the count comes from here.

export const INITIAL_FILTERS = {
  status: [],
  min_year: null,
  max_year: null,
  min_score: 0,
  min_chapters: null,
  max_chapters: null,
  min_match_pct: 0,
  genres: [],
  exclude_genres: [],
  format_type: null
};

const length = value => (Array.isArray(value) ? value.length : 0);

/**
 * @returns {{ active: boolean, count: number }} `count` is the number of filter
 * values set (a status pill counts one, three included genres count three), which
 * is what the badge on the search field has always shown.
 */
export function summarizeFilters(filters) {
  const f = filters || {};
  const count =
    length(f.status) +
    (f.min_year ? 1 : 0) +
    (f.max_year ? 1 : 0) +
    (f.min_score > 0 ? 1 : 0) +
    (f.min_chapters || f.max_chapters ? 1 : 0) +
    (f.min_match_pct > 0 ? 1 : 0) +
    length(f.genres) +
    length(f.exclude_genres) +
    (f.format_type ? 1 : 0);

  return { active: count > 0, count };
}

/** Formats arrive as null | string | string[] depending on the age of the value. */
export function normalizeFormats(value) {
  if (Array.isArray(value)) return value;
  return value ? [value] : [];
}

/**
 * The removable chips in the drawer footer: one per staged value, each carrying
 * the updater that clears just that value. Reset and Apply stay the only two
 * whole-set operations.
 */
export function useStagedChips(draft, setDraft) {
  return useMemo(() => {
    const chips = [];
    const clear = updater => () => setDraft(prev => updater(prev));

    (draft.status || []).forEach(status =>
      chips.push({
        key: `status:${status}`,
        label: status,
        onRemove: clear(prev => ({ ...prev, status: (prev.status || []).filter(s => s !== status) }))
      })
    );

    normalizeFormats(draft.format_type).forEach(format =>
      chips.push({
        key: `format:${format}`,
        label: format,
        onRemove: clear(prev => {
          const next = normalizeFormats(prev.format_type).filter(f => f !== format);
          return { ...prev, format_type: next.length > 0 ? next : null };
        })
      })
    );

    if (draft.max_chapters) {
      chips.push({
        key: 'chapters',
        label: `≤ ${draft.max_chapters} ch`,
        onRemove: clear(prev => ({ ...prev, min_chapters: null, max_chapters: null }))
      });
    }

    if (draft.min_year || draft.max_year) {
      chips.push({
        key: 'years',
        label: `${draft.min_year || 1970}–${draft.max_year || 2026}`,
        onRemove: clear(prev => ({ ...prev, min_year: null, max_year: null }))
      });
    }

    (draft.genres || []).forEach(genre =>
      chips.push({
        key: `include:${genre}`,
        label: `#${genre}`,
        onRemove: clear(prev => ({ ...prev, genres: (prev.genres || []).filter(g => g !== genre) }))
      })
    );

    (draft.exclude_genres || []).forEach(genre =>
      chips.push({
        key: `exclude:${genre}`,
        label: `not #${genre}`,
        muted: true,
        onRemove: clear(prev => ({
          ...prev,
          exclude_genres: (prev.exclude_genres || []).filter(g => g !== genre)
        }))
      })
    );

    return chips;
  }, [draft, setDraft]);
}
