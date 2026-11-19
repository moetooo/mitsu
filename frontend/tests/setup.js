import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

import { setCoverReportingEnabled } from '@/utils/coverReports';

// A broken cover in a test would otherwise POST to the API. The reporting path has
// its own test (coverReports.test.js) that turns it back on with a stubbed fetch.
setCoverReportingEnabled(false);

// jsdom implements neither observer. Components register them in effects, so
// without these the render throws instead of merely never intersecting.
if (!globalThis.IntersectionObserver) {
  globalThis.IntersectionObserver = class {
    constructor(callback) {
      this.callback = callback;
    }
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  };
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

afterEach(() => {
  cleanup();
});
