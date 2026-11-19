import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FilterDrawer from '@/components/controls/FilterDrawer';
import { INITIAL_FILTERS } from '@/utils/filters';

// FE-23: the drawer used to own a fourth copy of the genre taxonomy. It now
// renders whatever the served vocabulary gives it, and only falls back when it
// is given nothing.

const categories = [
  {
    id: 'genre',
    name: 'Served Genres',
    tagline: 'Story Archetypes',
    options: ['Kung Fu', 'Space Opera']
  },
  {
    id: 'setting',
    name: 'Settings & World',
    tagline: 'World & Setting',
    options: ['Floating Cities']
  }
];

const renderDrawer = (props = {}) =>
  render(
    <FilterDrawer
      filters={{ genres: [], exclude_genres: [] }}
      setFilters={vi.fn()}
      isOpen
      onClose={vi.fn()}
      {...props}
    />
  );

describe('FilterDrawer vocabulary (FE-23)', () => {
  it('renders the groups it is handed, not a list of its own', () => {
    renderDrawer({ categories });

    // The name appears twice: once as the category tab, once as the section header.
    expect(screen.getAllByText('Served Genres').length).toBeGreaterThan(0);
    expect(screen.getByText('#Kung Fu')).toBeTruthy();
    expect(screen.getAllByText('Settings & World').length).toBeGreaterThan(0);
    expect(screen.getByText('#Floating Cities')).toBeTruthy();

    // Nothing the built-in fallback contains can leak into a served render.
    expect(screen.queryByText('Demographics')).toBeNull();
  });

  it('shows the served option count', () => {
    renderDrawer({ categories });
    expect(screen.getByText('(3)')).toBeTruthy();
  });

  it('falls back to the built-in list when given no groups', () => {
    renderDrawer({ categories: [] });

    expect(screen.getAllByText('Core Genres').length).toBeGreaterThan(0);
    expect(screen.getByText('#Action')).toBeTruthy();
  });

  it('stages a genre choice and only commits it on Apply', () => {
    const onApply = vi.fn();
    const setFilters = vi.fn();
    renderDrawer({ categories, onApply, setFilters });

    fireEvent.click(screen.getByText('#Kung Fu'));

    // Nothing reaches App while the drawer is open: a half-built filter set used
    // to go live behind a closed drawer on the next search.
    expect(onApply).not.toHaveBeenCalled();
    expect(setFilters).not.toHaveBeenCalled();
    expect(screen.getByRole('status')).toHaveTextContent('#Kung Fu');

    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toMatchObject({ genres: ['Kung Fu'], exclude_genres: [] });
  });

  it('cycles a tag include → exclude → neutral, the third state being "no horror"', () => {
    renderDrawer({ categories });

    const tag = screen.getByText('#Kung Fu');
    fireEvent.click(tag);
    expect(tag.closest('button').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('status')).toHaveTextContent('#Kung Fu');

    fireEvent.click(tag.closest('button'));
    expect(tag.closest('button').getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('status')).toHaveTextContent('not #Kung Fu');

    fireEvent.click(tag.closest('button'));
    expect(screen.getByRole('status')).toHaveTextContent('No filters staged');
  });
});

