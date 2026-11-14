# Mitsu (密) — AI Manga Discovery

> An AI-powered manga discovery and recommendation engine built with vector embeddings, semantic RAG search, and a minimalist Japanese design language (Sumi Ink & Washi Paper themes).

---

## ✨ Features

- **Semantic Vector Search**: Natural language recommendations powered by `pgvector` HNSW indices & 384d embeddings.
- **Trope & Comparison Queries**: Hybrid recommendation builder ("Like X but Y").
- **Japanese Shibui Aesthetic**: Minimalist UI inspired by Japanese design principles (Sumi & Washi themes, Hanko seals).
- **Multi-Criteria Filtering**: Filter by genre, year, status, origin, chapter count, and score.
- **Redis Response Caching**: High-performance response caching for trending, featured, and recommendation endpoints.

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.11), PostgreSQL 16 + `pgvector`, Redis 7, SentenceTransformers (`all-MiniLM-L6-v2`)
- **Frontend**: React 18, Vite, TailwindCSS
- **Typography**: `Shippori Mincho`, `Zen Kaku Gothic New`, `Inter`

---

## 🚀 Quick Start

### 1. Start Database Infrastructure
```bash
docker compose up -d
```

### 2. Start Backend API
```bash
# Activate virtualenv & install requirements
pip install -r requirements.txt

# Launch FastAPI dev server
uvicorn app.main:app --reload
```

### 3. Start Frontend UI
```bash
cd frontend
npm install
npm run dev
```

### 4. Refresh the catalog
The refresh job is idempotent and can be run manually or once per day from an
external scheduler. It caps AniList at 30 requests/day and never inserts a known
external ID twice.

```bash
python -m app.sync.cli migrate
python -m app.sync.cli run --dry-run --max-pages 1
python -m app.sync.cli run --mode manual --max-pages 3
python -m app.sync.cli backfill --until 2026-08-06T19:43:15+00:00 --max-pages 25
python -m app.sync.cli status
```

Open <http://localhost:8000/admin/dashboard> for the control page: daily request
bars, backfill progress toward the cutoff, guardrail counters, a dark/light
toggle, paginated run history with expandable multiline details, and
manual/backfill triggers. Sign in with `SYNC_ADMIN_USERNAME` / `SYNC_ADMIN_PASSWORD`.
There is no default account: leave either one unset and the whole admin surface
answers 503, so a fresh deployment cannot be entered with a well-known password.
Scheduled auto sync starts **off**; enable it with the switch when you are ready.

The dashboard is a separate React/Vite entry. A production build is checked into
`app/static/dashboard/`; after editing `frontend/src/dashboard/`, rebuild it:

```bash
cd frontend
npm run build:dashboard
```

For live dashboard work, `npm run dev:dashboard` serves the entry at
<http://localhost:5174/dashboard.html> and proxies `/admin` to the API.

Full setup, API trigger, Windows Task Scheduler, and cron details are in
[`docs/catalog-sync.md`](docs/catalog-sync.md).

---

## 📄 License
[MIT](LICENSE)
