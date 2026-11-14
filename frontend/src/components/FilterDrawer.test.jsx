import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FilterDrawer from './FilterDrawer';

// FE-23: the drawer used to own a fourth copy of the genre taxonomy. It now
// renders whatever the served vocabulary gives it, and only falls back when it
// is given nothing.

const categories = [
  {
    id: 'genre',
    name: 'Served Genres',
    tagline: 'Story Archetypes',
    options: ['Kung Fu', 'Space Opera']
  },
  {
    id: 'setting',
    name: 'Settings & World',
    tagline: 'World & Setting',
    options: ['Floating Cities']
  }
];

const renderDrawer = (props = {}) =>
  render(
    <FilterDrawer
      filters={{ genres: [], exclude_genres: [] }}
      setFilters={vi.fn()}
      isOpen
      onClose={vi.fn()}
      onReset={vi.fn()}
      {...props}
    />
  );

describe('FilterDrawer vocabulary (FE-23)', () => {
  it('renders the groups it is handed, not a list of its own', () => {
    renderDrawer({ categories });

    // The name appears twice: once as the category tab, once as the section header.
    expect(screen.getAllByText('Served Genres').length).toBeGreaterThan(0);
    expect(screen.getByText('#Kung Fu')).toBeTruthy();
    expect(screen.getAllByText('Settings & World').length).toBeGreaterThan(0);
    expect(screen.getByText('#Floating Cities')).toBeTruthy();

    // Nothing the built-in fallback contains can leak into a served render.
    expect(screen.queryByText('Demographics')).toBeNull();
  });

  it('shows the served option count', () => {
    renderDrawer({ categories });
    expect(screen.getByText('(3)')).toBeTruthy();
  });

  it('falls back to the built-in list when given no groups', () => {
    renderDrawer({ categories: [] });

    expect(screen.getAllByText('Core Genres').length).toBeGreaterThan(0);
    expect(screen.getByText('#Action')).toBeTruthy();
  });

  it('includes and excludes a served option through the same filters', () => {
    const setFilters = vi.fn();
    renderDrawer({ categories, setFilters });

    fireEvent.click(screen.getByText('#Kung Fu'));
    expect(setFilters).toHaveBeenCalled();

    const updater = setFilters.mock.calls[0][0];
    expect(updater({ genres: [], exclude_genres: [] })).toEqual({
      genres: ['Kung Fu'],
      exclude_genres: []
    });
  });
});
