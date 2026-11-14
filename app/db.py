from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import settings


# asyncpg 0.31 removed the connect-time `init` callback. Apply connection
# settings through PostgreSQL startup parameters instead.
#
# The pgvector GUCs (hnsw.ef_search, hnsw.iterative_scan) cannot be set here:
# they are defined by the extension, which is only loaded once the `vector`
# type is first touched in a session, so a startup packet or a connect-time SET
# fails with "unrecognized configuration parameter". They are applied per query
# by `retrieval.apply_ann_settings()` using transaction-local set_config.
_CONNECT_ARGS = {
    "command_timeout": settings.DB_COMMAND_TIMEOUT_S,
    "server_settings": {
        "application_name": "mitsu-api",
        "statement_timeout": str(int(settings.DB_STATEMENT_TIMEOUT_MS)),
    },
}


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_S,
    pool_pre_ping=True,
    connect_args=_CONNECT_ARGS,
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
