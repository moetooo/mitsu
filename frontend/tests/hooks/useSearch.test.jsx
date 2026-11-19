import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useSearch from '@/hooks/useSearch';

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

  it('still answers an empty query, and leaves the "is this a browse?" question to App', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 12) }));
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    let answer;
    await act(async () => {
      answer = await result.current.search(null, '', 1, {});
    });

    // The hook stays willing: a filter-only browse goes through this same call.
    // Whether an *unfiltered* empty query is a request at all is a page decision
    // App now makes (Explore's arrival state is the Trending rail), so the hook
    // no longer reports a `browsing` flag for the UI to hang rank badges on.
    expect(answer).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.query).toBe('');
    expect(body.page).toBe(1);
    expect(body.sort).toBe('default');
    expect(result.current.mangas).toHaveLength(12);
    expect(result.current.browsing).toBeUndefined();
    expect(result.current.browse).toBeUndefined();
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it('browses the catalogue when filters are set and the box is empty', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 12) }));
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    let answer;
    await act(async () => {
      answer = await result.current.search(null, '', 1, { genres: ['Action'] });
    });

    expect(answer).toBe(true);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.query).toBe('');
    expect(body.filters.genres).toEqual(['Action']);
    expect(result.current.mangas).toHaveLength(12);
    expect(result.current.searched).toBe(true);
  });

  it('sends the sort and resets the page when the order changes', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 12) }));
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    await act(async () => {
      await result.current.search(null, 'action', 1, {});
    });
    await act(async () => {
      await result.current.setSort('popularity', {});
    });

    const bodies = fetchMock.mock.calls.map(([, opts]) => JSON.parse(opts.body));
    expect(bodies[0].sort).toBe('default');
    expect(bodies[1].sort).toBe('popularity');
    expect(bodies[1].page).toBe(1);
    expect(result.current.page).toBe(1);
    expect(result.current.sort).toBe('popularity');
    expect(result.current.resultKey).toContain('popularity');
  });

  it('load-more replays the criteria page 1 was fetched with', async () => {
    const fetchMock = vi.fn((url, opts) => {
      const body = JSON.parse(opts.body);
      return ok({ results: body.page === 1 ? rows(1, 12) : rows(13, 12) });
    });
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    await act(async () => {
      await result.current.search(null, 'action', 1, { status: ['FINISHED'] }, 'relevance');
    });
    // The user edits the box but does not submit: page 2 must still be the
    // committed query, not the draft.
    act(() => result.current.setQuery('something else'));
    await act(async () => {
      await result.current.loadMore();
    });

    const page2 = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(page2.query).toBe('action');
    expect(page2.filters.status).toEqual(['FINISHED']);
    expect(page2.sort).toBe('relevance');
    expect(page2.page).toBe(2);
  });

  it('stops restoring at the last page that has rows and reports the last good page', async () => {
    const fetchMock = vi.fn((url, opts) => {
      const page = JSON.parse(opts.body).page;
      return ok({ results: page <= 2 ? rows((page - 1) * 12 + 1, 12) : [] });
    });
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    let reached;
    await act(async () => {
      reached = await result.current.restore({ query: 'action', filters: {}, sort: 'default', page: 5 });
    });

    // Page 3 came back empty, so 2 is the last page with content.
    expect(reached).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.current.mangas).toHaveLength(24);
    expect(result.current.page).toBe(2);
  });

  it('resets to page 1 when the criteria change after paging', async () => {
    const fetchMock = vi.fn(() => ok({ results: rows(1, 12) }));
    vi.stubGlobal('fetch', fetchMock);
    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSearch({ beginRequest }));

    await act(async () => {
      await result.current.search(null, 'action', 1, {});
    });
    await act(async () => {
      await result.current.loadMore();
    });
    expect(result.current.page).toBe(2);

    await act(async () => {
      await result.current.search(null, 'different', 1, {});
    });

    expect(result.current.page).toBe(1);
    const body = JSON.parse(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][1].body);
    expect(body.page).toBe(1);
    expect(body.query).toBe('different');
  });
});
