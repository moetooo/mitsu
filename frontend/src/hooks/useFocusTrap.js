import { useEffect } from 'react';

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(', ');

function focusableWithin(container) {
  // jsdom has no layout, so visibility (offsetParent) cannot be used as a
  // filter here; a real browser hides the rest from the tab order itself.
  return Array.from(container.querySelectorAll(FOCUSABLE_SELECTOR)).filter(
    (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true'
  );
}

// Keeps Tab inside an overlay, parks the initial focus on the dialog container
// (so a screen reader announces it before its first button), and returns focus
// to whatever opened the overlay when it closes.
export default function useFocusTrap(active, containerRef) {
  useEffect(() => {
    if (!active) return undefined;
    const container = containerRef.current;
    if (!container) return undefined;

    const previouslyFocused = document.activeElement;
    container.focus({ preventScroll: true });

    const handleKeyDown = (event) => {
      if (event.key !== 'Tab') return;

      const items = focusableWithin(container);
      if (items.length === 0) {
        event.preventDefault();
        container.focus({ preventScroll: true });
        return;
      }

      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      const inside = container.contains(current);

      if (event.shiftKey) {
        if (!inside || current === first || current === container) {
          event.preventDefault();
          last.focus();
        }
      } else if (!inside || current === container || current === last) {
        event.preventDefault();
        first.focus();
      }
    };

    container.addEventListener('keydown', handleKeyDown);

    return () => {
      container.removeEventListener('keydown', handleKeyDown);
      if (previouslyFocused && previouslyFocused.isConnected && typeof previouslyFocused.focus === 'function') {
        previouslyFocused.focus({ preventScroll: true });
      }
    };
  }, [active, containerRef]);
}
