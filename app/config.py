import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load environment variables from .env
load_dotenv()

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/mangamind")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    HF_TOKEN: str = os.getenv("HF_TOKEN", os.getenv("HUGGINGFACE_TOKEN", os.getenv("HUGGING_FACE_HUB_TOKEN", "")))
    ENABLE_INFERRED_TAG_RANKING: bool = os.getenv("ENABLE_INFERRED_TAG_RANKING", "false").lower() in ("true", "1", "yes")
    INFERRED_TAG_BOOST: float = float(os.getenv("INFERRED_TAG_BOOST", "0.10"))

    # --- Catalog sync (manual + once-daily scheduler) ---
    SYNC_ENABLED: bool = os.getenv("SYNC_ENABLED", "true").lower() in ("true", "1", "yes")
    SYNC_AUTO_ENABLED: bool = os.getenv("SYNC_AUTO_ENABLED", "false").lower() in ("true", "1", "yes")
    SYNC_ADMIN_TOKEN: str = os.getenv("SYNC_ADMIN_TOKEN", "")
    # Browser dashboard login. Deliberately empty: with no username/password
    # the admin surface fails closed (503) instead of shipping a well-known
    # credential. Set both before using the dashboard.
    SYNC_ADMIN_USERNAME: str = os.getenv("SYNC_ADMIN_USERNAME", "")
    SYNC_ADMIN_PASSWORD: str = os.getenv("SYNC_ADMIN_PASSWORD", "")
    SYNC_ADMIN_SESSION_SECRET: str = os.getenv("SYNC_ADMIN_SESSION_SECRET", "")
    SYNC_ADMIN_SESSION_HOURS: int = int(os.getenv("SYNC_ADMIN_SESSION_HOURS", "12"))
    SYNC_ADMIN_COOKIE_SECURE: bool = os.getenv("SYNC_ADMIN_COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
    SYNC_EMBEDDINGS: bool = os.getenv("SYNC_EMBEDDINGS", "true").lower() in ("true", "1", "yes")
    SYNC_INVALIDATE_CACHE: bool = os.getenv("SYNC_INVALIDATE_CACHE", "true").lower() in ("true", "1", "yes")
    SYNC_RUN_RETENTION_DAYS: int = int(os.getenv("SYNC_RUN_RETENTION_DAYS", "30"))
    SYNC_LOCK_KEY: int = int(os.getenv("SYNC_LOCK_KEY", "74657374"))

    # --- Daily guardrails shared by manual, auto, and backfill runs ---
    # An override may raise today's cap, but never above this deploy-level ceiling.
    SYNC_HARD_DAILY_CEILING: int = int(os.getenv("SYNC_HARD_DAILY_CEILING", "60"))
    # Requests kept back from backfill so the normal daily sync always fits.
    SYNC_BACKFILL_RESERVE: int = int(os.getenv("SYNC_BACKFILL_RESERVE", "5"))
    SYNC_DAILY_RUN_LIMIT: int = int(os.getenv("SYNC_DAILY_RUN_LIMIT", "6"))
    SYNC_MANUAL_COOLDOWN_SECONDS: int = int(os.getenv("SYNC_MANUAL_COOLDOWN_SECONDS", "600"))
    SYNC_USAGE_RETENTION_DAYS: int = int(os.getenv("SYNC_USAGE_RETENTION_DAYS", "90"))

    ANILIST_DAILY_REQUEST_BUDGET: int = int(os.getenv("ANILIST_DAILY_REQUEST_BUDGET", "30"))
    ANILIST_SYNC_PAGE_SIZE: int = int(os.getenv("ANILIST_SYNC_PAGE_SIZE", "50"))
    ANILIST_SYNC_MAX_PAGES: int = int(os.getenv("ANILIST_SYNC_MAX_PAGES", "3"))
    MANGADEX_DAILY_REQUEST_BUDGET: int = int(os.getenv("MANGADEX_DAILY_REQUEST_BUDGET", "20"))
    MANGADEX_SYNC_BATCH_SIZE: int = int(os.getenv("MANGADEX_SYNC_BATCH_SIZE", "20"))
    MANGADEX_SYNC_ENABLED: bool = os.getenv("MANGADEX_SYNC_ENABLED", "true").lower() in ("true", "1", "yes")
    # Historical catch-up target. Backfill walks AniList updates newer than this.
    SYNC_BACKFILL_CUTOFF: str = os.getenv("SYNC_BACKFILL_CUTOFF", "2026-08-06T19:43:15+00:00")

    # --- Database / query tuning (P1 optimization) ---
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "15"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    DB_POOL_RECYCLE_S: int = int(os.getenv("DB_POOL_RECYCLE_S", "1800"))
    DB_STATEMENT_TIMEOUT_MS: int = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "15000"))
    DB_COMMAND_TIMEOUT_S: float = float(os.getenv("DB_COMMAND_TIMEOUT_S", "20"))
    # Quality knob for the ANN graph walk. pgvector treats it as a hard ceiling on
    # the candidate list unless iterative_scan is on, so it is no longer used to
    # cap the pool and completeness comes from HNSW_ITERATIVE_SCAN instead.
    HNSW_EF_SEARCH: int = int(os.getenv("HNSW_EF_SEARCH", "200"))
    # `relaxed_order` lets pgvector keep scanning past ef_search until the LIMIT is
    # satisfied. Without it a LIMIT larger than ef_search returns fewer rows than
    # asked for (measured: 39 of 100 at the default ef_search=40).
    HNSW_ITERATIVE_SCAN: str = os.getenv("HNSW_ITERATIVE_SCAN", "relaxed_order")
    # How many ANN candidates to fetch per requested row. The pool has to survive
    # the title de-duplication and the relevance filter inside the CTE, so it is
    # deliberately larger than the page.
    HNSW_POOL_HEADROOM: int = int(os.getenv("HNSW_POOL_HEADROOM", "5"))
    # Ceiling on that pool. Measured on a 95k-row catalog, 300 candidates took
    # ~24 ms; an unbounded pool would let `page=100` ask for ~75k.
    HNSW_MAX_POOL_LIMIT: int = int(os.getenv("HNSW_MAX_POOL_LIMIT", "1000"))
    DB_ENABLE_HNSW_FALLBACK: bool = os.getenv("DB_ENABLE_HNSW_FALLBACK", "true").lower() in ("true", "1", "yes")
    # Precomputed `similar_mangas` edges older than this are ignored by
    # /manga/{id}/similar in favour of a live ANN query. The edges were never
    # invalidated before, so a re-embedded row served stale neighbours forever.
    SIMILAR_EDGES_MAX_AGE_DAYS: int = int(os.getenv("SIMILAR_EDGES_MAX_AGE_DAYS", "30"))

    # --- Title shortcut ("/recommend" deciding the query names one title) ---
    # The shortcut is what makes a misspelled title search work (the semantic
    # fallback recovers only 2 of 8 misspellings we measured) and what made 10 of
    # 12 thematic searches return one obscure title instead of a genre list.
    #
    # TITLE_MATCH_MAX_WORD_SIM is the one rule here that is *structural* rather
    # than tuned: a query whose every word appears verbatim inside a title is not
    # a misspelling, it is a phrase that happens to occur in a title ("cooking"
    # in "Hot-to-Go Bakery: Cooking the Dead", word_similarity = 1.000). Measured
    # over 8 misspellings, the highest word_similarity is 0.933, so the veto
    # costs nothing and does not drift as the catalogue grows.
    #
    # The other two are tuned and may need revisiting if titles get much longer
    # or shorter on average. TITLE_MATCH_MIN_SIM is the original 0.40 (the
    # misspelling set spans 0.429-0.824); the coverage bounds reject a short
    # fragment of a long title, e.g. "sports underdog team" -> "Underdog" (0.36).
    TITLE_MATCH_MIN_SIM: float = float(os.getenv("TITLE_MATCH_MIN_SIM", "0.40"))
    TITLE_MATCH_MAX_WORD_SIM: float = float(os.getenv("TITLE_MATCH_MAX_WORD_SIM", "0.995"))
    TITLE_MATCH_MIN_COVERAGE: float = float(os.getenv("TITLE_MATCH_MIN_COVERAGE", "0.5"))
    TITLE_MATCH_MAX_COVERAGE: float = float(os.getenv("TITLE_MATCH_MAX_COVERAGE", "2.0"))

    # --- Roulette sampling ---
    # A draw is taken from this many short id ranges spread across the catalogue
    # instead of one contiguous block. A contiguous block is one ingest batch:
    # measured, 76% of a draw carried a MangaDex id against a 14% catalogue
    # baseline, and every draw came from a single ingest day.
    ROULETTE_SAMPLE_BLOCKS: int = int(os.getenv("ROULETTE_SAMPLE_BLOCKS", "8"))
    # How many ids each range spans, as a multiple of the draw size. The ranges
    # are scanned with index range scans, so cost follows this number and the
    # block count rather than the table size -- unlike ORDER BY random(), which
    # degrades as the catalogue grows.
    ROULETTE_SAMPLE_OVERSCAN: int = int(os.getenv("ROULETTE_SAMPLE_OVERSCAN", "4"))

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# Set HuggingFace authentication token in OS environment for HuggingFace Hub & sentence-transformers
if settings.HF_TOKEN:
    os.environ["HF_TOKEN"] = settings.HF_TOKEN
    os.environ["HUGGINGFACE_TOKEN"] = settings.HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = settings.HF_TOKEN
