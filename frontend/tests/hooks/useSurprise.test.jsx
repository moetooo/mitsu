import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import useSurprise from '@/hooks/useSurprise';

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

const row = (id) => ({ id, title: `Title ${id}`, cover_image_url: `https://x.invalid/${id}.jpg` });
const ok = (body) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

const base = { beginRequest: makeRequestGuard(), filters: { genres: [] }, query: '', allowNsfw: false };

beforeEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe('useSurprise (FE-29 extraction of FE-10/FE-17/FE-25/FE-28)', () => {
  it('draws once when the tab is entered with an empty queue', async () => {
    const fetchMock = vi.fn(() => ok(row(1)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() =>
      useSurprise({ ...base, beginRequest, activeTab: 'surprise' })
    );

    await waitFor(() => expect(result.current.queue).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('roulette');
    expect(result.current.loading).toBe(false);
  });

  it('does not draw while the tab is closed', async () => {
    const fetchMock = vi.fn(() => ok(row(1)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    await act(async () => {});

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.queue).toEqual([]);
  });

  it('joins the request already in flight instead of POSTing twice', async () => {
    const fetchMock = vi.fn(() => ok(row(7)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    await act(async () => {
      await Promise.all([result.current.draw(), result.current.draw()]);
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.queue).toHaveLength(1);
  });

  it('a fresh draw empties the queue and remounts the view', async () => {
    vi.stubGlobal('fetch', vi.fn(() => ok(row(1))));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    await act(async () => {
      await result.current.draw();
    });
    expect(result.current.queue).toHaveLength(1);
    const keyBefore = result.current.key;

    await act(async () => {
      await result.current.draw(true);
    });

    expect(result.current.key).toBe(keyBefore + 1);
    expect(result.current.queue).toHaveLength(1);
  });

  it('reports "nothing matches" once on a 404 and clears it on the next draw (FE-25)', async () => {
    let status = 404;
    vi.stubGlobal('fetch', vi.fn(() =>
      Promise.resolve({ ok: status === 200, status, json: () => Promise.resolve(row(2)) })
    ));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    await act(async () => {
      await result.current.draw();
    });
    expect(result.current.exhausted).toBe(true);
    expect(result.current.error).toBeNull();

    status = 200;
    await act(async () => {
      await result.current.draw(true);
    });
    expect(result.current.exhausted).toBe(false);
    expect(result.current.queue).toHaveLength(1);
  });

  it('a failed draw reports an error instead of pretending nothing matched', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('down'))));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    await act(async () => {
      await result.current.draw();
    });

    expect(result.current.error).toBeTruthy();
    expect(result.current.exhausted).toBe(false);
    expect(result.current.loading).toBe(false);
  });

  it('drops unusable rows at insertion so the queue has no holes (FE-28)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => ok([null, { title: 'no id' }, row(3)])));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    let returned;
    await act(async () => {
      returned = await result.current.fetchBatch(3);
    });

    // The batch reply is passed through as received; the queue is what is cleaned.
    expect(returned.length).toBeGreaterThan(0);
    expect(result.current.queue.map((r) => r.id)).toEqual([3]);
  });

  it('a batch adds only ids the queue does not have yet', async () => {
    let body = row(1);
    vi.stubGlobal('fetch', vi.fn(() => ok(body)));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    await act(async () => {
      await result.current.draw();
    });
    body = [row(1), row(4), row(4)];
    await act(async () => {
      await result.current.fetchBatch(3);
    });

    expect(result.current.queue.map((r) => r.id)).toEqual([1, 4]);
  });

  it('a batch failure is survivable and returns nothing', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('down'))));

    const beginRequest = makeRequestGuard();
    const { result } = renderHook(() => useSurprise({ ...base, beginRequest, activeTab: 'explore' }));

    let returned;
    await act(async () => {
      returned = await result.current.fetchBatch();
    });

    expect(returned).toEqual([]);
    expect(result.current.queue).toEqual([]);
  });

  it('does not draw a second time when the tab is entered (B-05)', async () => {
    const fetchMock = vi.fn(() => ok(row(3)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result, rerender } = renderHook(
      ({ tab }) => useSurprise({ ...base, beginRequest, activeTab: tab }),
      { initialProps: { tab: 'explore' } }
    );

    await act(async () => {});
    expect(fetchMock).not.toHaveBeenCalled();

    rerender({ tab: 'surprise' });
    await waitFor(() => expect(result.current.queue).toHaveLength(1), { timeout: 3000 });

    // The filter effect also reacted to `activeTab`, so it scheduled a forced redraw
    // 400 ms after entry; waiting past that window is what exposes it.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 700));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.queue).toHaveLength(1);
  });

  it('resets the queue when the filters change while the tab is open', async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(() => ok(row(5)));
    vi.stubGlobal('fetch', fetchMock);

    const beginRequest = makeRequestGuard();
    const { result, rerender } = renderHook(
      (props) => useSurprise({ ...base, beginRequest, activeTab: 'surprise', ...props }),
      { initialProps: { filters: { genres: [] } } }
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender({ filters: { genres: ['Action'] } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1200);
    });

    // A fresh draw: new session, queue rebuilt under the new filters.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(secondBody.filters.genres).toEqual(['Action']);
    expect(result.current.queue).toHaveLength(1);
    vi.useRealTimers();
  });
});
