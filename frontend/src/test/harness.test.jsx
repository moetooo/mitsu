import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

// Smoke test for the harness itself (QA-05): proves jsdom, React 19 and the
// jest-dom matchers are wired before any component test relies on them.
describe('frontend test harness', () => {
  it('renders a component and exposes jest-dom matchers', () => {
    render(<p role="status">harness ready</p>);
    expect(screen.getByRole('status')).toHaveTextContent('harness ready');
  });
});
