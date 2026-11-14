import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import SurpriseView from './SurpriseView';

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
