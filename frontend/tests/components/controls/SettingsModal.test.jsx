import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import SettingsModal from '@/components/controls/SettingsModal';
import { DEFAULT_SETTINGS } from '@/utils/settings';

// The search-field focus ring is no longer a preference: SearchBar hardcodes the
// glow ring, so no control here may write a focus style.
const Harness = ({ onChange }) => {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const wrapped = updater => {
    setSettings(prev => {
      const next = typeof updater === 'function' ? updater(prev) : { ...prev, ...updater };
      onChange(next);
      return next;
    });
  };
  return <SettingsModal settings={settings} setSettings={wrapped} isOpen onClose={vi.fn()} />;
};

describe('SettingsModal retired search focus control (B-08)', () => {
  it('offers no focus style choice, because SearchBar only renders the glow ring', () => {
    render(<Harness onChange={vi.fn()} />);

    for (const name of ['Search Field Focus', 'Glow Ring', 'Red Edge', 'Brush Stroke', 'Subtle Fill']) {
      expect(screen.queryByRole('button', { name })).toBeNull();
      expect(screen.queryByText(name)).toBeNull();
    }
  });
});

describe('SettingsModal dead-setting removal (B-07)', () => {
  it('renders no stamp control, because no card reads a stamp style', () => {
    render(<Harness onChange={vi.fn()} />);

    expect(screen.queryByRole('button', { name: /hanko|crest|stamp/i })).toBeNull();
  });
});

