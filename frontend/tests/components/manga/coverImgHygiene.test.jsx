/**
 * How the cover images are loaded, not just where from.
 *
 * Three attributes decide what the browser does with a cover, and each was missing
 * or wrong before: `loading` (defer off-screen cards), `fetchpriority` (do not let a
 * blurred decorative duplicate outrank the real poster) and `decoding="async"` (do
 * not block the main thread on decode). They are easy to drop in a refactor and
 * invisible in a screenshot, so they are asserted here.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/react';

import MangaCard from '@/components/manga/MangaCard';
import MangaDetailModal from '@/components/manga/MangaDetailModal';

const ANILIST = 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx1-a.png';

const MANGA = {
  id: 41,
  title: 'Vinland Saga',
  cover_image_url: ANILIST,
  cover_candidates: [{ source: 'anilist', url: ANILIST }],
};

const CARD_PROPS = {
  manga: MANGA,
  onClick: () => {},
  isBookmarked: false,
  onToggleBookmark: () => {},
};

/** The card only mounts its poster once it is near the viewport, so intersect it. */
function observeImmediately() {
  const original = globalThis.IntersectionObserver;
  globalThis.IntersectionObserver = class {
    constructor(callback) {
      this.callback = callback;
    }
    observe(element) {
      this.callback([{ isIntersecting: true, target: element }]);
    }
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  };
  return () => {
    globalThis.IntersectionObserver = original;
  };
}

describe('cover image loading attributes', () => {
  let restore;

  beforeEach(() => {
    restore = observeImmediately();
  });

  afterEach(() => {
    restore();
    vi.restoreAllMocks();
  });

  it('loads an above-the-fold cover eagerly and at high priority', () => {
    const { container } = render(<MangaCard {...CARD_PROPS} priority />);

    const poster = [...container.querySelectorAll('img')].find((img) => img.alt === MANGA.title);
    expect(poster).toBeTruthy();
    expect(poster.getAttribute('loading')).toBe('eager');
    expect(poster.getAttribute('fetchpriority')).toBe('high');
    expect(poster.getAttribute('decoding')).toBe('async');
    expect(poster.getAttribute('referrerpolicy')).toBe('no-referrer');
  });

  it('leaves every other cover lazy, so a long grid does not fetch 60 images', () => {
    const { container } = render(<MangaCard {...CARD_PROPS} />);

    const poster = [...container.querySelectorAll('img')].find((img) => img.alt === MANGA.title);
    expect(poster.getAttribute('loading')).toBe('lazy');
    expect(poster.getAttribute('fetchpriority')).toBe('auto');
  });

  it('declares an intrinsic size so the browser reserves the right box', () => {
    const { container } = render(<MangaCard {...CARD_PROPS} />);

    const poster = [...container.querySelectorAll('img')].find((img) => img.alt === MANGA.title);
    expect(poster.getAttribute('width')).toBe('300');
    expect(poster.getAttribute('height')).toBe('450');
  });

  it('keeps the decorative glow out of the race for bandwidth', () => {
    const { container } = render(<MangaCard {...CARD_PROPS} priority />);

    const glow = [...container.querySelectorAll('img')].find((img) => img.alt === '');
    expect(glow).toBeTruthy();
    expect(glow.getAttribute('aria-hidden')).toBe('true');
    expect(glow.getAttribute('fetchpriority')).toBe('low');
    expect(glow.getAttribute('loading')).toBe('lazy');
  });

  it('loads the modal poster immediately, because the user just asked for it', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) });

    const { container } = render(
      <MangaDetailModal
        manga={MANGA}
        onClose={() => {}}
        onSelectTag={() => {}}
        onSelectManga={() => {}}
        isBookmarked={false}
        onToggleBookmark={() => {}}
      />,
    );

    const poster = [...container.querySelectorAll('img')].find((img) => img.alt === MANGA.title);
    expect(poster).toBeTruthy();
    expect(poster.getAttribute('loading')).toBe('eager');
    expect(poster.getAttribute('fetchpriority')).toBe('high');
    expect(poster.getAttribute('decoding')).toBe('async');
  });
});
