import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useSearch from './useSearch';

const rows = (from, count) =>
  Array.from({ length: count }, (_, i) => ({ id: from + i, title: `Title ${from + i}` }));

function makeRequestGuard() {
  const channels = {};
  return (channel) => {
    channels[channel]?.controller.abort();
    const controller = new AbortController();
    const seq = (channels[channel]?.seq ?? 0) + 1;
    channels[channel] = { controller, seq };
    return { controller, isCurrent: () => channels[channel].seq === seq };
  };
}

const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('useSearch (FE-29 extraction of FE-03/FE-12/FE-15/FE-25/FE-31)', () => {
  it('sends the query, the filters and the clamped limit, and stores page 1', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 12), title_suggestion: { title: 'Berserk' } }));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() =>
      useSearch({ beginRequest, requestLimit: 20, allowNsfw: true })
    );

    act(() => result.current.setQuery('dark fantasy'));
    await act(async () => {
      await result.current.search(null, null, 1, { min_score: 8 });
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.query).toBe('dark fantasy');
    expect(body.limit).toBe(20);
    expect(body.filters).toMatchObject({ min_score: 8, nsfw: true });
    expect(result.current.mangas).toHaveLength(12);
    expect(result.current.searched).toBe(true);
    expect(result.current.titleSuggestion.title).toBe('Berserk');
    expect(result.current.resultKey).toContain('dark fantasy');
  });

  it('appends page 2 without duplicates and advances the counter', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) => {
        const page = JSON.parse(opts.body).page;
        return ok({ results: page === 1 ? rows(1, 12) : [...rows(10, 2), ...rows(13, 10)] });
      })
    );

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest, requestLimit: 12 }));

    // Like the app: the box holds the query, load-more reads it from state.
    act(() => result.current.setQuery('action'));
    await act(async () => {
      await result.current.search(null, null, 1, {});
    });
    await act(async () => {
      await result.current.loadMore({});
    });

    expect(result.current.page).toBe(2);
    // The two rows already on screen are not added a second time.
    expect(result.current.mangas.filter(m => m.id === 10)).toHaveLength(1);
    expect(result.current.mangas).toHaveLength(22);
  });

  it('does not advance the counter when the next page fails (FE-12)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url, opts) =>
        JSON.parse(opts.body).page === 1 ? ok({ results: rows(1, 12) }) : Promise.reject(new Error('down'))
      )
    );

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest, requestLimit: 12 }));

    await act(async () => {
      await result.current.search(null, 'action', 1, {});
    });
    await act(async () => {
      await result.current.loadMore({});
    });

    expect(result.current.page).toBe(1);
    expect(result.current.mangas).toHaveLength(12);
  });

  it('clears the rows and reports an error when page 1 fails (FE-25)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('boom'))));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest, requestLimit: 12 }));

    await act(async () => {
      await result.current.search(null, 'action', 1, {});
    });

    expect(result.current.error).toBeTruthy();
    expect(result.current.mangas).toEqual([]);
    expect(result.current.loading).toBe(false);
  });

  it('spends one request when load-more is triggered twice (FE-31)', async () => {
    const fetchMock = vi.fn((url, opts) =>
      ok({ results: JSON.parse(opts.body).page === 1 ? rows(1, 12) : rows(13, 12) })
    );
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest, requestLimit: 12 }));

    act(() => result.current.setQuery('action'));
    await act(async () => {
      await result.current.search(null, null, 1, {});
    });
    const before = fetchMock.mock.calls.length;

    await act(async () => {
      await Promise.all([result.current.loadMore({}), result.current.loadMore({})]);
    });

    expect(fetchMock.mock.calls.length - before).toBe(1);
  });

  it('ignores a superseded response (FE-03)', async () => {
    let releaseFirst;
    const slow = new Promise((resolve) => {
      releaseFirst = () => resolve({ ok: true, status: 200, json: () => Promise.resolve({ results: rows(100, 3) }) });
    });
    let call = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        call += 1;
        return call === 1 ? slow : ok({ results: rows(1, 3) });
      })
    );

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest, requestLimit: 12 }));

    act(() => {
      void result.current.search(null, 'first', 1, {});
    });
    await act(async () => {
      await result.current.search(null, 'second', 1, {});
    });
    await act(async () => {
      releaseFirst();
    });

    expect(result.current.mangas.map(m => m.id)).toEqual([1, 2, 3]);
    expect(result.current.resultKey).toContain('second');
  });

  it('gives each distinct query set its own result key (FE-15)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => ok({ results: rows(1, 3) })));
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    await act(async () => {
      await result.current.search(null, 'one', 1, { min_score: 5 });
    });
    const first = result.current.resultKey;
    await act(async () => {
      await result.current.search(null, 'one', 1, { min_score: 6 });
    });

    expect(result.current.resultKey).not.toBe(first);
  });

  it('a #tag search behaves like a typed query', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 3) }));
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    await act(async () => {
      await result.current.searchForTag('Isekai', {});
    });

    expect(result.current.query).toBe('#Isekai');
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).query).toBe('#Isekai');
  });

  it('refuses an empty query without spending a request', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    let answer;
    await act(async () => {
      answer = await result.current.search(null, '   ', 1, {});
    });

    expect(answer).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    await waitFor(() => expect(result.current.loading).toBe(false));
  });
});
