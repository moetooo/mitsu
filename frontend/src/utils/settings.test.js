import { describe, it, expect } from 'vitest';
import {
  DEFAULT_SETTINGS,
  normalizeSettings,
  clampLimit,
  clampBatchSize,
  clampNumber,
  SETTINGS_RANGES
} from './settings';

// FE-22: settings are read from localStorage and then sent to the API as request
// parameters. The parse was guarded; the values were not, so a corrupted blob
// produced a 422 (the server bounds limit to 1-50) or an unusable UI.

describe('normalizeSettings', () => {
  it('returns the defaults for junk input', () => {
    for (const junk of [null, undefined, 42, 'nope', [], true]) {
      expect(normalizeSettings(junk)).toEqual(DEFAULT_SETTINGS);
    }
  });

  it('keeps valid stored values', () => {
    const stored = { theme: 'washi', gridSize: 'compact', limit: 24, allowNsfw: true };
    const settings = normalizeSettings(stored);
    expect(settings.theme).toBe('washi');
    expect(settings.gridSize).toBe('compact');
    expect(settings.limit).toBe(24);
    expect(settings.allowNsfw).toBe(true);
  });

  it('replaces an unknown enum value with the default', () => {
    const settings = normalizeSettings({
      theme: 'neon',
      gridSize: 'gigantic',
      hoverAccent: 'chartreuse',
      fontStyle: 'comic-sans',
      accent: 'plaid'
    });
    expect(settings.theme).toBe(DEFAULT_SETTINGS.theme);
    expect(settings.gridSize).toBe(DEFAULT_SETTINGS.gridSize);
    expect(settings.hoverAccent).toBe(DEFAULT_SETTINGS.hoverAccent);
    expect(settings.fontStyle).toBe(DEFAULT_SETTINGS.fontStyle);
    expect(settings.accent).toBe(DEFAULT_SETTINGS.accent);
  });

  it('clamps limit and batchSize to what the API accepts', () => {
    const settings = normalizeSettings({ limit: 999999, batchSize: -5 });
    expect(settings.limit).toBe(SETTINGS_RANGES.limit.max);
    expect(settings.batchSize).toBe(SETTINGS_RANGES.batchSize.min);
  });

  it('rejects NaN, Infinity and numeric strings that are not numbers', () => {
    expect(normalizeSettings({ limit: NaN }).limit).toBe(DEFAULT_SETTINGS.limit);
    // Infinity is not a usable request parameter; it falls back, it does not clamp.
    expect(normalizeSettings({ limit: Infinity }).limit).toBe(DEFAULT_SETTINGS.limit);
    expect(normalizeSettings({ limit: 'abc' }).limit).toBe(DEFAULT_SETTINGS.limit);
    expect(normalizeSettings({ limit: '24' }).limit).toBe(24);
  });

  it('keeps only real booleans for the toggles', () => {
    const settings = normalizeSettings({ allowNsfw: 'yes', nsfwBlur: 0, infiniteScroll: null });
    // Truthy strings are deliberately ignored: an 18+ gate must not open on "yes".
    expect(settings.allowNsfw).toBe(DEFAULT_SETTINGS.allowNsfw);
    expect(settings.nsfwBlur).toBe(DEFAULT_SETTINGS.nsfwBlur);
    expect(settings.infiniteScroll).toBe(DEFAULT_SETTINGS.infiniteScroll);
  });

  it('never returns a field the settings modal does not know', () => {
    const settings = normalizeSettings({ ...DEFAULT_SETTINGS, extra: 'ignored' });
    expect(settings).not.toHaveProperty('extra');
  });
});

describe('clampLimit / clampBatchSize', () => {
  it('bounds a value at the request site too', () => {
    expect(clampLimit(0)).toBe(1);
    expect(clampLimit(1000)).toBe(50);
    expect(clampLimit(undefined)).toBe(DEFAULT_SETTINGS.limit);
    expect(clampBatchSize(0)).toBe(1);
  });
});

describe('clampNumber', () => {
  it('rounds and falls back', () => {
    expect(clampNumber(7.6, { min: 1, max: 10 }, 3)).toBe(8);
    expect(clampNumber('x', { min: 1, max: 10 }, 3)).toBe(3);
  });
});
