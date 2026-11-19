import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import SearchBar from '@/components/controls/SearchBar';

function props(overrides = {}) {
  return {
    query: '',
    setQuery: vi.fn(),
    onSearch: vi.fn(),
    loading: false,
    isFilterOpen: false,
    setIsFilterOpen: vi.fn(),
    hasActiveFilters: false,
    ...overrides
  };
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('mitsu_recent_queries', JSON.stringify(['naruto', 'bleach']));
});

afterEach(() => {
  localStorage.clear();
});

describe('SearchBar combobox semantics (FE-20)', () => {
  it('exposes the input as a combobox that controls a listbox of recent searches', () => {
    render(<SearchBar {...props()} />);

    const input = screen.getByRole('combobox');
    expect(input).toHaveAttribute('aria-autocomplete', 'list');
    expect(input).toHaveAttribute('aria-expanded', 'false');

    fireEvent.focus(input);

    expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'true');
    const listbox = screen.getByRole('listbox', { name: 'Recent searches' });
    expect(screen.getByRole('combobox')).toHaveAttribute('aria-controls', listbox.id);
    expect(within(listbox).getAllByRole('option')).toHaveLength(2);
  });

  it('moves the active option with the arrow keys and runs it on Enter', () => {
    const onSearch = vi.fn();
    render(<SearchBar {...props({ onSearch })} />);
    const input = screen.getByRole('combobox');

    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(input).toHaveAttribute('aria-activedescendant', 'searchbar-recent-option-0');

    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(input).toHaveAttribute('aria-activedescendant', 'searchbar-recent-option-1');

    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(input).toHaveAttribute('aria-activedescendant', 'searchbar-recent-option-0');

    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onSearch).toHaveBeenCalledWith(null, 'naruto');
  });

  it('closes the listbox on Escape without leaking the key to the page behind', () => {
    render(<SearchBar {...props()} />);
    const input = screen.getByRole('combobox');
    const behind = vi.fn();
    window.addEventListener('keydown', behind);

    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: 'Escape' });

    expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(behind).not.toHaveBeenCalled();

    window.removeEventListener('keydown', behind);
  });
});

describe('SearchBar blur timer (FE-20)', () => {
  it('cancels the pending close timer on unmount', () => {
    vi.useFakeTimers();
    try {
      const { unmount } = render(<SearchBar {...props()} />);
      const input = screen.getByRole('combobox');

      fireEvent.focus(input);
      fireEvent.blur(input);
      expect(vi.getTimerCount()).toBeGreaterThan(0);

      unmount();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('SearchBar entry points', () => {
  it('offers no Surprise Me button: the tab bar is the only way in', () => {
    // The drawer is not the only place a second entry point hid: this button
    // duplicated the Surprise Me tab, sat inside the search form (so clicking it
    // could submit the query instead) and was hidden under 640px anyway.
    render(<SearchBar {...props()} />);

    expect(screen.queryByRole('button', { name: /surprise/i })).toBeNull();
    // The bar still has exactly its own controls: filters, submit, search box.
    expect(screen.getByRole('button', { name: /filters/i })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Search' })).toBeTruthy();
    expect(screen.getByRole('combobox')).toBeTruthy();
  });
});
