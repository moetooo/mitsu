# Mitsu frontend

React 19 + Vite client for the Mitsu API. See the [root README](../README.md) for
the full project setup; this file only covers the frontend layout and commands.

## Layout

```
src/
├─ App.jsx                 # page composition: tabs, filters, modals
├─ main.jsx                # entry: StrictMode + ErrorBoundary + index.css
├─ config.js               # API base URL and route builders
├─ index.css               # design tokens + global styles
├─ components/
│  ├─ common/              # BackToTop, ErrorBanner, ErrorBoundary
│  ├─ layout/              # Header
│  ├─ manga/               # MangaCard, MangaGrid, detail modal, cover rail/fallback
│  ├─ explore/             # HeroBanner, TrendingSection
│  ├─ views/               # BookmarksView, SimilarView, SurpriseView
│  └─ controls/            # SearchBar, FilterDrawer, FilterControls, SettingsModal
├─ hooks/                  # one hook per concern (routing, search, covers, …)
├─ utils/                  # pure helpers (filters, storage, vocabulary, …)
└─ dashboard/              # separate admin entry (DashboardApp + dashboard.css)

tests/                      # Vitest, mirrors src/: setup, harness, components, hooks, utils, contract
```

Tests live in `tests/`, mirroring the `src/` tree, and import application code
through the `@` alias (`@/components/manga/MangaCard`). Test files are source:
only generated artifacts (`coverage/`, `*.lcov`, `.vitest/`) are gitignored.

## Tuning the Surprise Me card

`src/utils/surpriseCardLayout.js` is the only place to change the discovery
card's geometry and type. Both objects are exported so tests can prove the
rendered styles come from them.

| Object | Covers |
| --- | --- |
| `SURPRISE_CARD_LAYOUT` | text-block padding (`PLATE_*`), reveal gap (`SECTION_GAP`), open-state drop (`EXPANDED_DROP`) |
| `SURPRISE_CARD_TEXT` | Y positions (`TEXT_OFFSET_Y`, `TEXT_OFFSET_Y_HOVER`), title (`TITLE_*`), genre • year (`META_*`), genre pills (`PILL_SIZE`), status pill (`STATUS_*`), synopsis (`SYNOPSIS_*`), Full Details button (`BUTTON_*`) |

Each value has a one-line comment in that file (px, em, weight or line count).
The component forwards them as CSS custom properties to the `surprise-card-*`
classes in `src/index.css`; no other file hardcodes those sizes. The card's
overall bottom-sheet height is separate: it is the user's cover-length setting
(`surpriseImageLength`, 50–70%).

## Commands

```bash
npm install          # once
npm run dev          # app on :5173, proxies /api → :8001
npm test             # Vitest + Testing Library
npm run lint         # oxlint
npm run build        # production bundle → dist/

npm run dev:dashboard      # admin entry on :5174/dashboard.html
npm run build:dashboard    # → ../app/static/dashboard
```
