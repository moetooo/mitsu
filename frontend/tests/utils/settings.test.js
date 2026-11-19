import { describe, it, expect } from 'vitest';
import {
  DEFAULT_SETTINGS,
  normalizeSettings,
  clampNumber,
  SETTINGS_RANGES,
  PAGE_SIZE
} from '@/utils/settings';

// FE-22: settings are read from localStorage and then sent to the API as request
// parameters. The parse was guarded; the values were not, so a corrupted blob
// produced a 422 (the server bounds limit to 1-50) or an unusable UI.
//
// FE-06: the page size stopped being a setting. `limit` and `batchSize` were two
// knobs for one question and up to four variants of every trending cache key, so
// there is one `PAGE_SIZE` and a stored limit must not survive normalisation.

describe('normalizeSettings', () => {
  it('returns the defaults for junk input', () => {
    for (const junk of [null, undefined, 42, 'nope', [], true]) {
      expect(normalizeSettings(junk)).toEqual(DEFAULT_SETTINGS);
    }
  });

  it('keeps valid stored values', () => {
    const stored = { theme: 'washi', gridSize: 'compact', allowNsfw: true };
    const settings = normalizeSettings(stored);
    expect(settings.theme).toBe('washi');
    expect(settings.gridSize).toBe('compact');
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

  it('clamps the numeric preferences to what the UI can render', () => {
    const settings = normalizeSettings({ surpriseImageLength: 999 });
    expect(settings.surpriseImageLength).toBe(SETTINGS_RANGES.surpriseImageLength.max);
  });

  it('drops the retired page-size settings', () => {
    const settings = normalizeSettings({ limit: 999999, batchSize: -5 });
    expect(settings).not.toHaveProperty('limit');
    expect(settings).not.toHaveProperty('batchSize');
    expect(PAGE_SIZE).toBe(12);
  });

  it('rejects NaN, Infinity and numeric strings that are not numbers', () => {
    expect(normalizeSettings({ surpriseImageLength: NaN }).surpriseImageLength)
      .toBe(DEFAULT_SETTINGS.surpriseImageLength);
    // Infinity is not a usable request parameter; it falls back, it does not clamp.
    expect(normalizeSettings({ surpriseImageLength: Infinity }).surpriseImageLength)
      .toBe(DEFAULT_SETTINGS.surpriseImageLength);
    expect(normalizeSettings({ surpriseImageLength: 'abc' }).surpriseImageLength)
      .toBe(DEFAULT_SETTINGS.surpriseImageLength);
    expect(normalizeSettings({ surpriseImageLength: '70' }).surpriseImageLength).toBe(70);
  });

  it('keeps only real booleans for the toggles', () => {
    const settings = normalizeSettings({ allowNsfw: 'yes', nsfwBlur: 0 });
    // Truthy strings are deliberately ignored: an 18+ gate must not open on "yes".
    expect(settings.allowNsfw).toBe(DEFAULT_SETTINGS.allowNsfw);
    expect(settings.nsfwBlur).toBe(DEFAULT_SETTINGS.nsfwBlur);
    // FE-06: the infinite-scroll toggle is gone, so a stored one must not survive.
    expect(settings).not.toHaveProperty('infiniteScroll');
  });

  it('never returns a field the settings modal does not know', () => {
    const settings = normalizeSettings({ ...DEFAULT_SETTINGS, extra: 'ignored' });
    expect(settings).not.toHaveProperty('extra');
  });
});

describe('clampNumber', () => {
  it('rounds and falls back', () => {
    expect(clampNumber(7.6, { min: 1, max: 10 }, 3)).toBe(8);
    expect(clampNumber('x', { min: 1, max: 10 }, 3)).toBe(3);
  });
});

describe('retired and previously unreachable preferences (B-07, B-08)', () => {
  it('drops the dead stampStyle key instead of persisting it forever', () => {
    // B-07: it was threaded through App → MangaGrid → MangaCard, and MangaCard
    // never read it. Nothing renders it, so a stored one must not survive.
    const settings = normalizeSettings({ stampStyle: 'hanko' });
    expect(settings).not.toHaveProperty('stampStyle');
  });

  it('drops a stored focusStyle now that SearchBar hardcodes the glow ring', () => {
    // B-08: the style map was retired with the control that set it, so a value
    // left in localStorage must not come back as an unknown key.
    const settings = normalizeSettings({ focusStyle: 'brush' });
    expect(settings).not.toHaveProperty('focusStyle');
  });
});
