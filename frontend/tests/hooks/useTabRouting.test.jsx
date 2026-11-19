import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useTabRouting, { getInitialTab, getTabFromPath, tabToPath } from '@/hooks/useTabRouting';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('tab routing helpers (FE-29 extraction)', () => {
  it('maps a path to a tab and back', () => {
    expect(getTabFromPath('/')).toBe('explore');
    expect(getTabFromPath('/trending')).toBe('explore');
    expect(getTabFromPath('/surprise/')).toBe('surprise');
    expect(getTabFromPath('/nonsense')).toBe('explore');
    expect(tabToPath('explore')).toBe('/');
    expect(tabToPath('bookmarks')).toBe('/bookmarks');
  });

  it('reads a legacy #tab hash and rewrites it to a path', () => {
    window.history.replaceState({}, '', '/#bookmarks');

    expect(getInitialTab()).toBe('bookmarks');
    expect(window.location.pathname).toBe('/bookmarks');
    expect(window.location.hash).toBe('');
  });
});

describe('useTabRouting', () => {
  it('pushes a new tab and its path, and records history', () => {
    const { result } = renderHook(() => useTabRouting());
    expect(result.current.activeTab).toBe('explore');

    act(() => result.current.pushTab('bookmarks'));

    expect(result.current.activeTab).toBe('bookmarks');
    expect(window.location.pathname).toBe('/bookmarks');
  });

  it('leaves the /similar/{id} destination alone on mount', () => {
    window.history.replaceState({}, '', '/similar/42');

    renderHook(() => useTabRouting());

    // Rewriting this to `/` would bounce the full "You Might Also Like" page.
    expect(window.location.pathname).toBe('/similar/42');
  });

  it('follows Back/Forward through popstate', async () => {
    const { result } = renderHook(() => useTabRouting());

    act(() => result.current.pushTab('surprise'));
    expect(result.current.activeTab).toBe('surprise');

    // Simulate Back: the URL moved, and popstate is what tells the app.
    act(() => {
      window.history.replaceState({}, '', '/bookmarks');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    await act(async () => {});

    expect(result.current.activeTab).toBe('bookmarks');
  });

  it('keeps the path in step when the tab is set directly', async () => {
    const { result } = renderHook(() => useTabRouting());

    act(() => result.current.setActiveTab('bookmarks'));
    await act(async () => {});

    expect(window.location.pathname).toBe('/bookmarks');
  });
});

describe('useTabRouting keeps the explore query string', () => {
  it('carries params across a tab switch and a direct tab set', async () => {
    window.history.replaceState({}, '', '/?q=cats&sort=popularity');
    const { result } = renderHook(() => useTabRouting());

    act(() => result.current.pushTab('bookmarks'));
    expect(window.location.pathname).toBe('/bookmarks');
    expect(window.location.search).toBe('?q=cats&sort=popularity');

    act(() => result.current.setActiveTab('explore'));
    await act(async () => {});
    expect(window.location.pathname).toBe('/');
    expect(window.location.search).toBe('?q=cats&sort=popularity');
  });
});
