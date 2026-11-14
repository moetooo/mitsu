import { describe, it, expect } from 'vitest';
import { formatScore, scoreOutOfTen } from './scoreUtils';

// FE-14: one conversion for every score surface. The catalogue is 0-100; some
// provider payloads are already 0-10.
describe('scoreOutOfTen', () => {
  it('converts the catalogue 0-100 scale', () => {
    expect(scoreOutOfTen(84)).toBeCloseTo(8.4);
    expect(scoreOutOfTen(100)).toBe(10);
  });

  it('leaves an already-normalised score alone', () => {
    expect(scoreOutOfTen(8.4)).toBeCloseTo(8.4);
    expect(scoreOutOfTen(10)).toBe(10);
  });

  it('returns null for missing or unusable values', () => {
    expect(scoreOutOfTen(undefined)).toBeNull();
    expect(scoreOutOfTen(null)).toBeNull();
    expect(scoreOutOfTen('')).toBeNull();
    expect(scoreOutOfTen(0)).toBeNull();
    expect(scoreOutOfTen('not a number')).toBeNull();
  });

  it('accepts numeric strings', () => {
    expect(formatScore('84')).toBe('8.4');
  });
});

describe('formatScore', () => {
  it('formats one decimal by default and honours a digit count', () => {
    expect(formatScore(84)).toBe('8.4');
    expect(formatScore(84, 2)).toBe('8.40');
  });

  it('returns null instead of rendering a fake zero', () => {
    expect(formatScore(null)).toBeNull();
  });
});
