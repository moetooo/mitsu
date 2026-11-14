import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readJSON, writeJSON, removeKey, resetStorageWarning, warnStorageOnce } from './storage';

// FE-18: every localStorage call used to be bare. A full quota throws, and the
// throw landed inside a React effect or a click handler — the app kept running
// while nothing was saved, forever, with no message.

const clearStorage = () => {
  try {
    localStorage.clear();
  } catch {
    /* ignore */
  }
};

let warnSpy;

beforeEach(() => {
  clearStorage();
  resetStorageWarning();
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
  clearStorage();
});

describe('readJSON', () => {
  it('returns the fallback when the key is absent', () => {
    expect(readJSON('missing', { a: 1 })).toEqual({ a: 1 });
  });

  it('returns parsed data when present', () => {
    localStorage.setItem('settings', JSON.stringify({ limit: 12 }));
    expect(readJSON('settings', null)).toEqual({ limit: 12 });
  });

  it('tries the legacy key second, so an upgrade keeps the data', () => {
    localStorage.setItem('mangamind_settings', JSON.stringify({ limit: 8 }));
    expect(readJSON(['mitsu_settings', 'mangamind_settings'], null)).toEqual({ limit: 8 });
  });

  it('returns the fallback for a corrupted value instead of throwing', () => {
    localStorage.setItem('settings', '{not json');
    expect(readJSON('settings', { limit: 10 })).toEqual({ limit: 10 });
    expect(warnSpy).toHaveBeenCalled();
  });

  it('skips a null JSON payload', () => {
    localStorage.setItem('settings', 'null');
    expect(readJSON('settings', { limit: 10 })).toEqual({ limit: 10 });
  });

  it('returns the fallback when storage itself throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(readJSON('settings', [])).toEqual([]);
    expect(warnSpy).toHaveBeenCalled();
  });
});

describe('writeJSON', () => {
  it('reports success and round-trips', () => {
    expect(writeJSON('key', { a: [1, 2] })).toBe(true);
    expect(readJSON('key', null)).toEqual({ a: [1, 2] });
  });

  it('swallows a quota failure, reports false, and warns only once', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      const error = new Error('quota');
      error.name = 'QuotaExceededError';
      throw error;
    });

    expect(writeJSON('a', {})).toBe(false);
    expect(writeJSON('b', {})).toBe(false);
    expect(writeJSON('c', {})).toBe(false);

    // One message per session: four failing writes must not spam the console.
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain('QuotaExceededError');
  });
});

describe('removeKey', () => {
  it('removes and reports success', () => {
    localStorage.setItem('key', '1');
    expect(removeKey('key')).toBe(true);
    expect(localStorage.getItem('key')).toBeNull();
  });

  it('does not throw when storage refuses', () => {
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(removeKey('key')).toBe(false);
  });
});

describe('warnStorageOnce', () => {
  it('is idempotent across modules', () => {
    warnStorageOnce(new Error('first'));
    warnStorageOnce(new Error('second'));
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });
});
