/**
 * The Explore hero is the one surface that paints a photograph-sized sheet of art
 * behind text, and it sits on a near-black page in AMOLED and on cream paper in the
 * light theme. It used to hardcode that assumption -- `bg-black/70`, `from-black/90`,
 * `text-white`, white chip borders -- so the light theme got a black slab whose
 * white type bled into a paper-white fade.
 *
 * These tests keep the colours in the theme blocks: the component may only name
 * `--hero-*` tokens, never a fixed black or white. A single reintroduced
 * `text-white` fails here instead of in a screenshot review months later.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { readFileSync } from 'node:fs';

import HeroBanner from '@/components/explore/HeroBanner';

const MANGA = {
  id: 7,
  title: 'Vinland Saga',
  genres: ['Action', 'Historical'],
  status: 'RELEASING',
  start_year: 2005,
  average_score: 91,
  synopsis: 'A young Viking grows up on the wrong side of a blood feud.',
  // The blurred background layer only exists when there is art to blur, and its wash
  // strength is one of the tokens under test.
  cover_image_url: 'https://s4.anilist.co/file/anilistcdn/media/manga/cover/medium/bx1-a.png'
};

const HARDCODED = /(?:^|\s)(?:bg|text|border|from|via|to)-(?:black|white)(?:\/\d+)?(?=\s|$)/;

const allClasses = () =>
  [...document.querySelectorAll('*')].flatMap(node => [...node.classList]);

// Two slides, so an *inactive* dot exists: with one slide only the accent branch of
// the dot class renders and the inactive colour is never exercised.
const MANGA_2 = { ...MANGA, id: 8, title: 'Vagabond' };

beforeEach(() => {
  // The banner falls back to its own art when the catalogue is empty; stub the call
  // so the test never reaches the network.
  globalThis.fetch = vi.fn(() => Promise.resolve({ json: () => Promise.resolve([]) }));
});

describe('HeroBanner colours come from the theme', () => {
  it('names theme tokens instead of fixed black or white', () => {
    render(<HeroBanner mangas={[MANGA]} />);

    const offenders = allClasses().filter(name => HARDCODED.test(name));

    expect(offenders).toEqual([]);
  });

  it('washes the art, the scrims and the cover plate with --hero tokens', () => {
    render(<HeroBanner mangas={[MANGA, MANGA_2]} />);

    const classes = allClasses().join(' ');

    for (const token of [
      'var(--hero-veil)',
      'var(--hero-art-opacity)',
      'var(--hero-scrim-from)',
      'var(--hero-scrim-via)',
      'var(--hero-scrim-to)',
      'var(--hero-side-from)',
      'var(--hero-side-via)',
      'var(--hero-thumb-border)',
      'var(--hero-thumb-bg)',
      'var(--hero-chip-bg)',
      'var(--hero-chip-border)',
      'var(--hero-ink-muted)',
      'var(--hero-ink-soft)',
      'var(--hero-dot)'
    ]) {
      expect(classes).toContain(token);
    }
  });

  it('takes its text colour and halo from the theme, not from a utility class', () => {
    const { container } = render(<HeroBanner mangas={[MANGA]} />);

    const overlay = [...container.querySelectorAll('div')].find(
      node => node.style.color === 'var(--hero-ink)'
    );

    expect(overlay).toBeTruthy();
    expect(overlay.style.filter).toBe('var(--hero-ink-shadow)');
  });

  it('keeps the accent on the score and the active dot', () => {
    render(<HeroBanner mangas={[MANGA]} />);

    // Accent is the site colour and must not be replaced by a hero token: the hero
    // reads as part of the page, not as its own palette.
    const classes = allClasses().join(' ');

    expect(classes).toContain('var(--accent-vermillion)');
  });
});

describe('index.css defines the hero tokens for every theme', () => {
  // jsdom hands modules an http-ish import.meta.url, so resolve from the project root
  // like the other file-reading tests rather than from the module.
  const css = readFileSync('src/index.css', 'utf8');

  // The base block plus the two themes that ship. Reads the real file so a token
  // added to the component but forgotten in one theme block fails here.
  const blocks = [':root {', ':root[data-theme="washi"] {', ':root[data-theme="amoled"]'].map(selector => {
    const start = css.indexOf(selector);

    expect(start, `${selector} should exist in index.css`).toBeGreaterThan(-1);

    return css.slice(start, css.indexOf('\n}', start));
  });

  it('declares every hero token in the base block and both themes', () => {
    const tokens = [...css.matchAll(/--hero-[a-z-]+(?=\s*:)/g)].map(match => match[0]);

    expect(new Set(tokens).size).toBeGreaterThan(10);

    for (const block of blocks) {
      for (const token of ['--hero-veil', '--hero-art-opacity', '--hero-ink', '--hero-chip-bg', '--hero-dot']) {
        expect(block, `${token} missing from a theme block`).toContain(`${token}:`);
      }
    }
  });

  it('flips the ink between dark and light themes, which is the whole point', () => {
    const ink = blocks.map(block => block.match(/--hero-ink:\s*([^;]+);/)[1].trim());

    expect(ink[1]).not.toBe(ink[2]);
  });
});
