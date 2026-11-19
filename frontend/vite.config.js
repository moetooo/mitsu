import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export function getProxyTarget(env = process.env) {
  // 8001, not 8000: 8000 is vLLM's default port, and coding agents (opencode)
  // probe it every 30s for a local model server. Nothing should compete for it.
  return env.VITE_DEV_PROXY_TARGET || env.VITE_API_BASE_URL || 'http://localhost:8001';
}

const proxyTarget = getProxyTarget();

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/manga': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/recommend': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/roulette': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/search': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/admin': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/health': {
        target: proxyTarget,
        changeOrigin: true,
      },
      // FE-23: the served taxonomy. It is a root path, not under /manga, which is
      // why it was the one API route the proxy list did not answer.
      '/vocabulary': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5173,
    proxy: {
      '/manga': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/recommend': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/roulette': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/search': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/admin': {
        target: proxyTarget,
        changeOrigin: true,
      },
      '/health': {
        target: proxyTarget,
        changeOrigin: true,
      },
      // FE-23: the served taxonomy. It is a root path, not under /manga, which is
      // why it was the one API route the proxy list did not answer.
      '/vocabulary': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('react-window')) {
              return 'vendor-virtual'
            }
            if (id.includes('react') || id.includes('react-dom')) {
              return 'vendor-react'
            }
          }
        },
      },
    },
  },
})
