import { describe, it, expect, beforeEach } from 'vitest';
import { isCoverCached, markCoverCached, loadedCoverCache } from './imageUtils';

// FE-27: the cover cache used to grow for the lifetime of the session.
describe('cover cache bound', () => {
  beforeEach(() => {
    loadedCoverCache.clear();
  });

  it('remembers a cover and reports it as cached', () => {
    markCoverCached('https://example.test/a.jpg');
    expect(isCoverCached('https://example.test/a.jpg')).toBe(true);
    expect(isCoverCached(undefined)).toBe(false);
  });

  it('evicts the oldest entry instead of growing without limit', () => {
    for (let i = 0; i < 500; i += 1) {
      markCoverCached(`https://example.test/${i}.jpg`);
    }

    expect(loadedCoverCache.size).toBe(400);
    expect(isCoverCached('https://example.test/0.jpg')).toBe(false);
    expect(isCoverCached('https://example.test/499.jpg')).toBe(true);
  });

  it('moves a re-loaded cover to the back of the queue', () => {
    for (let i = 0; i < 400; i += 1) {
      markCoverCached(`https://example.test/${i}.jpg`);
    }

    markCoverCached('https://example.test/0.jpg');
    markCoverCached('https://example.test/new.jpg');

    expect(loadedCoverCache.size).toBe(400);
    expect(isCoverCached('https://example.test/0.jpg')).toBe(true);
    expect(isCoverCached('https://example.test/1.jpg')).toBe(false);
  });
});
