import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import useSettings from '@/hooks/useSettings';

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('data-title-font');
  document.documentElement.removeAttribute('data-accent');
});

describe('useSettings (FE-29 extraction of FE-18/FE-22)', () => {
  it('normalises a corrupted blob instead of trusting it', () => {
    localStorage.setItem(
      'mitsu_settings',
      JSON.stringify({ theme: 'neon', gridSize: 'enormous', limit: 999999, infiniteScroll: 'yes' })
    );

    const { result } = renderHook(() => useSettings());

    expect(result.current.settings.theme).not.toBe('neon');
    expect(result.current.settings.gridSize).not.toBe('enormous');
    // The limit reaches a request body, so it must be clamped at the boundary.
    expect(result.current.requestLimit).toBeLessThanOrEqual(50);
    expect(result.current.requestLimit).toBeGreaterThan(0);
  });

  it('falls back to the defaults when storage holds garbage', () => {
    localStorage.setItem('mitsu_settings', '{not json');

    const { result } = renderHook(() => useSettings());

    expect(result.current.settings.theme).toBe('washi');
    expect(result.current.requestLimit).toBeGreaterThan(0);
  });

  it('moves a stored Dark Ink theme onto Paper Light', () => {
    localStorage.setItem('mitsu_settings', JSON.stringify({ theme: 'sumi' }));

    const { result } = renderHook(() => useSettings());

    expect(result.current.settings.theme).toBe('washi');
    expect(document.documentElement.getAttribute('data-theme')).toBe('washi');
  });

  it('pushes theme attributes onto the document root and persists', () => {
    const { result } = renderHook(() => useSettings());

    act(() => {
      result.current.updateSettings(prev => ({ ...prev, theme: 'washi', fontStyle: 'mono' }));
    });

    expect(document.documentElement.getAttribute('data-theme')).toBe('washi');
    expect(document.documentElement.getAttribute('data-title-font')).toBe('mono');
    expect(JSON.parse(localStorage.getItem('mitsu_settings')).theme).toBe('washi');
  });

  it('normalises every write, including a plain object updater', () => {
    const { result } = renderHook(() => useSettings());

    act(() => {
      result.current.updateSettings({ theme: 'amoled', limit: 99999 });
    });

    expect(result.current.settings.theme).toBe('amoled');
    expect(result.current.requestLimit).toBeLessThanOrEqual(50);
  });

  it('does not throw when storage writes fail', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });

    const { result } = renderHook(() => useSettings());

    expect(() => {
      act(() => {
        result.current.updateSettings(prev => ({ ...prev, theme: 'washi' }));
      });
    }).not.toThrow();
    // In memory the change still applies; only persistence was lost.
    expect(result.current.settings.theme).toBe('washi');
  });
});
