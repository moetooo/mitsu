import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CoverRail from '@/components/manga/CoverRail';

const items = [
  { id: 1, title: 'Chainsaw Man', cover_image_url: 'https://example.test/1.jpg' },
  { id: 2, title: 'Solo Leveling', cover_image_url: 'https://example.test/2.jpg' }
];

beforeEach(() => {
  localStorage.clear();
});

describe('CoverRail (shared rail shell)', () => {
  it('renders one tile per item, with the title as the accessible name', () => {
    render(<CoverRail items={items} onSelect={vi.fn()} />);

    expect(screen.getByAltText('Chainsaw Man')).toBeTruthy();
    expect(screen.getByAltText('Solo Leveling')).toBeTruthy();
    expect(screen.getByText('Chainsaw Man')).toBeTruthy();
  });

  it('shows skeletons while loading and no tiles', () => {
    const { container } = render(<CoverRail items={items} loading onSelect={vi.fn()} />);

    expect(screen.queryByAltText('Chainsaw Man')).toBeNull();
    expect(container.querySelectorAll('.shimmer-paper-loading')).toHaveLength(4);
  });

  it('renders the action tile and calls it — a rail navigates, it never paginates in place', () => {
    const onAction = vi.fn();
    render(<CoverRail items={items} onSelect={vi.fn()} onAction={onAction} />);

    const action = screen.getByRole('button', { name: 'Load more' });
    expect(action.textContent).toContain('Load More');

    fireEvent.click(action);
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('omits the action tile when the rail has no destination', () => {
    render(<CoverRail items={items} onSelect={vi.fn()} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders the empty line only when it is given one', () => {
    const { rerender } = render(<CoverRail items={[]} onSelect={vi.fn()} />);
    expect(screen.queryByText(/no titles/i)).toBeNull();

    rerender(<CoverRail items={[]} onSelect={vi.fn()} emptyLabel="No similar titles found." />);
    expect(screen.getByText('No similar titles found.')).toBeTruthy();
  });

  it('hands the clicked item back to the caller', () => {
    const onSelect = vi.fn();
    render(<CoverRail items={items} onSelect={onSelect} />);

    fireEvent.click(screen.getByText('Solo Leveling'));
    expect(onSelect).toHaveBeenCalledWith(items[1]);
  });
});
