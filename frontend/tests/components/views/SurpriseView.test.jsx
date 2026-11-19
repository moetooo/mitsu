import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen, fireEvent, act } from '@testing-library/react';
import SurpriseView from '@/components/views/SurpriseView';

// FE-10: the view must not own the queue, the seen ids or the refill timer.
// These tests pin the contract it now has: it renders `items`, asks for more via
// `onNeedMore`, keys the peek accordion by manga id (FE-16), and shows a failed
// draw differently from an empty one (FE-25).

const makeItem = (id, title) => ({
  id,
  title,
  cover_image_url: null,
  synopsis: 'A synopsis.',
  score: 8.2,
  genres: ['Action'],
  release_year: 2020,
});

const renderView = (props = {}) =>
  render(
    <SurpriseView
      items={[makeItem(1, 'First Title'), makeItem(2, 'Second Title')]}
      loading={false}
      onNeedMore={vi.fn().mockResolvedValue([])}
      onToggleBookmark={vi.fn()}
      {...props}
    />
  );

const pressArrowDown = () =>
  act(() => {
    fireEvent.keyDown(window, { key: 'ArrowDown', code: 'ArrowDown' });
  });

describe('SurpriseView queue contract (FE-10)', () => {
  it('renders the items it is given and asks the owner for more via onNeedMore', () => {
    const onNeedMore = vi.fn().mockResolvedValue([]);
    renderView({ onNeedMore });

    expect(screen.getAllByText('First Title').length).toBeGreaterThan(0);
    // Two items in hand and four wanted ahead, so the first render asks once —
    // with a count, not an endpoint of its own.
    expect(onNeedMore).toHaveBeenCalledTimes(1);
    expect(onNeedMore).toHaveBeenCalledWith(5);
  });

  it('does not fetch on its own and keeps the index inside the queue', () => {
    const onNeedMore = vi.fn().mockResolvedValue([]);
    const { rerender } = renderView({ onNeedMore });
    onNeedMore.mockClear();

    pressArrowDown();
    expect(screen.getAllByText('Second Title').length).toBeGreaterThan(0);

    // A fresh draw shrinks the queue; the index must not point past its end.
    rerender(
      <SurpriseView items={[makeItem(9, 'Only Title')]} loading={false} onNeedMore={onNeedMore} />
    );
    expect(screen.getAllByText('Only Title').length).toBeGreaterThan(0);
  });

  it('cannot release a second batch while one is in flight', async () => {
    let release;
    const onNeedMore = vi.fn(() => new Promise(resolve => { release = resolve; }));
    renderView({ onNeedMore });

    expect(onNeedMore).toHaveBeenCalledTimes(1);
    pressArrowDown();
    pressArrowDown();
    expect(onNeedMore).toHaveBeenCalledTimes(1);

    await act(async () => {
      release([]);
    });
  });
});

describe('SurpriseView peek accordion (FE-16)', () => {
  beforeEach(() => {
    window.innerWidth = 500;
  });

  it('opens the peek on the card it was clicked on, not on the next card', () => {
    const { container } = renderView();
    const peeks = () => Array.from(container.querySelectorAll('.card-details-peek'));

    expect(peeks()[0].className).not.toContain('is-expanded');

    // Clicking the peek header toggles the card's own accordion; the
    // "Full Details" button below it opens the dossier instead.
    fireEvent.click(peeks()[0].parentElement);
    expect(peeks()[0].className).toContain('is-expanded');

    pressArrowDown();
    // The state followed the id, so the second card starts collapsed.
    expect(peeks()[1].className).not.toContain('is-expanded');
  });
});

describe('SurpriseView selectable text', () => {
  beforeEach(() => {
    window.innerWidth = 500;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('keeps the title and synopsis selectable instead of suppressing selection', () => {
    const { container } = renderView();
    const peek = container.querySelector('.card-details-peek');
    const card = peek.parentElement.parentElement;

    // The card, its cover wrapper and the dossier pane must not switch
    // selection off; copying a title is a normal thing to do on this card.
    expect(card.className).not.toContain('select-none');
    expect(card.querySelector('h3').className).toContain('select-text');
    expect(peek.querySelector('p').className).toContain('select-text');
  });

  it('treats a click that ended a copy drag as selection, not as a gesture', () => {
    const { container } = renderView();
    const peek = container.querySelector('.card-details-peek');
    const spy = vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'First Title' });

    fireEvent.click(peek.parentElement);

    expect(peek.className).not.toContain('is-expanded');
    spy.mockRestore();

    // With nothing selected, the same click still opens the peek.
    fireEvent.click(peek.parentElement);
    expect(peek.className).toContain('is-expanded');
  });

  it('does not slide to the next card when the touch drag selected text', () => {
    const { container } = renderView();
    const viewport = container.querySelector('#card-viewport');
    const track = viewport.firstElementChild;
    const before = track.style.transform;

    vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'First Title' });
    fireEvent.touchStart(viewport, { touches: [{ clientY: 400 }] });
    fireEvent.touchEnd(viewport, { changedTouches: [{ clientY: 100 }] });

    expect(track.style.transform).toBe(before);
  });
});

