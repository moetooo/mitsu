# Mitsu (密) — AI-Powered Manga Discovery & Recommendation Engine

> **Mitsu** is a full-stack, AI-powered manga discovery system built over a database of 95,000+ manga titles sourced from Jikan (MyAnimeList) and AniList APIs. It uses high-dimensional vector embeddings, RAG similarity search, multi-field SQL filtering, and a minimalist Japanese aesthetic interface (Sumi Ink & Washi Paper themes).

---

## 🌟 Key Features

- **Semantic Vector Search**: Natural language search powered by SentenceTransformers (`all-MiniLM-L6-v2`, 384-dimensional embeddings) and PostgreSQL `pgvector` HNSW indexes.
- **Trope & Hybrid Comparison ("Like X but Y")**: Search for titles based on existing manga tropes (e.g., *"Like Berserk but happier"*, *"Like Naruto but darker and psychological"*).
- **Japanese Minimalist Design System**: Built with Japanese aesthetic principles (**Ma** negative space, **Kanso** simplicity, **Shibui** restrained tones, and **Hanko** vermillion stamp seals).
- **Multi-Field Filtering Drawer**: Filter recommendations by status (`FINISHED`, `RELEASING`), publication year, score range, chapter counts, include/exclude genres, format origin (`Manga`/`Manhwa`/`Manhua`), and NSFW preferences.
- **Interactive Detail Modal**: Modal previews with vertical-text genre sidebars, clickable tag chips, direct AniList profile links, shareable link generation, and horizontal **More Like This** carousels.
- **Date-Seeded Featured Banners**: Dynamic homepage hero banner featuring high-resolution wallpapers and date-seeded random database title sampling (stable across page loads throughout the day).
- **Theme & Customization Options**: Light/Dark modes (**Sumi Ink**, **Washi Paper**, **Classic**), adjustable card grid density, typography selection, and customizable hover accent palettes.
- **Zero-Lag Performance**: Optimized CSS backdrop radial gradients, lazy-loaded images with fallback handling, and cross-browser custom scrollbar hiding.

---

## 🛠️ Technology Stack

### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 16 with `pgvector` extension (HNSW Cosine Vector Indexing)
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384d)
- **Database Access**: SQLAlchemy Async Engine + `asyncpg` connection pooling
- **Cache**: Redis 7

### Frontend
- **Framework**: React 18 + Vite
- **Styling**: TailwindCSS + Custom CSS Variables & Typography (`Shippori Mincho`, `Zen Kaku Gothic New`, `Inter`)
- **Icons**: Lucide Icons & Custom SVG Mon Glyphs (`❖`)

---

## 📂 Project Architecture

```
mitsu/
├── app/                        # FastAPI Backend Application
│   ├── db.py                   # Async PostgreSQL Database Session Setup
│   ├── db_models.py            # SQLAlchemy Database Models (manga_canonical)
│   ├── main.py                 # FastAPI Application Router & CORS Entry
│   ├── models.py               # Pydantic Schemas & Request/Response Models
│   ├── ingestion/              # Data Pipeline Modules
│   │   ├── discovery.py        # Jikan API Discovery Service
│   │   ├── enrich.py           # AniList GraphQL Metadata Enrichment
│   │   ├── merge.py            # Deduplication & Canonical Linking
│   │   └── embed.py            # SentenceTransformers Vector Embedding Pipeline
│   ├── routers/                # API Endpoints
│   │   ├── recommend.py        # POST /recommend Vector Search & RAG Handler
│   │   ├── manga.py            # GET /manga/featured & GET /manga/{id}/similar
│   │   ├── search.py           # Autocomplete Suggestions Handler
│   │   └── admin.py            # Administrative Ingestion Triggers
│   └── services/               # Core Search & Retrieval Logic
│       └── retrieval.py        # Vector Similarity Queries & SQL Filter Builder
├── frontend/                   # React Frontend Application
│   ├── public/                 # Static Assets
│   ├── src/
│   │   ├── components/         # React Component Library
│   │   │   ├── Header.jsx      # Top Navigation & Branding Bar
│   │   │   ├── SearchBar.jsx   # Input Bar & Circular Vermillion Search Button
│   │   │   ├── HeroBanner.jsx  # Featured Title Banner Carousel
│   │   │   ├── MangaGrid.jsx   # Recommendation Grid & Pagination
│   │   │   ├── MangaCard.jsx   # Framed Print Cards with Hanko Match Seals
│   │   │   ├── MangaDetailModal.jsx # Detail Drawer & Related Titles
│   │   │   ├── FilterDrawer.jsx # Multi-Criteria Filter Controls
│   │   │   ├── ComparisonSearch.jsx # Hybrid "Like X but Y" Query Builder
│   │   │   └── SettingsModal.jsx    # Theme & Density Controls
│   │   ├── App.jsx             # Main Application State Container
│   │   ├── index.css           # Global Theme Tokens & Utility Classes
│   │   └── main.jsx            # React Mounting Root
│   ├── package.json
│   └── vite.config.js
├── docker-compose.yml          # Local PostgreSQL & Redis Infrastructure
├── requirements.txt            # Python Dependencies
├── .env.example                # Environment Variable Template
└── README.md
```

---

## 🚀 Quick Start Guide

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker & Docker Compose

### 1. Database Infrastructure Setup
Start PostgreSQL with `pgvector` and Redis containers:
```bash
docker compose up -d
```

### 2. Backend Setup
Create a virtual environment and install Python dependencies:
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment (Windows PowerShell)
.\venv\Scripts\activate

# Activate virtual environment (Linux/macOS)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and verify database credentials:
```bash
cp .env.example .env
```

Start the FastAPI server:
```bash
uvicorn app.main:app --reload
```
The API server will run at `http://localhost:8000`.

### 3. Frontend Setup
In a new terminal window:
```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite development server
npm run dev
```
The application will open at `http://localhost:5173`.

---

## 📊 Data Ingestion Pipeline

To populate the database with manga titles and vector embeddings:

1. **Discover Raw Titles**:
   ```bash
   python -m app.ingestion.discovery
   ```
2. **Enrich Metadata**:
   ```bash
   python -m app.ingestion.enrich
   ```
3. **Deduplicate & Merge**:
   ```bash
   python -m app.ingestion.merge
   ```
4. **Generate Vector Embeddings**:
   ```bash
   python -m app.ingestion.embed
   ```

---

## 🔌 API Endpoints Summary

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/recommend` | Semantic RAG search with multi-field SQL filters |
| `GET` | `/manga/featured` | Date-seeded random featured titles for hero banner |
| `GET` | `/manga/{manga_id}/similar` | Vector nearest-neighbor search for a target title |
| `GET` | `/search/suggest` | Fast autocomplete search suggestions |
| `GET` | `/health` | API health check endpoint |

---

## 📦 Production Deployment

### Building Frontend Assets
To compile optimized production assets:
```bash
cd frontend
npm run build
```
Output files will be generated in `frontend/dist/`.

### Production Server Command
Run Uvicorn with multi-worker production configuration:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 📄 License
MIT License. Created for AI-assisted manga discovery.
