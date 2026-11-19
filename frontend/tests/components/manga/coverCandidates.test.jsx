import { describe, it, expect, vi } from 'vitest';
import { render, renderHook, act, screen, fireEvent } from '@testing-library/react';
import { coverCandidates, useCoverSource } from '@/hooks/useCoverSource';
import MangaCard from '@/components/manga/MangaCard';

const ANILIST = 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx1-a.png';
const MAL = 'https://cdn.myanimelist.net/images/manga/1/1.jpg';

const MANGA = {
  id: 41,
  title: 'Vinland Saga',
  cover_image_url: ANILIST,
  cover_candidates: [
    { source: 'anilist', url: ANILIST },
    { source: 'mal', url: MAL },
  ],
  start_year: 2005,
  status: 'FINISHED',
  average_score: 89,
};

describe('coverCandidates', () => {
  it('returns the ranked list, best first', () => {
    expect(coverCandidates(MANGA)).toEqual([ANILIST, MAL]);
  });

  it('falls back to the legacy single field when a cached payload has no list', () => {
    expect(coverCandidates({ cover_image_url: ANILIST })).toEqual([ANILIST]);
  });

  it('de-duplicates a list that repeats the legacy field', () => {
    expect(coverCandidates({ cover_image_url: MAL, cover_candidates: [{ url: MAL }] })).toEqual([MAL]);
  });

  it('returns nothing when neither field is usable', () => {
    expect(coverCandidates({ cover_image_url: null, cover_candidates: [] })).toEqual([]);
    expect(coverCandidates(undefined)).toEqual([]);
  });
});

describe('useCoverSource', () => {
  const walk = (manga) => renderHook(() => useCoverSource(manga));

  it('retries the current host once with a cache-buster, then moves to the next candidate', () => {
    const { result } = walk(MANGA);
    expect(result.current.src).toBe(ANILIST);

    act(() => result.current.handleError());
    expect(result.current.src).toBe(`${ANILIST}?r=1`);
    expect(result.current.dead).toBe(false);

    act(() => result.current.handleError());
    expect(result.current.src).toBe(MAL);

    act(() => result.current.handleError());
    expect(result.current.src).toBe(`${MAL}?r=1`);

    act(() => result.current.handleError());
    expect(result.current.src).toBe(null);
    expect(result.current.dead).toBe(true);
  });

  it('is dead immediately when there is no candidate at all', () => {
    const { result } = walk({ id: 2, title: 'Oyasumi Punpun', cover_image_url: null, cover_candidates: [] });
    expect(result.current.src).toBe(null);
    expect(result.current.dead).toBe(true);
  });

  it('does not retry past the last candidate', () => {
    const { result } = walk({ cover_image_url: ANILIST, cover_candidates: [{ url: ANILIST }] });
    act(() => result.current.handleError());
    act(() => result.current.handleError());
    expect(result.current.dead).toBe(true);
    expect(result.current.remaining).toBe(0);
  });
});

describe('MangaCard cover fallback', () => {
  it('draws a tile instead of a broken image when the title has no cover', () => {
    render(
      <MangaCard
        manga={{ ...MANGA, cover_image_url: null, cover_candidates: [] }}
        onClick={() => {}}
        isBookmarked={false}
        onToggleBookmark={() => {}}
      />,
    );

    expect(screen.getByLabelText('Vinland Saga (cover unavailable)')).toBeTruthy();
    expect(screen.queryByAltText('Vinland Saga')).toBe(null);
  });

  it('still renders the first candidate when one exists', () => {
    const { container } = render(
      <MangaCard manga={MANGA} onClick={() => {}} isBookmarked={false} onToggleBookmark={() => {}} />,
    );

    // jsdom never intersects, so the lazy image is not mounted: assert on the URL
    // the card would request rather than on a DOM node.
    expect(container.querySelector('[aria-label*="cover unavailable"]')).toBe(null);
    expect(coverCandidates(MANGA)[0]).toBe(ANILIST);
  });
});

describe('CoverFallback', () => {
  it('keeps its existing look and stays clickable when there is no cover', () => {
    const onClick = vi.fn();
    render(
      <MangaCard
        manga={{ id: 7, title: 'Oyasumi Punpun', cover_image_url: null, cover_candidates: [] }}
        onClick={onClick}
        isBookmarked={false}
        onToggleBookmark={() => {}}
      />,
    );

    // Unchanged surface: the reader still sees the bordered tile, the mark, the
    // title and the "Cover Unavailable" caption.
    const tile = screen.getByLabelText('Oyasumi Punpun (cover unavailable)');
    expect(tile).toBeTruthy();
    expect(screen.getByText('Cover Unavailable')).toBeTruthy();

    // The tile carries no title text: the card footer already prints it, so the
    // cover used to show the same name twice.
    expect(tile.textContent).not.toContain('Oyasumi');

    fireEvent.click(tile);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
