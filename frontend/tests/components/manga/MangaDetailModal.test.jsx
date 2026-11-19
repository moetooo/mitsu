import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { act } from 'react';
import MangaDetailModal from '@/components/manga/MangaDetailModal';
import SettingsModal from '@/components/controls/SettingsModal';
import useEscapeLayer, { __resetEscapeLayersForTests } from '@/hooks/useEscapeLayer';
import { __resetScrollLockForTests } from '@/hooks/useScrollLock';

const MANGA = {
  id: 7,
  title: 'Vinland Saga',
  cover_image_url: null,
  banner_image: null,
  synopsis: 'A revenge story.',
  genres: ['Action'],
  tags: []
};

const FOCUSABLE = 'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

function LowerLayer({ onEscape }) {
  useEscapeLayer(true, onEscape);
  return <div data-testid="lower-layer" />;
}

async function renderModal(onClose = vi.fn(), extra = null) {
  const result = render(
    <>
      {extra}
      <MangaDetailModal
        manga={MANGA}
        onClose={onClose}
        onSelectTag={vi.fn()}
        onSelectManga={vi.fn()}
        isBookmarked={false}
        onToggleBookmark={vi.fn()}
      />
    </>
  );
  // The `/similar` fetch resolves on a microtask; flushing it inside act keeps
  // its state writes out of the act warnings.
  await act(async () => {});
  return result;
}

beforeEach(() => {
  __resetEscapeLayersForTests();
  __resetScrollLockForTests();
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve([]) })));
});

afterEach(() => {
  document.body.style.overflow = '';
  document.documentElement.style.overflow = '';
});

