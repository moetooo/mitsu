import { useState, useMemo } from 'react';

import { FALLBACK_GROUPS } from '../../utils/vocabulary';
import { INITIAL_FILTERS, normalizeFormats, summarizeFilters, useStagedChips } from '../../utils/filters';
import { DualRange, FilterCard, Pill, Segmented, StagedChip, StopsSlider, Ticks } from './FilterControls';

const STATUSES = ['FINISHED', 'RELEASING', 'CANCELLED', 'HIATUS'];
const FORMATS = [
  { id: null, label: 'All' },
  { id: 'Manga', label: 'Manga (JP)' },
  { id: 'Manhwa', label: 'Manhwa (KR)' },
  { id: 'Manhua', label: 'Manhua (CN)' }
];
// Chapters are a ceiling on a fixed ladder: 1, 50, 100, 250, then "500+" which is
// "no ceiling at all". A free slider invited impossible precision on a value the
// backend only compares with `<=` anyway.
const CHAPTER_STOPS = [
  { label: '1', value: 1 },
  { label: '50', value: 50 },
  { label: '100', value: 100 },
  { label: '250', value: 250 },
  { label: '500+', value: null }
];
const YEARS = { min: 1970, max: 2026, step: 1 };
const YEAR_TICKS = [1970, 1985, 2000, 2015, 2026];

// Alias handling for the tag search: the vocabulary names these two groups, and
// readers search for the older shorthand.
const TAG_ALIASES = [
  { value: "boys' love", aliases: ['yaoi', 'bl'] },
  { value: "girls' love", aliases: ['yuri', 'gl'] }
];

const tagMatches = (option, query) => {
  const q = query.toLowerCase().trim();
  if (!q) return true;
  if (option.toLowerCase().includes(q)) return true;
  const alias = TAG_ALIASES.find(entry => entry.value === option.toLowerCase());
  return Boolean(alias && alias.aliases.some(alias => alias.includes(q)));
};

const readoutFor = (low, high, lowDefault, highDefault, highSuffix = '') => {
  if (low <= lowDefault && high >= highDefault) return 'ANY';
  return `${low} – ${high >= highDefault ? `${highDefault}${highSuffix}` : high}`;
};

