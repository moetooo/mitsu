import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useSimilarRoute from '@/hooks/useSimilarRoute';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('useSimilarRoute', () => {
  it('reads the destination from the path on a cold load', () => {
    window.history.replaceState({}, '', '/similar/7');

    const { result } = renderHook(() => useSimilarRoute());

    expect(result.current.similarId).toBe(7);
  });

  it('opens the page with an in-app history entry', () => {
    const { result } = renderHook(() => useSimilarRoute());

    act(() => {
      expect(result.current.openSimilar(12)).toBe(true);
    });

    expect(result.current.similarId).toBe(12);
    expect(window.location.pathname).toBe('/similar/12');
    expect(window.history.state).toMatchObject({ fromSimilar: true });
  });

  it('rejects a non-numeric id without touching the URL', () => {
    const { result } = renderHook(() => useSimilarRoute());

    act(() => {
      expect(result.current.openSimilar(null)).toBe(false);
      expect(result.current.openSimilar('7')).toBe(false);
    });

    expect(result.current.similarId).toBeNull();
    expect(window.location.pathname).toBe('/');
  });

  it('follows Back to the results and clears the destination', () => {
    const { result } = renderHook(() => useSimilarRoute());

    act(() => {
      result.current.openSimilar(12);
    });
    act(() => {
      window.history.replaceState({}, '', '/');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(result.current.similarId).toBeNull();
  });

  it('clears without navigating when a tab is chosen', () => {
    window.history.replaceState({}, '', '/similar/12');
    const { result } = renderHook(() => useSimilarRoute());

    act(() => {
      result.current.clearSimilar();
    });

    expect(result.current.similarId).toBeNull();
    expect(window.location.pathname).toBe('/similar/12');
  });

  it('closes a deep link by going to Explore instead of leaving the site', () => {
    window.history.replaceState({}, '', '/similar/12');
    const { result } = renderHook(() => useSimilarRoute());

    act(() => {
      result.current.closeSimilar();
    });

    expect(result.current.similarId).toBeNull();
    expect(window.location.pathname).toBe('/');
  });
});
