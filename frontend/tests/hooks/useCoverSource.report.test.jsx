/**
 * When the browser runs out of cover candidates, the title is reported to the
 * backend. This is the only path by which a reader's broken cover reaches the
 * repair queue, so it is tested away from the components that render it.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useCoverSource } from '@/hooks/useCoverSource';
import { __resetCoverReports, setCoverReportingEnabled } from '@/utils/coverReports';

const oneCandidate = {
  id: 101,
  cover_image_url: 'https://s4.anilist.co/a.jpg',
  cover_candidates: [{ url: 'https://s4.anilist.co/a.jpg', source: 'anilist' }],
};

const twoCandidates = {
  id: 102,
  cover_image_url: 'https://s4.anilist.co/b.jpg',
  cover_candidates: [
    { url: 'https://s4.anilist.co/b.jpg', source: 'anilist' },
    { url: 'https://cdn.myanimelist.net/b.jpg', source: 'mal' },
  ],
};

describe('useCoverSource reporting', () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202 });
    globalThis.fetch = fetchMock;
    __resetCoverReports();
    setCoverReportingEnabled(true);
  });

  afterEach(() => {
    setCoverReportingEnabled(false);
    vi.restoreAllMocks();
  });

  it('reports the title once every candidate has failed', () => {
    const { result } = renderHook(() => useCoverSource(oneCandidate));

    expect(fetchMock).not.toHaveBeenCalled();

    act(() => result.current.handleError());
    expect(fetchMock).not.toHaveBeenCalled(); // one retry is still in flight

    act(() => result.current.handleError());
    expect(result.current.dead).toBe(true);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toContain('/covers/101/broken');
  });

  it('does not report while a fallback candidate remains', () => {
    const { result } = renderHook(() => useCoverSource(twoCandidates));

    act(() => result.current.handleError());
    act(() => result.current.handleError());

    // Moved on to the MAL candidate rather than giving up.
    expect(result.current.src).toBe('https://cdn.myanimelist.net/b.jpg');
    expect(result.current.dead).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('reports nothing for a title with no id', () => {
    const { result } = renderHook(() => useCoverSource({ cover_image_url: null }));

    expect(result.current.dead).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
