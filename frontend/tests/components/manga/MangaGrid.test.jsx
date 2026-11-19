import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import MangaGrid from '@/components/manga/MangaGrid';


const ITEMS = [
  { id: 1, title: 'One', cover_image_url: null, average_score: 7.2, start_year: 2010, genres: [], tags: [] },
  { id: 2, title: 'Two', cover_image_url: null, average_score: 8.4, start_year: 2015, genres: [], tags: [] }
];

describe('MangaGrid sort pills (FE-30)', () => {
  it('reports the active sort and asks the parent to change it', () => {
    const onSortChange = vi.fn();
    render(
      <MangaGrid
        mangas={ITEMS}
        hasSearched
        sort="default"
        queryActive
        onSortChange={onSortChange}
        onCardClick={vi.fn()}
        onToggleBookmark={vi.fn()}
      />
    );

    const group = screen.getByRole('group', { name: 'Sort results' });
    const byName = (name) => within(group).getByRole('button', { name });

    expect(byName('Default')).toHaveAttribute('aria-pressed', 'true');
    expect(byName('Relevance')).toHaveAttribute('aria-pressed', 'false');
    expect(byName('Popularity')).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(byName('Popularity'));

    // Controlled: the pill does not flip itself while the request is in flight.
    expect(onSortChange).toHaveBeenCalledWith('popularity');
    expect(byName('Default')).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('MangaGrid status regions (FE-30)', () => {
  it('announces loading as a live status instead of only drawing skeletons', () => {
    render(<MangaGrid mangas={[]} loading hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />);

    const status = screen.getByRole('status', { name: 'Loading titles' });
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  it('announces an empty result set', () => {
    render(<MangaGrid mangas={[]} hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />);

    expect(screen.getByRole('status')).toHaveTextContent('No titles found.');
  });
});

describe('MangaGrid bookmarks in a long list (B-02)', () => {
  const MANY = Array.from({ length: 37 }, (_, index) => ({
    id: index + 1,
    title: `Title ${index + 1}`,
    cover_image_url: null,
    average_score: 8,
    start_year: 2000,
    genres: [],
    tags: []
  }));

  it('repaints a row when the saved list changes, instead of holding the first render', () => {
    const props = {
      mangas: MANY,
      hasSearched: true,
      onCardClick: vi.fn(),
      onToggleBookmark: vi.fn()
    };

    const { rerender } = render(<MangaGrid {...props} bookmarks={[]} />);
    expect(screen.getAllByTitle('Save Bookmark')).toHaveLength(37);

    rerender(<MangaGrid {...props} bookmarks={[{ id: 1, title: 'Title 1' }]} />);

    // The row memo only lets a repaint through if the saved list reaches the row
    // props; the old ref-based predicate left all 37 buttons saying "Save".
    expect(screen.getAllByTitle('Remove Bookmark')).toHaveLength(1);
    expect(screen.getAllByTitle('Save Bookmark')).toHaveLength(36);
  });
});

describe('MangaGrid sort scope (FE-15)', () => {
  it('offers exactly the three sorts the API implements', () => {
    render(<MangaGrid mangas={ITEMS} hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />);

    const group = screen.getByRole('group', { name: 'Sort results' });
    expect(
      within(group).getAllByRole('button').map(button => button.textContent)
    ).toEqual(['Default', 'Relevance', 'Popularity']);
  });

  it('disables Relevance for a filter-only browse and enables it with a query', () => {
    const { rerender } = render(
      <MangaGrid mangas={ITEMS} hasSearched queryActive={false} onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />
    );
    const group = () => screen.getByRole('group', { name: 'Sort results' });

    const relevance = within(group()).getByRole('button', { name: 'Relevance' });
    expect(relevance).toBeDisabled();
    expect(relevance).toHaveAttribute('title', 'Relevance needs a search query');

    rerender(
      <MangaGrid mangas={ITEMS} hasSearched queryActive onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />
    );
    expect(within(group()).getByRole('button', { name: 'Relevance' })).not.toBeDisabled();
  });

  it('does not reorder the loaded rows on its own', () => {
    const unsorted = [
      { id: 1, title: 'Lower', cover_image_url: null, average_score: 5, start_year: 2020, genres: [], tags: [] },
      { id: 2, title: 'Higher', cover_image_url: null, average_score: 9, start_year: 2000, genres: [], tags: [] }
    ];
    render(<MangaGrid mangas={unsorted} hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />);

    // Server order is the truth: a client comparator here would disagree with
    // page 2 and make "Highest Rating" mean "highest on this page".
    const titles = screen.getAllByRole('heading', { level: 3 }).map(node => node.textContent);
    expect(titles).toEqual(['Lower', 'Higher']);
  });
});

describe('MangaGrid grid density (B-09)', () => {
  const MANY = Array.from({ length: 37 }, (_, index) => ({
    id: index + 1,
    title: `Title ${index + 1}`,
    cover_image_url: null,
    average_score: 8,
    start_year: 2000,
    genres: [],
    tags: []
  }));

  // Below 640px "standard" and "large" both resolve to a single column, so the
  // column count stays put while the gap and breakpoint classes still change.
  const narrowViewport = () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, 'innerWidth');
    Object.defineProperty(window, 'innerWidth', { value: 500, configurable: true, writable: true });
    return () => {
      if (descriptor) Object.defineProperty(window, 'innerWidth', descriptor);
    };
  };

  const rowGrid = (container) => container.querySelector('.grid');

  it('repaints the grid with the new template when the density changes at one column', () => {
    const restore = narrowViewport();
    const props = {
      mangas: MANY,
      hasSearched: true,
      onCardClick: vi.fn(),
      onToggleBookmark: vi.fn()
    };

    try {
      const { container, rerender } = render(<MangaGrid {...props} gridSize="standard" />);
      expect(rowGrid(container)).toHaveClass('gap-6');

      rerender(<MangaGrid {...props} gridSize="large" />);

      // Same column count means only the class string changes; a stale
      // `gridCols` would keep the old gap on screen.
      expect(rowGrid(container)).toHaveClass('gap-8');
      expect(rowGrid(container)).not.toHaveClass('gap-6');
    } finally {
      restore();
    }
  });
});

describe('MangaGrid keeps one scroll container (FE-33)', () => {
  const MANY = Array.from({ length: 48 }, (_, index) => ({
    id: index + 1,
    title: `Title ${index + 1}`,
    cover_image_url: null,
    average_score: 8,
    start_year: 2000,
    genres: [],
    tags: []
  }));

  it('renders a plain grid past the old 36-item virtualization threshold', () => {
    const { container } = render(
      <MangaGrid mangas={MANY} hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />
    );

    // The page is the only scroller: no nested react-window list, and all 48
    // cards are in the same grid container.
    expect(container.querySelector('[data-testid="virtual-list"]')).toBeNull();
    expect(screen.getAllByTitle('Save Bookmark')).toHaveLength(48);
  });
});

describe('empty state explains itself when filters are the cause', () => {
  it('says nothing about filters when none are on', () => {
    render(<MangaGrid mangas={[]} hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />);
    expect(screen.getByRole('status')).toHaveTextContent('No titles found.');
    expect(screen.getByRole('status')).not.toHaveTextContent(/loosen a filter/i);
  });

  it('points at the filters when they are active, because a score floor empties a page', () => {
    render(
      <MangaGrid mangas={[]} hasSearched filtersActive onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />
    );
    expect(screen.getByRole('status')).toHaveTextContent(/loosen a filter/i);
  });
});
