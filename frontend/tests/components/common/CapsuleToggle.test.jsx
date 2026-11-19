import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CapsuleToggle from '@/components/common/CapsuleToggle';

const OPTIONS = [
  { id: 'manga', label: 'Manga' },
  { id: 'manhwa', label: 'Manhwa' },
  { id: 'manhua', label: 'Manhua' }
];

const indicatorOf = (container) => container.querySelector('[data-capsule-indicator]');

describe('CapsuleToggle (the one toggle)', () => {
  it('renders every option inside one capsule, in order', () => {
    const { container } = render(
      <CapsuleToggle label="Format" options={OPTIONS} value="manga" onChange={vi.fn()} />
    );

    const capsule = screen.getByRole('group', { name: 'Format' });
    expect(capsule.className).toMatch(/rounded-full/);
    expect(Array.from(capsule.querySelectorAll('button')).map(node => node.textContent)).toEqual([
      'Manga',
      'Manhwa',
      'Manhua'
    ]);
    expect(capsule.contains(indicatorOf(container))).toBe(true);
  });

  it('slides one highlight by whole slots and reports the pressed option', () => {
    const onChange = vi.fn();
    const { container, rerender } = render(
      <CapsuleToggle label="Format" options={OPTIONS} value="manga" onChange={onChange} />
    );

    expect(indicatorOf(container).style.transform).toBe('translateX(0%)');
    expect(indicatorOf(container).className).toMatch(/transition-transform/);
    expect(indicatorOf(container).className).toMatch(/duration-300/);

    rerender(<CapsuleToggle label="Format" options={OPTIONS} value="manhwa" onChange={onChange} />);
    expect(indicatorOf(container).style.transform).toBe('translateX(100%)');

    rerender(<CapsuleToggle label="Format" options={OPTIONS} value="manhua" onChange={onChange} />);
    expect(indicatorOf(container).style.transform).toBe('translateX(200%)');

    fireEvent.click(screen.getByRole('button', { name: 'Manhwa' }));
    expect(onChange).toHaveBeenCalledWith('manhwa');
  });

  it('uses aria-pressed for a state switch and aria-current for navigation', () => {
    const { rerender } = render(
      <CapsuleToggle label="Format" options={OPTIONS} value="manhwa" onChange={vi.fn()} />
    );

    expect(screen.getByRole('button', { name: 'Manhwa' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Manga' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Manhwa' })).not.toHaveAttribute('aria-current');

    rerender(
      <CapsuleToggle label="Tabs" options={OPTIONS} value="manhwa" onChange={vi.fn()} active="current" />
    );

    // Tabs announce a page, not a pressed state.
    expect(screen.getByRole('button', { name: 'Manhwa' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('button', { name: 'Manhwa' })).not.toHaveAttribute('aria-pressed');
  });

  it('carries an icon and a badge without changing the slot maths', () => {
    const { container } = render(
      <CapsuleToggle
        label="Tabs"
        options={[
          { id: 'explore', label: 'Explore', icon: <span data-icon="">i</span> },
          { id: 'saved', label: 'Saved', badge: 3 }
        ]}
        value="saved"
        onChange={vi.fn()}
        active="current"
      />
    );

    expect(container.querySelectorAll('[data-icon]')).toHaveLength(1);
    expect(screen.getByText('3')).toBeTruthy();
    // Two options: the highlight is half the track, one slot to the right.
    // The browser normalises the calc; either spelling means "one of two slots".
    expect(indicatorOf(container).style.width.replace(/\s/g, '')).toBe('calc(50%-0.25rem)');
    // Equal slots come from the grid, so no label is truncated to fit them.
    expect(screen.getByRole('button', { name: /Explore/ }).className).toMatch(/w-full/);
    expect(container.querySelector('.truncate')).toBeNull();
    expect(indicatorOf(container).style.transform).toBe('translateX(100%)');
  });

  it('offers the two documented sizes and accent tokens', () => {
    const { container, rerender } = render(
      <CapsuleToggle label="Format" options={OPTIONS} value="manga" onChange={vi.fn()} size="sm" />
    );
    expect(indicatorOf(container).className).toMatch(/accent-vermillion/);
    expect(screen.getByRole('button', { name: 'Manga' }).className).toMatch(/uppercase/);

    rerender(
      <CapsuleToggle label="Format" options={OPTIONS} value="manga" onChange={vi.fn()} size="md" accent="indigo" />
    );
    expect(indicatorOf(container).className).toMatch(/accent-indigo/);
    expect(screen.getByRole('button', { name: 'Manga' }).className).not.toMatch(/uppercase/);
  });

  it('never navigates: it is buttons, not links', () => {
    render(<CapsuleToggle label="Format" options={OPTIONS} value="manga" onChange={vi.fn()} />);

    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.getAllByRole('button')).toHaveLength(3);
  });
});
