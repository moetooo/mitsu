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

export default function useScrollLock(active) {
  useEffect(() => {
    if (!active) return undefined;

    if (lockCount === 0) {
      savedOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
    }
    lockCount += 1;

    return () => {
      lockCount -= 1;
      if (lockCount <= 0) {
        lockCount = 0;
        document.body.style.overflow = savedOverflow;
        savedOverflow = '';
      }
    };
  }, [active]);
}

// Test-only seam: the module-level counter outlives a test file, so a suite
// that unmounts mid-lock must be able to reset it.
export function __resetScrollLockForTests() {
  lockCount = 0;
  savedOverflow = '';
  document.body.style.overflow = '';
}