describe('SettingsModal option-tile consistency', () => {
  it('marks every choice control as a pressed toggle in the same idiom', () => {
    const { container } = render(<Harness onChange={vi.fn()} />);

    const tiles = [...container.querySelectorAll('.option-tile')];
    // 2 themes + 4 title fonts + 3 grid sizes + 4 cover-length presets. Dark Ink
    // and the accent palette are both gone.
    expect(tiles).toHaveLength(13);
    expect(container.textContent).not.toContain('Dark Ink');
    // The two switches share only the hover ring, so they use .option-switch.
    expect(container.querySelectorAll('.option-switch')).toHaveLength(2);

    // One pressed option per group: theme, title font, grid size, cover length.
    expect(tiles.filter(t => t.getAttribute('aria-pressed') === 'true')).toHaveLength(4);
    for (const tile of tiles) {
      expect(['true', 'false']).toContain(tile.getAttribute('aria-pressed'));
    }
  });

  it('leaves tile geometry to the master class, not to per-tile utilities', () => {
    const { container } = render(<Harness onChange={vi.fn()} />);

    for (const tile of container.querySelectorAll('.option-tile')) {
      const cls = tile.getAttribute('class');
      expect(cls).not.toMatch(/rounded-(?:xl|2xl|full)/);
      expect(cls).not.toMatch(/(?:^|\s)(?:p|py|px)-[0-9]/);
      expect(cls).not.toMatch(/border-\[var/);
      expect(cls).not.toMatch(/bg-\[var/);
      expect(cls).not.toMatch(/text-\[(?:var|white)/);
    }
    // Section cards follow the same token.
    expect(container.querySelectorAll('.option-group')).toHaveLength(2);
  });

  it('has no accent palette and no colour chip inside any theme tile', () => {
    const { container } = render(<Harness onChange={vi.fn()} />);

    expect(container.textContent).not.toMatch(/Accent Color Palette/i);
    for (const name of ['Amber', 'Emerald', 'Indigo', 'Rose', 'Vermillion']) {
      expect(container.textContent).not.toContain(name);
    }
    expect(container.querySelectorAll('.option-tile--swatch')).toHaveLength(0);
    expect(container.querySelectorAll('.option-tile span[class*="rounded-full"]')).toHaveLength(0);
  });

  it('uses no fixed second accent and no per-control ring utilities', () => {
    const { container } = render(<Harness onChange={vi.fn()} />);
    const html = container.innerHTML;

    expect(html).not.toContain('accent-indigo');
    expect(html).not.toMatch(/ring-2|shadow-md|shadow-sm/);
  });
});

describe('option-tile CSS is the single source of tile style', () => {  it('keeps master geometry tokens, the nav-style chosen state, and dark disabled', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');

    // master tokens that every tile and section card read
    for (const token of ['--tile-radius', '--tile-pad', '--tile-min-height', '--tile-font', '--group-pad']) {
      expect(css).toContain(token + ':');
    }

    // the chosen tile: the header's active tab -- accent fill, white text, bold
    const ruleAt = css.indexOf('.option-tile[aria-pressed="true"] {');
    expect(ruleAt).toBeGreaterThan(-1);
    const pressedBlock = css.slice(css.lastIndexOf('/*', ruleAt), css.indexOf('}', ruleAt));
    expect(pressedBlock).toContain('background-color: var(--accent-vermillion)');
    expect(pressedBlock).toContain('color: #fff');
    expect(pressedBlock).toContain('font-weight: 700');
    // and rose is the accent every theme starts from
    expect(css).not.toContain('--accent-vermillion: #c33d2e');

    // and the panels/tiles cannot declare a second chosen rule of their own
    expect(css.match(/\.option-tile\[aria-pressed="true"\]/g)).toHaveLength(1);

    // a disabled tile never glows
    expect(css).toContain('.option-tile:not([aria-pressed="true"]):not(:disabled)');
    expect(css).toMatch(/\.option-tile:disabled,[\s\S]*?box-shadow: none;/);
  });
});

describe('Surprise Me cover-length slider', () => {
  it('is a labelled, styled range control, not an unstyled appearance-none bar', () => {
    render(<Harness onChange={vi.fn()} />);

    const slider = screen.getByRole('slider', { name: /cover length/i });
    expect(slider).toHaveAttribute('type', 'range');
    expect(slider).toHaveAttribute('min', '50');
    expect(slider).toHaveAttribute('max', '70');
    // appearance-none without thumb rules paints no thumb at all.
    expect(slider.className).toContain('settings-range');
    expect(slider.className).not.toContain('appearance-none');

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
    for (const rule of [
      '.settings-range::-webkit-slider-runnable-track',
      '.settings-range::-webkit-slider-thumb',
      '.settings-range::-moz-range-track',
      '.settings-range::-moz-range-thumb'
    ]) {
      expect(css).toContain(rule);
    }
  });

  it('fills the track from the current value inside the 50-70 band', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    const slider = screen.getByRole('slider', { name: /cover length/i });
    expect(slider).toHaveValue('60');
    expect(slider.style.getPropertyValue('--range-pct')).toBe('50%');

    fireEvent.change(slider, { target: { value: '70' } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ surpriseImageLength: 70 })
    );
    expect(slider.style.getPropertyValue('--range-pct')).toBe('100%');
  });

  it('clamps a stale stored value into the band instead of overflowing the track', () => {
    render(
      <SettingsModal
        settings={{ ...DEFAULT_SETTINGS, surpriseImageLength: 100 }}
        setSettings={vi.fn()}
        isOpen
        onClose={vi.fn()}
      />
    );

    const slider = screen.getByRole('slider', { name: /cover length/i });
    expect(slider).toHaveValue('70');
    expect(slider.style.getPropertyValue('--range-pct')).toBe('100%');
  });
});

describe('scrollbar stays inside the rounded panel', () => {
  it('scrolls on an inner body, not on the rounded shell', () => {
    const { container } = render(<Harness onChange={vi.fn()} />);

    const body = container.querySelector('.panel-scroll');
    expect(body).not.toBeNull();

    const shell = body.parentElement;
    // The rounded, clipped frame owns the curve; the scroll body is plain.
    expect(shell.className).toContain('rounded-3xl');
    expect(shell.className).toContain('overflow-hidden');
    expect(shell.className).not.toContain('overflow-y-auto');
    expect(body.className).not.toContain('rounded-3xl');

    // The header stays put and only the settings below it scroll.
    expect(shell.firstElementChild.contains(body)).toBe(false);

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
    expect(css).toContain('.panel-scroll {');
  });
});
