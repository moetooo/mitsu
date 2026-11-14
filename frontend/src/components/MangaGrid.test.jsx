import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import MangaGrid from './MangaGrid';

const ITEMS = [
  { id: 1, title: 'One', cover_image_url: null, average_score: 7.2, start_year: 2010, genres: [], tags: [] },
  { id: 2, title: 'Two', cover_image_url: null, average_score: 8.4, start_year: 2015, genres: [], tags: [] }
];

describe('MangaGrid sort pills (FE-30)', () => {
  it('reports the active sort with aria-pressed', () => {
    render(<MangaGrid mangas={ITEMS} hasSearched onCardClick={vi.fn()} onToggleBookmark={vi.fn()} />);

    const group = screen.getByRole('group', { name: 'Sort results' });
    const best = within(group).getByRole('button', { name: 'Best Match' });
    const rating = within(group).getByRole('button', { name: 'Highest Rating' });

    expect(best).toHaveAttribute('aria-pressed', 'true');
    expect(rating).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(rating);

    expect(within(group).getByRole('button', { name: 'Highest Rating' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(group).getByRole('button', { name: 'Best Match' })).toHaveAttribute('aria-pressed', 'false');
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
