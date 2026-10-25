/**
 * Centralized API configuration for Mitsu Frontend.
 *
 * Priority order for API_BASE:
 * 1. Explicit environment variable: VITE_API_BASE_URL (if specified)
 * 2. Empty string '' by default, leveraging Vite dev/preview server proxy
 *    or reverse proxy (Nginx/Caddy) in production.
 *
 * This enables:
 * - Direct local development (localhost:5173 -> localhost:8000 via proxy)
 * - Seamless LAN / Wi-Fi usage on mobile or secondary devices
 *   (e.g., http://192.168.x.x:5173 proxies automatically to backend, bypassing CORS and firewall issues)
 * - Custom deployment targets via VITE_API_BASE_URL
 */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL !== undefined && import.meta.env.VITE_API_BASE_URL !== '')
  ? import.meta.env.VITE_API_BASE_URL.replace(/\/+$/, '')
  : '';

export const API_ROUTES = {
  featured: `${API_BASE}/manga/featured`,
  trending: (page = 1, limit = 12, formatParam = '', genreParam = '') =>
    `${API_BASE}/manga/trending?page=${page}&limit=${limit}${formatParam}${genreParam}`,
  similar: (id, limit = 6, allowNsfw = false) =>
    `${API_BASE}/manga/${id}/similar?limit=${limit}&allow_nsfw=${allowNsfw}`,
  mangaDetail: (id) => `${API_BASE}/manga/${id}`,
  recommend: `${API_BASE}/recommend`,
  roulette: `${API_BASE}/roulette`,
  rouletteBatch: `${API_BASE}/roulette/batch`,
  search: (query) => `${API_BASE}/search?q=${encodeURIComponent(query)}`,
  health: `${API_BASE}/health`,
};
