import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { act } from 'react';
import MangaDetailModal from './MangaDetailModal';
import SettingsModal from './SettingsModal';
import useEscapeLayer, { __resetEscapeLayersForTests } from '../hooks/useEscapeLayer';
import { __resetScrollLockForTests } from '../hooks/useScrollLock';

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

    const { unmount } = await renderModal();
    expect(document.body.style.overflow).toBe('hidden');

    unmount();
    expect(document.body.style.overflow).toBe('scroll');
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
