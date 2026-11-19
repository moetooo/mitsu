import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBanner from '@/components/common/ErrorBanner';

// FE-25: a failed fetch used to render as "No titles found." — the same screen a
// genuine empty result produces.
describe('ErrorBanner (FE-25)', () => {
  it('renders nothing when there is no error', () => {
    const { container } = render(<ErrorBanner message={null} onRetry={vi.fn()} />);
    expect(container.innerHTML).toBe('');
  });

  it('announces the failure and offers the retry that can fix it', () => {
    const onRetry = vi.fn();
    render(<ErrorBanner message="The catalogue did not answer." label="Catalogue unavailable" onRetry={onRetry} />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Catalogue unavailable');
    expect(alert).toHaveTextContent('The catalogue did not answer.');

    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('can report without a retry action', () => {
    render(<ErrorBanner message="Superseded." />);
    expect(screen.getByRole('alert')).toHaveTextContent('Superseded.');
    expect(screen.queryByRole('button')).toBeNull();
  });
});