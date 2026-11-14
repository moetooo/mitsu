import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, act } from '@testing-library/react';
import App from './App';

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/');
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })));
});

describe('App tab and filter semantics (FE-30)', () => {
  it('marks the current tab and reports the active format and genre with aria-pressed', async () => {
    render(<App />);

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(nav).getByRole('button', { name: /explore/i })).toHaveAttribute('aria-current', 'page');

    fireEvent.click(within(nav).getByRole('button', { name: /trending/i }));
    await act(async () => {});

    expect(within(nav).getByRole('button', { name: /trending/i })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('button', { name: /explore/i })).not.toHaveAttribute('aria-current');

    const formatGroup = screen.getByRole('group', { name: 'Trending format' });
    expect(within(formatGroup).getByRole('button', { name: /all formats/i })).toHaveAttribute('aria-pressed', 'true');
    expect(within(formatGroup).getByRole('button', { name: /^manga/i })).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(within(formatGroup).getByRole('button', { name: /^manga/i }));
    await act(async () => {});

    expect(
      within(screen.getByRole('group', { name: 'Trending format' })).getByRole('button', { name: /^manga/i })
    ).toHaveAttribute('aria-pressed', 'true');

    const genreGroup = screen.getByRole('group', { name: 'Trending genre' });
    expect(within(genreGroup).getByRole('button', { name: 'All Genres' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(genreGroup).getByRole('button', { name: '#Romance' })).toHaveAttribute('aria-pressed', 'false');
  });
});

describe('App tab switching (FE-24)', () => {
  it('does not remount the tab container when the tab changes', async () => {
    const { container } = render(<App />);
    const before = container.querySelector('.animate-tab-fade-in');
    expect(before).toBeTruthy();

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    fireEvent.click(within(nav).getByRole('button', { name: /trending/i }));
    await act(async () => {});
    fireEvent.click(within(nav).getByRole('button', { name: /explore/i }));
    await act(async () => {});

    // Same DOM node: `key={activeTab}` used to rebuild it here, which reset any
    // state living inside a tab (the discovery queue used to be one of those).
    expect(container.querySelector('.animate-tab-fade-in')).toBe(before);
  });
});
