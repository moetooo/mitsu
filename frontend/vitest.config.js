import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Test-only config. It deliberately does not extend `vite.config.js`: the dev
// proxy and the dashboard/manual-chunk build options are irrelevant here, and a
// separate file keeps `npm run build` behaviour untouched.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.js',
    include: ['src/**/*.test.{js,jsx}'],
    restoreMocks: true,
    unstubGlobals: true
  }
});
