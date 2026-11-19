import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// B-06: SettingsModal offers four title fonts, index.css maps each one to a font
// stack, and index.html has to actually load the family the stack names first.
// Nothing linked the two files, so "Tech Mono" and "Cinematic" shipped rendering in
// the system monospace and Georgia. This reads the real files, so a new option or a
// dropped font link fails here instead of in a screenshot review.
const read = relative => readFileSync(resolve(process.cwd(), relative), 'utf8');

const css = read('src/index.css');
const html = read('index.html');
const appFontsHtml = html.split('<title>')[0];
const loadedFamilies = [...appFontsHtml.matchAll(/family=([^&:]+)/g)].map(match =>
  match[1].replace(/\+/g, ' ')
);

const stacks = [...css.matchAll(/:root\[data-title-font="([^"]+)"\]\s*\{\s*--font-heading:\s*([^;]+);/g)].map(
  match => ({
    option: match[1],
    primary: match[2].split(',')[0].trim().replace(/^['"]|['"]$/g, '')
  })
);

describe('title fonts (B-06)', () => {
  it('declares a heading stack for each of the four settings options', () => {
    expect(stacks.map(stack => stack.option).sort()).toEqual(['display', 'mono', 'sans', 'serif']);
  });

  it('loads the primary family of every title font stack in index.html', () => {
    const missing = stacks
      .filter(stack => !loadedFamilies.includes(stack.primary))
      .map(stack => `${stack.option} → ${stack.primary}`);

    expect(loadedFamilies.length).toBeGreaterThan(0);
    expect(missing).toEqual([]);
  });
});