export default function FilterDrawer({
  filters,
  setFilters,
  onApply,
  isOpen,
  onClose,
  categories = FALLBACK_GROUPS
}) {
  const [activeCategoryTab, setActiveCategoryTab] = useState('all');
  const [tagQuery, setTagQuery] = useState('');
  // Filters are staged: the drawer edits a draft and nothing reaches the results
  // until Apply. Reset clears the draft only, so Apply stays the single commit.
  const [draft, setDraft] = useState(filters);
  const [seed, setSeed] = useState({ isOpen: Boolean(isOpen), filters });

  // Opening starts a new staging session from the committed filters. Derived during
  // render rather than in an effect: with an effect, the first pill click could land
  // on a draft that was still waiting to be overwritten by the seed.
  if (Boolean(isOpen) !== seed.isOpen) {
    setSeed({ isOpen: Boolean(isOpen), filters });
    setDraft(filters);
  }

  const filterCategories = useMemo(
    () => (Array.isArray(categories) && categories.length > 0 ? categories : FALLBACK_GROUPS),
    [categories]
  );
  const allFilterOptions = useMemo(
    () => Array.from(new Set(filterCategories.flatMap(group => group.options))),
    [filterCategories]
  );
  const displayedCategories = useMemo(
    () => (activeCategoryTab === 'all' ? filterCategories : filterCategories.filter(c => c.id === activeCategoryTab)),
    [activeCategoryTab, filterCategories]
  );
  const stagedChips = useStagedChips(draft, setDraft);
  const summary = summarizeFilters(draft);

  const toggleStatus = status =>
    setDraft(prev => {
      const current = prev.status || [];
      return {
        ...prev,
        status: current.includes(status) ? current.filter(s => s !== status) : [...current, status]
      };
    });

  // Three-state tag: include → exclude → neutral. The middle state is what makes
  // "no horror" expressible without a second control.
  const cycleGenre = genre =>
    setDraft(prev => {
      const included = prev.genres || [];
      const excluded = prev.exclude_genres || [];

      if (!included.includes(genre) && !excluded.includes(genre)) {
        return { ...prev, genres: [...included, genre], exclude_genres: excluded };
      }
      if (included.includes(genre)) {
        return { ...prev, genres: included.filter(g => g !== genre), exclude_genres: [...excluded, genre] };
      }
      return {
        ...prev,
        genres: included.filter(g => g !== genre),
        exclude_genres: excluded.filter(g => g !== genre)
      };
    });

  const applyDraft = () => {
    if (onApply) onApply(draft);
    else setFilters(draft);
    onClose?.();
  };

  if (!isOpen) return null;

  const currentFormats = normalizeFormats(draft.format_type);
  // A ceiling that is not on the ladder still has to render: pick the nearest stop
  // above it so the thumb never claims a shorter cap than the one being applied.
  const chapterIndex = (() => {
    if (draft.max_chapters == null) return CHAPTER_STOPS.length - 1;
    const exact = CHAPTER_STOPS.findIndex(stop => stop.value === draft.max_chapters);
    if (exact >= 0) return exact;
    const above = CHAPTER_STOPS.findIndex(stop => stop.value != null && stop.value >= draft.max_chapters);
    return above >= 0 ? above : CHAPTER_STOPS.length - 1;
  })();
  const chapterStop = CHAPTER_STOPS[chapterIndex];
  const chapterBadge =
    chapterStop.value == null ? 'ANY' : chapterStop.value === 1 ? '1 CH' : `1 – ${chapterStop.value}`;

  const yearLow = draft.min_year || YEARS.min;
  const yearHigh = draft.max_year || YEARS.max;
  const yearBadge = readoutFor(yearLow, yearHigh, YEARS.min, YEARS.max);

  const statusBadge = (() => {
    const active = draft.status || [];
    if (active.length === 0) return 'ANY';
    if (active.length === 1) return active[0];
    return `${active.length} SELECTED`;
  })();
  const formatBadge = currentFormats.length === 0 ? 'ALL' : currentFormats[0].toUpperCase();

  return (
    <div className="bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-color)] rounded-xl shadow-2xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-color)]">
        <div className="flex items-center gap-2.5">
          <span aria-hidden="true" className="text-[var(--panel-accent)] font-heading text-sm leading-none">
            ❖
          </span>
          <h3 className="text-sm font-bold tracking-tight">Advanced Search Filters</h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="Close filters"
          aria-label="Close filters"
          className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-color)] hover:bg-[var(--bg-color)] transition-colors cursor-pointer"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="p-3.5 space-y-3">
        {/* Instrument panel: themed shell, 2x2 cards, the theme accent as the only chroma. */}
        <div
          className="rounded-xl border p-2.5"
          style={{ background: 'var(--panel-bg)', borderColor: 'var(--panel-border)' }}
        >
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            <FilterCard
              title="Status"
              badge={statusBadge}
              active={(draft.status || []).length > 0}
              onClear={draft.status?.length ? () => setDraft(prev => ({ ...prev, status: [] })) : null}
            >
              <Segmented
                ariaLabel="Publication status"
                wide
                options={STATUSES.map(status => ({ id: status, label: status }))}
                isActive={option => (draft.status || []).includes(option.id)}
                onSelect={option => toggleStatus(option.id)}
              />
            </FilterCard>

            <FilterCard
              title="Format"
              badge={formatBadge}
              active={currentFormats.length > 0}
              onClear={currentFormats.length ? () => setDraft(prev => ({ ...prev, format_type: null })) : null}
            >
              <Segmented
                ariaLabel="Format"
                wide
                options={FORMATS.map(format => ({ id: format.id, label: format.label }))}
                isActive={option =>
                  option.id === null ? currentFormats.length === 0 : currentFormats.includes(option.id)
                }
                onSelect={option => setDraft(prev => ({ ...prev, format_type: option.id }))}
              />
            </FilterCard>

            <FilterCard
              title="Chapters"
              badge={chapterBadge}
              active={draft.max_chapters != null}
              onClear={draft.max_chapters != null ? () => setDraft(prev => ({ ...prev, max_chapters: null })) : null}
            >
              <div className="flex flex-col gap-1">
                <StopsSlider
                  ariaLabel="Maximum chapters"
                  stops={CHAPTER_STOPS}
                  index={chapterIndex}
                  onChange={index =>
                    setDraft(prev => ({ ...prev, min_chapters: null, max_chapters: CHAPTER_STOPS[index].value }))
                  }
                />
                <Ticks
                  stops={CHAPTER_STOPS}
                  activeIndex={chapterIndex}
                  onPick={index =>
                    setDraft(prev => ({ ...prev, min_chapters: null, max_chapters: CHAPTER_STOPS[index].value }))
                  }
                />
              </div>
            </FilterCard>

            <FilterCard
              title="Publication Year"
              badge={yearBadge}
              active={draft.min_year != null || draft.max_year != null}
              onClear={
                draft.min_year != null || draft.max_year != null
                  ? () => setDraft(prev => ({ ...prev, min_year: null, max_year: null }))
                  : null
              }
            >
              <div className="flex flex-col gap-1">
                <DualRange
                  ariaLabel="Publication year range"
                  low={yearLow}
                  high={yearHigh}
                  min={YEARS.min}
                  max={YEARS.max}
                  step={YEARS.step}
                  lowLabel="Minimum publication year"
                  highLabel="Maximum publication year"
                  onLow={value => setDraft(prev => ({ ...prev, min_year: value <= YEARS.min ? null : value }))}
                  onHigh={value => setDraft(prev => ({ ...prev, max_year: value >= YEARS.max ? null : value }))}
                />
                <Ticks
                  stops={YEAR_TICKS.map(year => ({ label: String(year), value: year }))}
                  activeIndex={-1}
                  onPick={index => {
                    // A tick moves whichever thumb is nearer, so a click never crosses them.
                    const year = YEAR_TICKS[index];
                    const toLow = Math.abs(year - yearLow) <= Math.abs(year - yearHigh);
                    setDraft(prev =>
                      toLow
                        ? { ...prev, min_year: year <= YEARS.min ? null : Math.min(year, yearHigh) }
                        : { ...prev, max_year: year >= YEARS.max ? null : Math.max(year, yearLow) }
                    );
                  }}
                />
              </div>
            </FilterCard>
          </div>
        </div>

        {/* Categories & genres */}
        <div className="bg-[var(--bg-color)]/40 border border-[var(--border-color)] rounded-lg p-3 space-y-2.5">
          {/* Label + search row, then the tab strip: six category names plus a
              search field in one row squeezes both on a laptop width. */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-[var(--text-muted)]">
              Categories &amp; Genres
            </span>

            <div className="relative shrink-0 w-full sm:w-64">
              <svg
                className="w-3.5 h-3.5 text-[var(--text-muted)] absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35m1.85-5.15a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search genres and tags..."
                aria-label="Search genres and tags"
                value={tagQuery}
                onChange={event => setTagQuery(event.target.value)}
                className="w-full bg-[var(--surface-color)] border border-[var(--border-color)] focus:border-[var(--panel-accent)] rounded-md pl-8 pr-7 py-1 text-[11px] font-mono text-[var(--text-color)] placeholder:text-[var(--text-muted)] focus:outline-none transition-colors"
              />
              {tagQuery && (
                <button
                  type="button"
                  onClick={() => setTagQuery('')}
                  aria-label="Clear tag search"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-color)] text-xs cursor-pointer"
                >
                  ×
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center gap-1 overflow-x-auto no-scrollbar pb-1.5 border-b border-[var(--border-color)]">
            <button
              type="button"
              onClick={() => setActiveCategoryTab('all')}
              aria-pressed={activeCategoryTab === 'all'}
              className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono whitespace-nowrap transition-all cursor-pointer flex items-center gap-1 ${
                activeCategoryTab === 'all'
                  ? 'bg-[var(--text-color)] text-[var(--bg-color)] font-bold'
                  : 'bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
              }`}
            >
              All Categories
              <span className="opacity-70">({allFilterOptions.length})</span>
            </button>

            {filterCategories.map(group => {
              const activeCount =
                (draft.genres || []).filter(g => group.options.includes(g)).length +
                (draft.exclude_genres || []).filter(g => group.options.includes(g)).length;

              return (
                <button
                  key={group.id}
                  type="button"
                  onClick={() => setActiveCategoryTab(group.id)}
                  aria-pressed={activeCategoryTab === group.id}
                  className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono whitespace-nowrap transition-all cursor-pointer flex items-center gap-1 ${
                    activeCategoryTab === group.id
                      ? 'bg-[var(--panel-accent)] text-white font-bold'
                      : 'bg-[var(--surface-color)] border border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--text-color)]'
                  }`}
                >
                  {group.name}
                  {activeCount > 0 && (
                    <span className="w-3.5 h-3.5 rounded-full bg-white/20 text-[9px] font-bold flex items-center justify-center">
                      {activeCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Fixed-height viewport: all 72 tags stay reachable without stretching the drawer. */}
          <div className="max-h-56 overflow-y-auto custom-scrollbar pr-1 space-y-2.5">
            {displayedCategories.map(group => {
              const options = group.options.filter(option => tagMatches(option, tagQuery));
              if (options.length === 0) return null;

              return (
                <div key={group.id} className="space-y-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-[var(--text-color)]">
                      {group.name}
                    </span>
                    {group.tagline && (
                      <span className="text-[9px] font-mono italic text-[var(--text-muted)] opacity-70">{group.tagline}</span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {options.map(option => {
                      const included = (draft.genres || []).includes(option);
                      const excluded = (draft.exclude_genres || []).includes(option);

                      return (
                        <Pill
                          key={option}
                          active={included}
                          excluded={excluded}
                          onClick={() => cycleGenre(option)}
                          title={
                            included
                              ? 'Included (click to exclude)'
                              : excluded
                                ? 'Excluded (click to reset)'
                                : 'Click to include'
                          }
                          className="px-2 py-0.5 text-[11px] font-mono"
                        >
                          #{option}
                        </Pill>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>

          {tagQuery && !displayedCategories.some(group => group.options.some(o => tagMatches(o, tagQuery))) && (
            <p className="text-[10px] font-mono text-[var(--text-muted)]">No tags match “{tagQuery}”.</p>
          )}
        </div>
      </div>

      {/* Staged summary + commit */}
      <div className="px-3.5 py-2.5 border-t border-[var(--border-color)] bg-[var(--bg-color)]/60 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2">
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-1.5 overflow-x-auto no-scrollbar min-h-[26px]"
        >
          {stagedChips.length === 0 ? (
            <span className="text-[11px] font-mono text-[var(--text-muted)]">No filters staged</span>
          ) : (
            stagedChips.map(chip => (
              <StagedChip key={chip.key} label={chip.label} muted={chip.muted} onRemove={chip.onRemove} />
            ))
          )}
        </div>

        <div className="flex items-center justify-end gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setDraft(INITIAL_FILTERS)}
            disabled={summary.count === 0}
            className="px-3 py-1.5 rounded-lg text-[11px] font-mono text-[var(--text-muted)] hover:text-[var(--text-color)] hover:bg-[var(--surface-color)] transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-default"
          >
            Reset
          </button>
          <button
            type="button"
            onClick={applyDraft}
            className="px-4 py-1.5 rounded-full text-[11px] font-bold text-white bg-[var(--panel-accent)] hover:opacity-90 active:scale-[0.98] transition-all cursor-pointer"
            style={{ boxShadow: '0 0 20px color-mix(in srgb, var(--panel-accent) 35%, transparent)' }}
          >
            Apply Filters
          </button>
        </div>
      </div>
    </div>
  );
}
