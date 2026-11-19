import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import MangaCard from '@/components/manga/MangaCard';

const CARD = {
  id: 1,
  title: 'Gachiakuta',
  cover_image_url: null,
  start_year: 2022,
  status: 'RELEASING',
  average_score: 81,
  inferred_tags: [
    { name: 'Manga', category: 'format', confidence: 0.95 },
    { name: 'Underdog', category: 'trope', confidence: 0.8 }
  ]
};

describe('MangaCard metadata', () => {
  it('shows year, status and rating but no inferred-tag chips', () => {
    render(<MangaCard manga={CARD} onClick={vi.fn()} isBookmarked={false} onToggleBookmark={vi.fn()} />);

    expect(screen.getByText('2022')).toBeTruthy();
    expect(screen.getByText(/RELEASING/)).toBeTruthy();
    expect(screen.getByText(/8\.1/)).toBeTruthy();
    // Inferred tags used to print format words like "Manga" and tropes like
    // "Underdog" on every card; they are not card metadata.
    expect(screen.queryByText('Manga')).toBeNull();
    expect(screen.queryByText('Underdog')).toBeNull();
  });
});
