import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { getProxyTarget } from './vite.config.js'

const proxyTarget = getProxyTarget()

const proxy = {
  '/admin': { target: proxyTarget, changeOrigin: true },
}

// Separate entry so the control page keeps its own bundle and can be embedded
// under /admin/dashboard without loading the reader app.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  // Relative to /admin/dashboard, so a reverse-proxy prefix like /api keeps working.
  base: command === 'build' ? './' : '/',
  server: { port: 5174, proxy },
  preview: { port: 5174, proxy },
  build: {
    copyPublicDir: false,
    outDir: fileURLToPath(new URL('../app/static/dashboard', import.meta.url)),
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./dashboard.html', import.meta.url)),
    },
  },
}))
