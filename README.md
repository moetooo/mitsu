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

---

## 📄 License
[MIT](LICENSE)
