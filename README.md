# Mitsu (密) — AI Manga Discovery

> An AI-powered manga discovery and recommendation engine built with vector embeddings, semantic RAG search, and a minimalist Japanese design language (Sumi Ink & Washi Paper themes).

---

## ✨ Features

- **Semantic Vector Search**: Natural language recommendations powered by `pgvector` HNSW indices & 384d embeddings.
- **Trope & Comparison Queries**: Hybrid recommendation builder ("Like X but Y").
- **Japanese Shibui Aesthetic**: Minimalist UI inspired by Japanese design principles (Sumi & Washi themes, Hanko seals).
- **Multi-Criteria Filtering**: Filter by genre, year, status, origin, chapter count, and score.
- **Trending Rail**: Explore opens on a cover rail of the top ten, with a Manga / Manhwa / Manhua toggle that reloads the rail in place — one cached request per format, no paging.
- **Redis Response Caching**: High-performance response caching for trending, featured, and recommendation endpoints.

---

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.13), PostgreSQL 16 + `pgvector`, Redis 7, `fastembed` serving `sentence-transformers/all-MiniLM-L6-v2` (384-d)
- **Frontend**: React 19, Vite, TailwindCSS
- **Typography**: `Shippori Mincho`, `Zen Kaku Gothic New`, `Inter`

---

## 🚀 Quick Start

### 1. Start Database Infrastructure
```bash
docker compose up -d
```

> Docker Engine runs natively inside the Ubuntu WSL2 distro (Docker Desktop is
> not installed). Run this from a WSL shell, or prefix it with
> `wsl -d Ubuntu --` from Windows. See
> [`docs/wsl-docker.md`](docs/wsl-docker.md) for the full environment,
> autostart, and backup setup.

### 2. Start Backend API
```bash
# Activate virtualenv & install requirements
pip install -r requirements.txt

# Create/upgrade the schema (Alembic owns the schema; nothing does it at startup)
alembic upgrade head

# Launch FastAPI dev server. The app logs one line per request itself
# (`app/middleware/request_log.py`) and silences uvicorn's access log in
# `app/core/logging.py`, so no extra flags are needed.
python -m app                 # port 8001 built in (app/__main__.py)
```

Port 8001, not 8000: 8000 is vLLM's default port and coding agents probe it
every 30 s for a local model server (`GET /v1/models`), which would fill the
request log with 404s. `python -m app` sets the port for you; the other two
spellings work too, in increasing order of typing:

```bash
UVICORN_PORT=8001 uvicorn app.main:app --reload   # uvicorn reads UVICORN_* for defaults
uvicorn app.main:app --reload --port 8001        # explicit flag, always wins
```

`API_PORT` / `API_HOST` override `python -m app`'s defaults.

`alembic upgrade head` is the only way to change a table. An existing database
that predates migrations should be brought in with `alembic stamp <revision>`
instead of replaying the baseline. The app does not write DDL: it verifies the
database is at a revision it can use and logs `alembic upgrade head` if not.
Details: `docs/MIGRATIONS.md`.

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
python -m app.sync.cli migrate   # verify schema + seed external ids
python -m app.sync.cli run --dry-run --max-pages 1
python -m app.sync.cli run --mode manual --max-pages 3
python -m app.sync.cli backfill --until 2026-08-06T19:43:15+00:00 --max-pages 25
python -m app.sync.cli status
```

Open <http://localhost:8001/admin/dashboard> for the control page: daily request
bars, backfill progress toward the cutoff, guardrail counters, a dark/light
toggle, paginated run history with expandable multiline details, and
manual/backfill triggers. Sign in with `SYNC_ADMIN_USERNAME` / `SYNC_ADMIN_PASSWORD`.
There is no default account: leave either one unset and the whole admin surface
answers 503, so a fresh deployment cannot be entered with a well-known password.
Scheduled auto sync starts **off**; enable it with the switch when you are ready.

The dashboard is a separate React/Vite entry. Its build output is gitignored, so a
fresh checkout must build it once before `/admin/dashboard` serves the Vite app
(otherwise the legacy fallback page is served):

```bash
cd frontend
npm run build:dashboard
```

It is written to `app/static/dashboard/` and mounted at `/admin/dashboard-assets`.

For live dashboard work, `npm run dev:dashboard` serves the entry at
<http://localhost:5174/dashboard.html> and proxies `/admin` to the API.

Full setup, API trigger, Windows Task Scheduler, and cron details are in
[`docs/catalog-sync.md`](docs/catalog-sync.md).

---

## 🧪 Tests

Two suites, both must pass before a change lands.

```bash
# Backend: creates its own test database with `alembic upgrade head` and never
# touches the database in .env (see tests/conftest.py). Coverage is part of the
# run; the floor is in .coveragerc.
venv/Scripts/python.exe -m pytest -q
venv/Scripts/python.exe -m alembic check      # schema drift

# A single file or directory still reports coverage but cannot meet the floor,
# so add --no-cov when you are not running the whole suite:
venv/Scripts/python.exe -m pytest -q tests/test_search_filters.py --no-cov

# Frontend: Vitest + Testing Library + jsdom
cd frontend && npm test && npm run lint && npm run build
```

Tests that need a populated catalog are marked `requires_catalog` and skip on the
empty test database; point `MITSU_TEST_DATABASE_URL` at a disposable copy of a
real catalog to run them. The campaign records of past migration campaigns live
in `tests/milestones/` and assert on project artifacts rather than application
behaviour, so they are not regression protection (see `ARCHITECTURE.md` §7).

---

## 📄 License
[MIT](LICENSE)
