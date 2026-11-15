import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useTabRouting, { getInitialTab, getTabFromPath, tabToPath } from './useTabRouting';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('tab routing helpers (FE-29 extraction)', () => {
  it('maps a path to a tab and back', () => {
    expect(getTabFromPath('/')).toBe('explore');
    expect(getTabFromPath('/trending')).toBe('trending');
    expect(getTabFromPath('/surprise/')).toBe('surprise');
    expect(getTabFromPath('/nonsense')).toBe('explore');
    expect(tabToPath('explore')).toBe('/');
    expect(tabToPath('bookmarks')).toBe('/bookmarks');
  });

  it('reads a legacy #tab hash and rewrites it to a path', () => {
    window.history.replaceState({}, '', '/#trending');

    expect(getInitialTab()).toBe('trending');
    expect(window.location.pathname).toBe('/trending');
    expect(window.location.hash).toBe('');
  });
});

describe('useTabRouting', () => {
  it('pushes a new tab and its path, and records history', () => {
    const { result } = renderHook(() => useTabRouting());
    expect(result.current.activeTab).toBe('explore');

    act(() => result.current.pushTab('trending'));

    expect(result.current.activeTab).toBe('trending');
    expect(window.location.pathname).toBe('/trending');
  });

  it('follows Back/Forward through popstate', async () => {
    const { result } = renderHook(() => useTabRouting());

    act(() => result.current.pushTab('surprise'));
    expect(result.current.activeTab).toBe('surprise');

    // Simulate Back: the URL moved, and popstate is what tells the app.
    act(() => {
      window.history.replaceState({}, '', '/trending');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    await act(async () => {});

    expect(result.current.activeTab).toBe('trending');
  });

  it('keeps the path in step when the tab is set directly', async () => {
    const { result } = renderHook(() => useTabRouting());

    act(() => result.current.setActiveTab('bookmarks'));
    await act(async () => {});

    expect(window.location.pathname).toBe('/bookmarks');
  });
});
