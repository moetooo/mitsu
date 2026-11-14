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
    HNSW_EF_SEARCH: int = int(os.getenv("HNSW_EF_SEARCH", "200"))
    DB_ENABLE_HNSW_FALLBACK: bool = os.getenv("DB_ENABLE_HNSW_FALLBACK", "true").lower() in ("true", "1", "yes")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

# Set HuggingFace authentication token in OS environment for HuggingFace Hub & sentence-transformers
if settings.HF_TOKEN:
    os.environ["HF_TOKEN"] = settings.HF_TOKEN
    os.environ["HUGGINGFACE_TOKEN"] = settings.HF_TOKEN
    os.environ["HUGGING_FACE_HUB_TOKEN"] = settings.HF_TOKEN