describe('SurpriseView empty, failed and exhausted states (FE-25)', () => {
  it('shows a failure with a retry instead of "Discovering Titles"', () => {
    const onRetry = vi.fn();
    renderView({ items: [], error: 'Could not reach the recommendation service.', onRetry });

    expect(screen.getByText('Could not draw a title')).toBeTruthy();
    expect(screen.queryByText('Discovering Titles...')).toBeNull();

    fireEvent.click(screen.getByText('Try again'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('still says nothing matched when the draw answered 404', () => {
    renderView({ items: [], exhausted: true });

    expect(screen.getByText('No titles match these filters')).toBeTruthy();
    expect(screen.queryByText('Try again')).toBeNull();
  });
});

describe('SurpriseView card meta (title + genre + year)', () => {
  it('shows the record genre and year under the title', () => {
    renderView();

    expect(screen.getAllByText('Action • 2020').length).toBeGreaterThan(0);
    expect(screen.getAllByText('#Action').length).toBeGreaterThan(0);
  });

  it('prefers the record year and never invents one', () => {
    render(
      <SurpriseView
        items={[
          {
            id: 7,
            title: 'Undated Title',
            cover_image_url: null,
            synopsis: 'A synopsis.',
            genres: [],
          },
        ]}
        loading={false}
        onNeedMore={vi.fn().mockResolvedValue([])}
        onToggleBookmark={vi.fn()}
      />
    );

    // No fabricated '2020' and no fabricated genre pills.
    expect(screen.queryByText(/2020/)).toBeNull();
    expect(screen.queryByText(/#Action/)).toBeNull();
    expect(screen.queryByText(/Supernatural/)).toBeNull();
  });

  it('falls back to start_year for the year, and to the format for the genre slot', () => {
    render(
      <SurpriseView
        items={[
          {
            id: 8,
            title: 'Fallback Title',
            cover_image_url: null,
            synopsis: 'A synopsis.',
            genres: [],
            start_year: 2018,
            format_type: 'MANGA',
          },
        ]}
        loading={false}
        onNeedMore={vi.fn().mockResolvedValue([])}
        onToggleBookmark={vi.fn()}
      />
    );

    expect(screen.getAllByText('MANGA • 2018').length).toBeGreaterThan(0);
  });
});

describe('SurpriseView manual layout values', () => {
  it('drives the text plate padding from SURPRISE_CARD_LAYOUT', async () => {
    const { SURPRISE_CARD_LAYOUT: L } = await import('@/utils/surpriseCardLayout');
    const { container } = renderView();

    const plate = container.querySelector('[data-card-plate]');
    expect(plate.style.padding).toBe(`${L.PLATE_TOP}px ${L.PLATE_SIDE}px ${L.PLATE_BOTTOM}px`);

    const reveal = container.querySelector('[data-card-reveal]');
    expect(reveal.style.gap).toBe(`${L.SECTION_GAP}px`);
  });

  it('drives title, meta and pill typography from SURPRISE_CARD_TEXT', async () => {
    const { SURPRISE_CARD_TEXT: T } = await import('@/utils/surpriseCardLayout');
    const { container } = renderView();

    const card = container.querySelector('[data-surprise-card]');
    expect(card.style.getPropertyValue('--surprise-title-size')).toBe(`${T.TITLE_SIZE_MOBILE}px`);
    expect(card.style.getPropertyValue('--surprise-title-size-sm')).toBe(`${T.TITLE_SIZE_DESKTOP}px`);
    expect(card.style.getPropertyValue('--surprise-title-weight')).toBe(String(T.TITLE_WEIGHT));
    expect(card.style.getPropertyValue('--surprise-title-tracking')).toBe(`${T.TITLE_TRACKING_EM}em`);
    expect(card.style.getPropertyValue('--surprise-title-lines')).toBe(String(T.TITLE_LINES));
    expect(card.style.getPropertyValue('--surprise-meta-size')).toBe(`${T.META_SIZE}px`);

    const meta = container.querySelector('[data-card-meta]');
    expect(meta.style.marginTop).toBe(`${T.META_OFFSET_Y}px`);

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
    expect(css).toContain('.surprise-card-title {');
    expect(css).toContain('.surprise-card-meta {');
  });

  it('drives the status pill, synopsis and action button from SURPRISE_CARD_TEXT', async () => {
    const { SURPRISE_CARD_TEXT: T } = await import('@/utils/surpriseCardLayout');
    const { container } = renderView();

    const card = container.querySelector('[data-surprise-card]');
    const vars = {
      '--surprise-status-size': `${T.STATUS_SIZE}px`,
      '--surprise-status-weight': String(T.STATUS_WEIGHT),
      '--surprise-status-tracking': `${T.STATUS_TRACKING_EM}em`,
      '--surprise-status-pad-x': `${T.STATUS_PAD_X}px`,
      '--surprise-status-pad-y': `${T.STATUS_PAD_Y}px`,
      '--surprise-status-radius': `${T.STATUS_RADIUS}px`,
      '--surprise-synopsis-size': `${T.SYNOPSIS_SIZE}px`,
      '--surprise-synopsis-leading': String(T.SYNOPSIS_LINE_HEIGHT),
      '--surprise-synopsis-lines-mobile': String(T.SYNOPSIS_LINES_MOBILE),
      '--surprise-synopsis-lines': String(T.SYNOPSIS_LINES_DESKTOP),
      '--surprise-button-size': `${T.BUTTON_SIZE}px`,
      '--surprise-button-weight': String(T.BUTTON_WEIGHT),
      '--surprise-button-tracking': `${T.BUTTON_TRACKING_EM}em`,
      '--surprise-button-pad-y': `${T.BUTTON_PAD_Y}px`,
      '--surprise-button-radius': `${T.BUTTON_RADIUS}px`
    };
    for (const [name, value] of Object.entries(vars)) {
      expect(card.style.getPropertyValue(name)).toBe(value);
    }

    expect(container.querySelector('.surprise-card-status')).not.toBeNull();
    expect(container.querySelector('.surprise-card-synopsis')).not.toBeNull();
    expect(container.querySelector('.surprise-card-action')).not.toBeNull();

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
    for (const rule of [
      '.surprise-card-status {',
      '.surprise-card-synopsis {',
      '.surprise-card-action {'
    ]) {
      expect(css).toContain(rule);
    }
  });
});

describe('SurpriseView expanded text position', () => {
  it('lowers the title / genre / year block by SURPRISE_CARD_LAYOUT.EXPANDED_DROP when the peek opens', async () => {
    const { SURPRISE_CARD_LAYOUT: L } = await import('@/utils/surpriseCardLayout');
    const { container } = renderView();

    const card = container.querySelector('[data-surprise-card]');
    expect(card.style.getPropertyValue('--surprise-expanded-drop')).toBe(`${L.EXPANDED_DROP}px`);

    // No separate movement layer: the plate itself holds the title and meta.
    const plate = container.querySelector('[data-card-plate]');
    expect(plate.querySelector('.surprise-card-title')).not.toBeNull();
    expect(plate.querySelector('[data-card-meta]')).not.toBeNull();

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
    expect(css).toContain('margin-top: calc(0.625rem - var(--surprise-expanded-drop, 0px))');
  });
});

describe('SurpriseView text placement', () => {
  it('keeps two positions for the title / genre / year block: rest and after hover', async () => {
    const { SURPRISE_CARD_TEXT: T } = await import('@/utils/surpriseCardLayout');
    const { container } = renderView();

    const card = container.querySelector('[data-surprise-card]');
    expect(card.style.getPropertyValue('--surprise-text-y')).toBe(`${T.TEXT_OFFSET_Y}px`);
    expect(card.style.getPropertyValue('--surprise-text-y-hover')).toBe(`${T.TEXT_OFFSET_Y_HOVER}px`);

    const text = container.querySelector('[data-card-text]');
    expect(text).not.toBeNull();
    // Both pieces of text sit inside the offset wrapper.
    expect(text.querySelector('.surprise-card-title')).not.toBeNull();
    expect(text.querySelector('[data-card-meta]')).not.toBeNull();
    // Two placements, not an animation.
    expect(text.className).not.toMatch(/transition|duration|animate/);

    const css = readFileSync(resolve(process.cwd(), 'src/index.css'), 'utf8');
    expect(css).toContain('transform: translateY(var(--surprise-text-y, 0px))');
    expect(css).toContain('var(--surprise-text-y-hover, var(--surprise-text-y, 0px))');
  });
});
