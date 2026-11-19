import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useSimilar from '@/hooks/useSimilar';

const rows = (from, count) =>
  Array.from({ length: count }, (_, i) => ({ id: from + i, title: `Similar ${from + i}` }));

const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useSimilar (You Might Also Like pages)', () => {
  it('loads page 1 and believes the server about has_more', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 12), has_more: true }));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useSimilar({ mangaId: 7, requestLimit: 12 }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.mangas).toHaveLength(12);
    expect(result.current.hasMore).toBe(true);
    expect(result.current.searched).toBe(true);
    expect(fetchMock.mock.calls[0][0]).toContain('/manga/7/similar/pages');
    expect(fetchMock.mock.calls[0][0]).toContain('limit=12');
    expect(fetchMock.mock.calls[0][0]).toContain('page=1');
  });

  it('appends page 2, drops boundary duplicates and stops at the end', async () => {
    const fetchMock = vi.fn((url) => {
      const page = Number(new URL(url, 'http://x').searchParams.get('page'));
      if (page === 1) return ok({ results: rows(1, 12), has_more: true });
      // The live ANN can overlap one row across a page boundary.
      return ok({ results: [...rows(12, 2), ...rows(14, 4)], has_more: false });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useSimilar({ mangaId: 7, requestLimit: 12 }));
    await waitFor(() => expect(result.current.hasMore).toBe(true));

    await act(async () => {
      await result.current.loadMore();
    });

    const ids = result.current.mangas.map(item => item.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toHaveLength(17);
    expect(result.current.hasMore).toBe(false);
    expect(await result.current.loadMore()).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps the loaded rows when a later page fails, and retry re-requests it', async () => {
    let failPage2 = true;
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        const page = Number(new URL(url, 'http://x').searchParams.get('page'));
        if (page === 2 && failPage2) {
          failPage2 = false;
          return Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) });
        }
        return page === 1
          ? ok({ results: rows(1, 12), has_more: true })
          : ok({ results: rows(13, 3), has_more: false });
      })
    );

    const { result } = renderHook(() => useSimilar({ mangaId: 7, requestLimit: 12 }));
    await waitFor(() => expect(result.current.hasMore).toBe(true));

    await act(async () => {
      await result.current.loadMore();
    });
    expect(result.current.error).toBeTruthy();
    expect(result.current.mangas).toHaveLength(12);

    await act(async () => {
      await result.current.retry();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.mangas).toHaveLength(15);
  });

  it('ignores a stale response after the id changes', async () => {
    const resolvers = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolvers.push(() => resolve(ok({ results: rows(1, 2), has_more: false })));
          })
      )
    );

    const { result, rerender } = renderHook(({ id }) => useSimilar({ mangaId: id, requestLimit: 12 }), {
      initialProps: { id: 1 }
    });

    rerender({ id: 2 });
    await act(async () => {
      // Resolve the first request last: it belongs to id 1 and must not write.
      resolvers[0]();
      resolvers[1]();
      await Promise.resolve();
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.mangas).toHaveLength(2);
  });
});
