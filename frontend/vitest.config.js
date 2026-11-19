import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Test-only config. It deliberately does not extend `vite.config.js`: the dev
// proxy and the dashboard/manual-chunk build options are irrelevant here, and a
// separate file keeps `npm run build` behaviour untouched.
//
// Tests live in `tests/` (mirroring `src/`) and import application code through
// the `@` alias so a test can move without a chain of `../..` paths.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './tests/setup.js',
    include: ['tests/**/*.test.{js,jsx}'],
    restoreMocks: true,
    unstubGlobals: true
  }
});