describe('MangaDetailModal accessibility (FE-08)', () => {
  it('is a modal dialog named by the title and takes focus on open', async () => {
    await renderModal();

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAccessibleName('Vinland Saga');
    expect(dialog).toHaveFocus();
  });

  it('keeps Tab inside the dialog, wrapping at both ends', async () => {
    await renderModal();
    const dialog = screen.getByRole('dialog');
    const items = dialog.querySelectorAll(FOCUSABLE);
    const first = items[0];
    const last = items[items.length - 1];

    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(first).toHaveFocus();

    last.focus();
    fireEvent.keyDown(last, { key: 'Tab' });
    expect(first).toHaveFocus();

    first.focus();
    fireEvent.keyDown(first, { key: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();
  });

  it('returns focus to the trigger when it closes', async () => {
    const trigger = render(<button type="button">open card</button>).getByRole('button');
    trigger.focus();

    const { unmount } = await renderModal();
    expect(trigger).not.toHaveFocus();

    unmount();
    expect(trigger).toHaveFocus();
  });
});

describe('Escape ownership (FE-08)', () => {
  it('closes only the topmost layer as layers unwind', async () => {
    const lower = vi.fn();
    const onClose = vi.fn();

    // The lower layer mounts first, so it is underneath the dialog.
    render(<LowerLayer onEscape={lower} />);
    const modal = await renderModal(onClose);

    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(lower).not.toHaveBeenCalled();

    modal.unmount();
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(lower).toHaveBeenCalledTimes(1);
  });
});

describe('scroll lock (FE-13)', () => {
  it('restores the previous inline overflow instead of unsets it', async () => {
    document.body.style.overflow = 'scroll';
    document.documentElement.style.overflow = 'visible';

    const { unmount } = await renderModal();
    expect(document.body.style.overflow).toBe('hidden');

    unmount();
    expect(document.body.style.overflow).toBe('scroll');
    // <html> carries `overflow-y: scroll` in index.css, so locking only the body
    // left the page scrollable behind the modal.
    expect(document.documentElement.style.overflow).toBe('visible');
  });

  it('locks the root scroller too, so the page cannot scroll behind the panel', async () => {
    document.body.style.overflow = 'scroll';
    document.documentElement.style.overflow = 'visible';

    const { unmount } = await renderModal();
    expect(document.documentElement.style.overflow).toBe('hidden');

    unmount();
    expect(document.documentElement.style.overflow).toBe('visible');
  });

  it('does not unlock while a second overlay is still open', async () => {
    document.body.style.overflow = 'scroll';

    const detail = await renderModal();
    const settings = render(
      <SettingsModal settings={{}} setSettings={vi.fn()} isOpen onClose={vi.fn()} />
    );

    detail.unmount();
    expect(document.body.style.overflow).toBe('hidden');

    settings.unmount();
    expect(document.body.style.overflow).toBe('scroll');
  });
});

describe('You Might Also Like rail', () => {
  const SIMILAR = [
    {
      id: 99,
      title: 'Gachiakuta',
      cover_image_url: null,
      format_type: 'MANGA',
      start_year: 2022,
      status: 'RELEASING',
      average_score: 81
    }
  ];

  function renderWithRail(props = {}) {
    return render(
      <MangaDetailModal
        manga={MANGA}
        onClose={vi.fn()}
        onSelectTag={vi.fn()}
        onSelectManga={vi.fn()}
        isBookmarked={false}
        onToggleBookmark={vi.fn()}
        {...props}
      />
    );
  }

  it('keeps the compact cover tile and opens the full page from its end tile', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(SIMILAR) }))
    );
    const onOpenSimilar = vi.fn();

    renderWithRail({ onOpenSimilar });
    await act(async () => {});

    expect(screen.getByText('You Might Also Like')).toBeTruthy();
    // A rail is a preview strip: the tile is the cover and its title, not a
    // second result card (no year / status / rating line).
    expect(screen.getByText('Gachiakuta')).toBeTruthy();
    expect(screen.queryByText('2022')).toBeNull();
    expect(screen.queryByText(/RELEASING/)).toBeNull();
    const tile = screen.getByRole('button', { name: 'Load more similar titles' });
    fireEvent.click(tile);
    expect(onOpenSimilar).toHaveBeenCalledWith(MANGA.id);
  });

  it('names the record by its real format in the bar', async () => {
    const { container, unmount } = render(
      <MangaDetailModal
        manga={{ ...MANGA, format_type: 'MANHWA' }}
        onClose={vi.fn()}
        onSelectManga={vi.fn()}
        isBookmarked={false}
        onToggleBookmark={vi.fn()}
      />
    );
    await act(async () => {});
    expect(screen.getByText('Manhwa Details')).toBeTruthy();
    unmount();

    const second = render(
      <MangaDetailModal
        manga={{ ...MANGA, format_type: 'MANGA' }}
        onClose={vi.fn()}
        onSelectManga={vi.fn()}
        isBookmarked={false}
        onToggleBookmark={vi.fn()}
      />
    );
    await act(async () => {});
    expect(screen.getByText('Manga Details')).toBeTruthy();
    expect(container).toBeTruthy();
    second.unmount();
  });

  it('puts no genre stamp beside the cover', async () => {
    const { container } = renderWithRail();
    await act(async () => {});

    expect(screen.queryByText(/^GENRES$/)).toBeNull();
    expect(container.querySelector('.vertical-text')).toBeNull();
  });

  it('hides the tile when the rail is empty or the page cannot navigate', async () => {
    renderWithRail();
    await act(async () => {});

    expect(screen.queryByRole('button', { name: 'Load more similar titles' })).toBeNull();
  });
});

describe('AI-inferred narrative block', () => {
  it('is not rendered even when the payload carries inferred_tags', async () => {
    render(
      <MangaDetailModal
        manga={{
          ...MANGA,
          inferred_tags: [{ name: 'Revenge', category: 'trope', confidence: 0.9 }]
        }}
        onClose={vi.fn()}
        onSelectTag={vi.fn()}
        onSelectManga={vi.fn()}
        isBookmarked={false}
        onToggleBookmark={vi.fn()}
      />
    );
    await act(async () => {});

    expect(screen.queryByText('Story & Narrative Elements')).toBeNull();
    expect(screen.queryByText(/AI Inferred/)).toBeNull();
  });
});

describe('scrollbar stays inside the rounded panel', () => {
  it('scrolls on an inner .panel-scroll body, clipped by the rounded shell', async () => {
    await renderModal();

    const body = screen.getByRole('dialog').querySelector('.panel-scroll');
    expect(body).not.toBeNull();
    expect(body.className).not.toContain('overflow-y-auto');

    const shell = body.parentElement;
    expect(shell.className).toContain('rounded-3xl');
    expect(shell.className).toContain('overflow-hidden');
  });
});
