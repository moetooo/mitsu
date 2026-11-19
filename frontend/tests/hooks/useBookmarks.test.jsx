import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useBookmarks from '@/hooks/useBookmarks';
import { MAX_BOOKMARKS } from '@/utils/bookmarks';

const manga = (id, title = `Title ${id}`) => ({
  id,
  title,
  cover_image_url: `https://example.invalid/${id}.jpg`,
  average_score: 80,
});

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('useBookmarks (FE-29 extraction of FE-18)', () => {
  it('adds, projects and removes a title', () => {
    const { result } = renderHook(() => useBookmarks());

    act(() => result.current.toggleBookmark(manga(1)));
    expect(result.current.bookmarks).toHaveLength(1);
    expect(result.current.isBookmarked(1)).toBe(true);
    expect(JSON.parse(localStorage.getItem('mitsu_bookmarks'))).toHaveLength(1);

    act(() => result.current.toggleBookmark(manga(1)));
    expect(result.current.bookmarks).toHaveLength(0);
    expect(result.current.isBookmarked(1)).toBe(false);
  });

  it('caps a hand-edited blob on the way in', () => {
    const oversized = Array.from({ length: MAX_BOOKMARKS + 25 }, (_, i) => manga(i + 1));
    localStorage.setItem('mitsu_bookmarks', JSON.stringify(oversized));

    const { result } = renderHook(() => useBookmarks());

    expect(result.current.bookmarks.length).toBeLessThanOrEqual(MAX_BOOKMARKS);
  });

  it('ignores a blob that is not an array', () => {
    localStorage.setItem('mitsu_bookmarks', JSON.stringify({ nope: true }));

    const { result } = renderHook(() => useBookmarks());

    expect(result.current.bookmarks).toEqual([]);
  });

  it('clears every saved title', () => {
    const { result } = renderHook(() => useBookmarks());

    act(() => result.current.toggleBookmark(manga(1)));
    act(() => result.current.toggleBookmark(manga(2)));
    act(() => result.current.clearBookmarks());

    expect(result.current.bookmarks).toEqual([]);
  });

  it('survives a storage quota failure', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    const { result } = renderHook(() => useBookmarks());

    expect(() => {
      act(() => result.current.toggleBookmark(manga(3)));
    }).not.toThrow();
    expect(result.current.isBookmarked(3)).toBe(true);
  });
});
