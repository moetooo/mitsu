import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useRouteSync from '@/hooks/useRouteSync';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('useRouteSync', () => {
  it('restores the URL once on mount', () => {
    window.history.replaceState({}, '', '/?q=dark+fantasy&genreInUrl=1');
    const onRestore = vi.fn();

    renderHook(() => useRouteSync({ onRestore }));

    expect(onRestore).toHaveBeenCalledTimes(1);
    expect(onRestore.mock.calls[0][0].q).toBe('dark fantasy');
    expect(onRestore.mock.calls[0][1]).toEqual({ source: 'initial' });
  });

  it('pushes a new intent and replaces paging in one writer', () => {
    const onRestore = vi.fn();
    const { result } = renderHook(() => useRouteSync({ onRestore }));

    act(() => {
      result.current.commit({ tab: 'explore', q: 'cats', filters: {}, sort: 'default', page: 1 });
    });
    expect(window.location.search).toContain('q=cats');

    act(() => {
      result.current.commit(
        { tab: 'explore', q: 'cats', filters: {}, sort: 'default', page: 2 },
        { replace: true }
      );
    });
    expect(window.location.search).toContain('page=2');
  });

  it('does not write when the URL already matches', () => {
    const push = vi.spyOn(window.history, 'pushState');
    const onRestore = vi.fn();
    const { result } = renderHook(() => useRouteSync({ onRestore }));

    let changed;
    act(() => {
      changed = result.current.commit({ tab: 'explore', q: '', filters: {}, sort: 'default', page: 1 });
    });

    expect(changed).toBe(false);
    expect(push).not.toHaveBeenCalled();
    push.mockRestore();
  });

  it('restores on Back/Forward popstate', () => {
    const onRestore = vi.fn();
    renderHook(() => useRouteSync({ onRestore }));
    onRestore.mockClear();

    act(() => {
      window.history.replaceState({}, '', '/?q=back&sort=popularity');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(onRestore).toHaveBeenCalledTimes(1);
    expect(onRestore.mock.calls[0][0]).toMatchObject({ q: 'back', sort: 'popularity' });
    expect(onRestore.mock.calls[0][1]).toEqual({ source: 'popstate' });
  });
});
