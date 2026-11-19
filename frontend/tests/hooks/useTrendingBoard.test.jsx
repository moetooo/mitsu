import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useTrendingBoard, { BOARD_SIZE } from '@/hooks/useTrendingBoard';

const rows = (from, count) =>
  Array.from({ length: count }, (_, i) => ({ id: from + i, title: `Title ${from + i}` }));

const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

const formatOf = (url) => new URL(String(url), 'http://x').searchParams.get('format_type');

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useTrendingBoard (the Explore rail)', () => {
  it('fetches the top ten of the selected format, page 1 only', async () => {
    const fetchMock = vi.fn(() => ok(rows(1, 10)));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useTrendingBoard({ format: 'manhwa' }));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain('format_type=manhwa');
    expect(url).toContain('limit=10');
    expect(url).toContain('page=1');
    expect(result.current.rows).toHaveLength(BOARD_SIZE);
  });

  it('serves a format it already fetched from the local cache', async () => {
    const fetchMock = vi.fn(url => ok(rows(formatOf(url) === 'manga' ? 1 : 101, 10)));
    vi.stubGlobal('fetch', fetchMock);

    const { result, rerender } = renderHook(({ format }) => useTrendingBoard({ format }), {
      initialProps: { format: 'manga' }
    });
    await waitFor(() => expect(result.current.rows[0]?.id).toBe(1));

    rerender({ format: 'manhwa' });
    await waitFor(() => expect(result.current.rows[0]?.id).toBe(101));

    // Back to Manga: no third request, and no skeleton flash.
    rerender({ format: 'manga' });
    expect(result.current.rows[0]?.id).toBe(1);
    expect(result.current.loading).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('ignores a slow response the toggle has already superseded', async () => {
    const resolvers = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(
        url =>
          new Promise(resolve => {
            resolvers.push({ format: formatOf(url), resolve });
          })
      )
    );

    const { result, rerender } = renderHook(({ format }) => useTrendingBoard({ format }), {
      initialProps: { format: 'manga' }
    });
    await act(async () => {});

    rerender({ format: 'manhua' });
    await act(async () => {});

    resolvers.filter(entry => entry.format === 'manhua').forEach(entry =>
      entry.resolve({ ok: true, status: 200, json: () => Promise.resolve(rows(201, 10)) })
    );
    await act(async () => {});
    resolvers.filter(entry => entry.format === 'manga').forEach(entry =>
      entry.resolve({ ok: true, status: 200, json: () => Promise.resolve(rows(1, 10)) })
    );
    await act(async () => {});

    expect(result.current.rows[0].id).toBe(201);
  });

  it('fails silently, and retries the same format on a later selection', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: () => Promise.resolve(null) })
      .mockResolvedValue(ok(rows(1, 10)));
    vi.stubGlobal('fetch', fetchMock);

    const { result, rerender } = renderHook(({ format }) => useTrendingBoard({ format }), {
      initialProps: { format: 'manga' }
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    // No error banner and no rows: the section just has nothing to show.
    expect(result.current.rows).toEqual([]);

    rerender({ format: 'manhwa' });
    await waitFor(() => expect(result.current.rows).toHaveLength(10));
    rerender({ format: 'manga' });
    await waitFor(() => expect(result.current.rows).toHaveLength(10));
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('does not fetch while a result set is on screen', async () => {
    const fetchMock = vi.fn(() => ok(rows(1, 10)));
    vi.stubGlobal('fetch', fetchMock);

    renderHook(() => useTrendingBoard({ active: false }));
    await act(async () => {});

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
