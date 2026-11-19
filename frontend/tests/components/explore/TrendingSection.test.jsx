import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import TrendingSection from '@/components/explore/TrendingSection';

const items = (from, count) =>
  Array.from({ length: count }, (_, i) => ({
    id: from + i,
    title: `Title ${from + i}`,
    cover_image_url: null,
    average_score: 80,
    start_year: 2018,
    genres: [],
    tags: []
  }));

describe('TrendingSection', () => {
  it('is a word, a hairline, a format toggle and a rail of ten', () => {
    const { container } = render(
      <TrendingSection
        items={items(1, 10)}
        format="manga"
        onChangeFormat={vi.fn()}
        onSelect={vi.fn()}
      />
    );

    const section = screen.getByRole('region', { name: 'Trending' });
    expect(within(section).getByRole('heading', { name: 'Trending' })).toBeTruthy();
    // The rule under the word, not a decorative glyph.
    expect(container.querySelector('.h-px')).toBeTruthy();
    expect(within(section).getByText('Title 1')).toBeTruthy();
    expect(within(section).getByText('Title 10')).toBeTruthy();
    expect(screen.getAllByText(/^Title /)).toHaveLength(10);
  });

  it('keeps the highlight inside one capsule and slides it between slots', () => {
    const { container, rerender } = render(
      <TrendingSection items={items(1, 10)} format="manga" onChangeFormat={vi.fn()} onSelect={vi.fn()} />
    );

    const indicator = container.querySelector('[data-capsule-indicator]');
    expect(indicator).toBeTruthy();
    // The section uses the shared capsule: one bordered pill with the highlight
    // inside it, not a background painted onto each button.
    const capsule = screen.getByRole('group', { name: 'Trending format' });
    expect(capsule.className).toMatch(/rounded-full/);
    expect(capsule.contains(indicator)).toBe(true);
    expect(indicator.style.transform).toBe('translateX(0%)');
    expect(indicator.className).toMatch(/transition-transform/);

    rerender(
      <TrendingSection items={items(1, 10)} format="manhua" onChangeFormat={vi.fn()} onSelect={vi.fn()} />
    );
    // Two slots to the right for the third label.
    expect(container.querySelector('[data-capsule-indicator]').style.transform).toBe('translateX(200%)');
  });

  it('switches format from the toggle without any navigation', () => {
    const onChangeFormat = vi.fn();
    render(
      <TrendingSection items={items(1, 10)} format="manga" onChangeFormat={onChangeFormat} onSelect={vi.fn()} />
    );

    const toggle = screen.getByRole('group', { name: 'Trending format' });
    const labels = Array.from(toggle.querySelectorAll('button')).map(node => node.textContent);
    expect(labels).toEqual(['Manga', 'Manhwa', 'Manhua']);
    expect(within(toggle).getByRole('button', { name: 'Manga' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(within(toggle).getByRole('button', { name: 'Manhwa' }));
    expect(onChangeFormat).toHaveBeenCalledWith('manhwa');
    // The section must not send the browser anywhere.
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('has no Load More tile: the ten covers are the whole answer', () => {
    render(
      <TrendingSection items={items(1, 10)} format="manga" onChangeFormat={vi.fn()} onSelect={vi.fn()} />
    );

    expect(screen.queryByRole('button', { name: /see all trending titles/i })).toBeNull();
    expect(screen.queryByText('Load More')).toBeNull();
  });

  it('shows ten skeletons while the format is in flight', () => {
    const { container } = render(
      <TrendingSection items={[]} loading format="manhwa" onChangeFormat={vi.fn()} onSelect={vi.fn()} />
    );

    expect(container.querySelectorAll('.shimmer-paper-loading')).toHaveLength(10);
    // The heading and the toggle still say what is coming.
    expect(screen.getByRole('heading', { name: 'Trending' })).toBeTruthy();
  });

  it('renders nothing at all when the fetch came back empty', () => {
    const { container } = render(
      <TrendingSection items={[]} loading={false} format="manga" onChangeFormat={vi.fn()} onSelect={vi.fn()} />
    );

    expect(container.querySelector('[aria-labelledby="trending-heading"]')).toBeNull();
  });

  it('opens the title when a cover is clicked', () => {
    const onSelect = vi.fn();
    render(<TrendingSection items={items(1, 10)} format="manga" onChangeFormat={vi.fn()} onSelect={onSelect} />);

    fireEvent.click(screen.getByText('Title 3'));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }));
  });
});
