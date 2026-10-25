import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export function getProxyTarget(env = process.env) {
  return env.VITE_DEV_PROXY_TARGET || env.VITE_API_BASE_URL || 'http://localhost:8000';
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
