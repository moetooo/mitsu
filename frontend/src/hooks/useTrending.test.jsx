import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useTrending from './useTrending';

const rows = (from, count) =>
  Array.from({ length: count }, (_, i) => ({ id: from + i, title: `Title ${from + i}` }));

// The same contract App's beginRequest offers: an abortable controller plus an
// isCurrent() that goes false as soon as a newer request takes the channel.
function makeRequestGuard() {
  const channels = {};
  const beginRequest = (channel) => {
    channels[channel]?.controller.abort();
    const controller = new AbortController();
    const seq = (channels[channel]?.seq ?? 0) + 1;
    channels[channel] = { controller, seq };
    return { controller, isCurrent: () => channels[channel].seq === seq };
  };
  return beginRequest;
}

const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('useTrending (FE-29 extraction of FE-03/FE-12/FE-25/FE-31)', () => {
  it('loads page 1 and replaces the rows when the filter changes', async () => {
    const fetchMock = vi.fn(() => ok(rows(1, 12)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useTrending({ activeTab: 'trending', beginRequest }));

    await waitFor(() => expect(result.current.mangas).toHaveLength(12));
    expect(result.current.hasMore).toBe(true);
    expect(fetchMock.mock.calls[0][0]).not.toContain('format_type');

    act(() => result.current.setFormat('manhwa'));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(1));

    expect(fetchMock.mock.calls.at(-1)[0]).toContain('format_type=manhwa');
    expect(result.current.mangas).toHaveLength(12);
  });

  it('appends the next page and advances the counter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => ok(String(url).includes('page=2') ? rows(13, 12) : rows(1, 12)))
    );

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useTrending({ activeTab: 'trending', beginRequest }));
    await waitFor(() => expect(result.current.mangas).toHaveLength(12));

    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.mangas).toHaveLength(24);
    expect(result.current.page).toBe(2);
  });

  it('does not skip a page when the next page fails (FE-12)', async () => {
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn((url) => {
        calls += 1;
        if (String(url).includes('page=2')) return Promise.reject(new Error('network down'));
        return ok(rows(1, 12));
      })
    );

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useTrending({ activeTab: 'trending', beginRequest }));
    await waitFor(() => expect(result.current.mangas).toHaveLength(12));

    await act(async () => {
      await result.current.loadMore();
    });

    // The counter stayed on page 1, so a retry asks for page 2 again.
    expect(result.current.page).toBe(1);
    expect(result.current.mangas).toHaveLength(12);

    await act(async () => {
      await result.current.loadMore();
    });
    expect(calls).toBeGreaterThanOrEqual(3);
  });

  it('clears the rows and reports an error when page 1 fails (FE-25)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('boom'))));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useTrending({ activeTab: 'trending', beginRequest }));

    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.mangas).toEqual([]);
  });

  it('spends one request when the sentinel and the row callback both fire (FE-31)', async () => {
    const fetchMock = vi.fn((url) => ok(String(url).includes('page=2') ? rows(13, 12) : rows(1, 12)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useTrending({ activeTab: 'trending', beginRequest }));
    await waitFor(() => expect(result.current.mangas).toHaveLength(12));
    const before = fetchMock.mock.calls.length;

    await act(async () => {
      await Promise.all([result.current.loadMore(), result.current.loadMore()]);
    });

    expect(fetchMock.mock.calls.length - before).toBe(1);
  });

  it('ignores a superseded response (FE-03)', async () => {
    let releaseFirst;
    const firstResponse = new Promise((resolve) => {
      releaseFirst = () => resolve({ ok: true, status: 200, json: () => Promise.resolve(rows(100, 12)) });
    });

    let call = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        call += 1;
        return call === 1 ? firstResponse : ok(rows(1, 12));
      })
    );

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useTrending({ activeTab: 'trending', beginRequest }));

    // Change the filter while page 1 is still in flight, then let the stale
    // response land: it must not paint the old filter's titles.
    act(() => result.current.setFormat('manhwa'));
    await waitFor(() => expect(result.current.mangas).toHaveLength(12));
    act(() => releaseFirst());
    await act(async () => {});

    expect(result.current.mangas[0].id).toBe(1);
  });

  it('does not fetch while the tab is not visible', async () => {
    const fetchMock = vi.fn(() => ok(rows(1, 12)));
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() =>
      useTrending({ activeTab: 'explore', beginRequest: makeRequestGuard() })
    );

    await act(async () => {});

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.mangas).toEqual([]);
  });
});
