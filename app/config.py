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
