import { useEffect } from 'react';

// One lock for the whole document. Two overlays can be open at once (the
// detail modal on top of the Surprise Me pane), so the lock is counted rather
// than toggled: the first owner saves the previous inline value and the last
// one to leave restores it. Setting `overflow = 'unset'` on close (the old
// MangaDetailModal behaviour) clobbered whatever the page had before, and
// closing the modal while the settings modal was still open unlocked the page
// underneath it.
let lockCount = 0;
let savedOverflow = '';
let savedRootOverflow = '';

export default function useScrollLock(active) {
  useEffect(() => {
    if (!active) return undefined;

    if (lockCount === 0) {
      savedOverflow = document.body.style.overflow;
      savedRootOverflow = document.documentElement.style.overflow;
      document.body.style.overflow = 'hidden';
      // `index.css` gives <html> `overflow-y: scroll` so the gutter never jumps.
      // With an explicit root overflow the body lock alone does not stop the
      // page: the root keeps its own scroll container, so a wheel over the
      // backdrop scrolled the page behind the settings panel. Lock both.
      document.documentElement.style.overflow = 'hidden';
    }
    lockCount += 1;

    return () => {
      lockCount -= 1;
      if (lockCount <= 0) {
        lockCount = 0;
        document.body.style.overflow = savedOverflow;
        document.documentElement.style.overflow = savedRootOverflow;
        savedOverflow = '';
        savedRootOverflow = '';
      }
    };
  }, [active]);
}

// Test-only seam: the module-level counter outlives a test file, so a suite
// that unmounts mid-lock must be able to reset it.
export function __resetScrollLockForTests() {
  lockCount = 0;
  savedOverflow = '';
  savedRootOverflow = '';
  document.body.style.overflow = '';
  document.documentElement.style.overflow = '';
}
