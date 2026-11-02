from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import settings


async def _init_connection(conn):
    """Per-connection settings applied once per socket.

    Applied at connect time (not per request) so no extra round-trip is
    issued for each query, while still bounding runaway statements.
    """
    try:
        await conn.execute(f"SET statement_timeout = {int(settings.DB_STATEMENT_TIMEOUT_MS)}")
    except Exception:
        pass
    try:
        await conn.execute(f"SET hnsw.ef_search = {int(settings.HNSW_EF_SEARCH)}")
        await conn.execute("SET hnsw.iterative_scan = 'relaxed_order'")
    except Exception:
        pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_S,
    pool_pre_ping=True,
    connect_args={
        "command_timeout": settings.DB_COMMAND_TIMEOUT_S,
        "init": _init_connection,
        "server_settings": {"application_name": "mitsu-api"},
    },
)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