describe('FilterDrawer staged filters (Apply button)', () => {
  const committed = { ...INITIAL_FILTERS, status: ['FINISHED'] };

  it('seeds the draft from the committed filters when it opens', () => {
    renderDrawer({ categories, filters: committed });

    // The committed status is already on, and the footer shows it as a removable chip.
    expect(screen.getByRole('button', { name: 'FINISHED' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('status')).toHaveTextContent('FINISHED');
    expect(screen.getByRole('button', { name: /remove filter finished/i })).toBeTruthy();
  });

  it('drops one staged value from the footer chip without touching the rest', () => {
    renderDrawer({ categories, filters: { ...committed, genres: ['Kung Fu'] }, onApply: vi.fn() });

    fireEvent.click(screen.getByRole('button', { name: /remove filter finished/i }));

    expect(screen.getByRole('button', { name: 'FINISHED' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('status')).toHaveTextContent('#Kung Fu');
    expect(screen.getByRole('status')).not.toHaveTextContent('FINISHED');
  });

  it('closes the drawer after applying, so one click does both', () => {
    const onApply = vi.fn();
    const onClose = vi.fn();
    renderDrawer({ categories, onApply, onClose });

    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));

    expect(onApply).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('clears the draft on Reset without committing, so Apply stays the only commit', () => {
    const onApply = vi.fn();
    renderDrawer({ categories, filters: committed, onApply });

    expect(screen.getByRole('status')).toHaveTextContent('FINISHED');
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));

    expect(screen.getByRole('status')).toHaveTextContent('No filters staged');
    expect(onApply).not.toHaveBeenCalled();
  });

  it('stages nothing by default, so Apply on a fresh drawer is a no-op commit', () => {
    const onApply = vi.fn();
    renderDrawer({ categories, onApply });

    expect(screen.getByRole('button', { name: /apply filters/i })).toBeTruthy();
    expect(screen.getByRole('status')).toHaveTextContent('No filters staged');
  });
});

describe('chapter length is a ceiling on a fixed ladder', () => {
  it('sends only a maximum, from the stop the thumb landed on', () => {
    const onApply = vi.fn();
    renderDrawer({ categories, onApply, setFilters: vi.fn() });

    // Stop 2 of 0..4 is 100 chapters.
    fireEvent.change(screen.getByRole('slider', { name: /maximum chapters/i }), { target: { value: '2' } });

    expect(screen.getByRole('status')).toHaveTextContent('≤ 100 ch');

    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    expect(onApply.mock.calls[0][0]).toMatchObject({ max_chapters: 100, min_chapters: null });
  });

  it('reads ANY at the top stop and stages nothing', () => {
    renderDrawer({ categories, onApply: vi.fn(), setFilters: vi.fn() });

    fireEvent.change(screen.getByRole('slider', { name: /maximum chapters/i }), { target: { value: '4' } });

    expect(screen.getByRole('status')).toHaveTextContent(/no filters staged/i);
  });

  it('lets the tick row pick a stop and states the ceiling in the card badge', () => {
    renderDrawer({ categories, onApply: vi.fn(), setFilters: vi.fn() });

    fireEvent.click(screen.getByRole('button', { name: '250' }));

    expect(screen.getByText('1 – 250')).toBeTruthy();
    expect(screen.getByRole('status')).toHaveTextContent('≤ 250 ch');
  });
});

describe('instrument panel cards', () => {
  it('states a single status by name and counts multiple as N SELECTED', () => {
    renderDrawer({ categories, onApply: vi.fn(), filters: { ...INITIAL_FILTERS, status: ['FINISHED'] } });
    // A single status is named in the badge, not counted.
    expect(screen.getAllByText('FINISHED').length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByRole('button', { name: 'RELEASING' }));
    expect(screen.getByText('2 SELECTED')).toBeTruthy();
  });

  it('clears one card without touching the others', () => {
    const onApply = vi.fn();
    renderDrawer({
      categories,
      onApply,
      filters: { ...INITIAL_FILTERS, status: ['FINISHED'], max_chapters: 50 }
    });

    fireEvent.click(screen.getByRole('button', { name: /clear status/i }));

    // The segment stays visible but unlit; the staged chip is what disappears.
    expect(screen.getByRole('button', { name: 'FINISHED' }).getAttribute('aria-pressed')).toBe('false');
    expect(screen.getByRole('status')).toHaveTextContent(/^≤ 50 ch/);

    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    expect(onApply.mock.calls[0][0]).toMatchObject({ status: [], max_chapters: 50 });
  });

  it('keeps format single-select so All and a language are never both lit', () => {
    const onApply = vi.fn();
    renderDrawer({ categories, onApply, filters: { ...INITIAL_FILTERS, format_type: 'Manga' } });

    fireEvent.click(screen.getByRole('button', { name: 'Manhwa (KR)' }));
    expect(screen.getByRole('button', { name: 'Manhwa (KR)' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Manga (JP)' }).getAttribute('aria-pressed')).toBe('false');

    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(screen.getByRole('button', { name: 'All' }).getAttribute('aria-pressed')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: /apply filters/i }));
    expect(onApply.mock.calls[0][0]).toMatchObject({ format_type: null });
  });
});
