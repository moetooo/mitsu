from typing import Any
from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from pgvector.sqlalchemy import Vector
from .db import Base

class Manga(Base):
    __tablename__ = "manga"
    # Matches the deployed table: `id` is the only primary key and each
    # external id is unique on its own. The previous composite
    # (id, start_year) key + partitioning declaration could not be created on a
    # fresh database (the FK from manga_external_ids has no unique target) and
    # let one external id exist twice when start_year differed.
    __table_args__ = (
        UniqueConstraint("anilist_id", name="uq_manga_anilist_id"),
        UniqueConstraint("mal_id", name="uq_manga_mal_id"),
        UniqueConstraint("mangadex_id", name="uq_manga_mangadex_id"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    anilist_id = Column(Integer, nullable=True)
    mal_id = Column(Integer, nullable=True)
    mangadex_id = Column(String, nullable=True)
    title_romaji = Column(Text)
    title_english = Column(Text)
    title_native = Column(Text)
    synopsis = Column(Text)
    # Persisted safety signal. Decided once at ingestion time from provider
    # metadata (MangaDex contentRating, AniList isAdult) and kept as the single
    # source of truth for public visibility; see app/services/safety.py.
    is_nsfw = Column(Boolean, nullable=False, server_default=text("false"))
    genres = Column(ARRAY(Text))
    tags: Any = Column(JSONB) # [{"name": "Survival", "rank": 87}, ...]
    status = Column(Text)
    # Publication format, classified once at write time (ARCH-05). Filtering and
    # result payloads read this instead of re-deriving it per query.
    format_type = Column(String(16), nullable=True)
    start_year = Column(Integer)
    chapters = Column(Integer)
    volumes = Column(Integer)
    average_score = Column(Integer)
    popularity = Column(Integer)
    cover_image_url = Column(Text)
    banner_image = Column(Text)
    site_url = Column(Text)
    alternative_titles: Any = Column(ARRAY(Text), server_default=text("'{}'::text[]"))
    inferred_tags: Any = Column(JSONB, server_default=text("'[]'::jsonb"))
    embedding = Column(Vector(384))
    similar_mangas: Any = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=text('now()'))
    updated_at = Column(DateTime(timezone=True), server_default=text('now()'))

    # Daily sync observability. Nullable so legacy rows remain valid.
    source_updated_at = Column(DateTime(timezone=True), nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_source = Column(String(32), nullable=True)
    similarities_computed_at = Column(DateTime(timezone=True), nullable=True)

class DiscoveryQueue(Base):
    __tablename__ = "discovery_queue"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False)          # 'mangadex'
    external_id = Column(String, nullable=False)
    title = Column(String)
    start_year = Column(Integer)
    enriched = Column(Boolean, default=False)
    enrich_attempts = Column(Integer, default=0)
    last_error = Column(String, nullable=True)
    discovered_at = Column(DateTime(timezone=True), server_default=text('now()'))
    enriched_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external_id"),)

class RecommendationsEdge(Base):
    __tablename__ = "recommendations_edges"
    __table_args__ = (
        # Declared so a fresh database gets the same referential integrity the
        # deployed one already has (PIPE-15: the ORM and the DDL disagreed).
        ForeignKeyConstraint(
            ["manga_id_from"], ["manga.id"], name="recommendations_edges_manga_id_from_fkey"
        ),
        ForeignKeyConstraint(
            ["manga_id_to"], ["manga.id"], name="recommendations_edges_manga_id_to_fkey"
        ),
    )

    manga_id_from = Column(Integer, primary_key=True)
    manga_id_to = Column(Integer, primary_key=True)
    vote_count = Column(Integer)


class MangaExternalId(Base):
    """Canonical external-ID map.

    Uniqueness on (source, external_id) is what prevents a second local row from
    being created for an ID that is already attached to another manga.
    """
    __tablename__ = "manga_external_ids"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_manga_external_ids_source_external"),
        # One index on manga_id, named explicitly: `index=True` produced a second
        # identical index (`ix_manga_external_ids_manga_id`) next to this one.
        Index("idx_manga_external_ids_manga", "manga_id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    manga_id = Column(Integer, ForeignKey("manga.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(32), nullable=False)
    external_id = Column(String(128), nullable=False)
    confidence = Column(Float, nullable=False, server_default=text("1.0"))
    first_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_seen_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SyncState(Base):
    """Per-source checkpoint. AniList stores its updatedAt watermark here."""
    __tablename__ = "sync_state"

    source = Column(String(32), primary_key=True)
    checkpoint_value = Column(Text, nullable=True)
    checkpoint_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    # Oldest provider update date the backfill has consumed. Drives progress.
    progress_at = Column(DateTime(timezone=True), nullable=True)
    # AniList reports lastPage for UPDATED_AT_DESC; lets the UI show exact page progress.
    page_total = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SyncSetting(Base):
    """Small runtime overrides that must survive restarts (for example auto on/off)."""
    __tablename__ = "sync_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SyncApiUsage(Base):
    """Daily provider request counter. One row per UTC day/source."""
    __tablename__ = "sync_api_usage"

    day = Column(Date, primary_key=True)
    source = Column(String(32), primary_key=True)
    requests = Column(Integer, nullable=False, server_default=text("0"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SyncRun(Base):
    """Bounded audit log for manual and scheduled syncs."""
    __tablename__ = "sync_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(36), nullable=False, unique=True)
    mode = Column(String(16), nullable=False)  # manual | auto
    status = Column(String(24), nullable=False)  # running | success | partial | failed | skipped | rejected
    dry_run = Column(Boolean, nullable=False, server_default=text("false"))
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True), nullable=True)
    pages_fetched = Column(Integer, nullable=False, server_default=text("0"))
    rows_seen = Column(Integer, nullable=False, server_default=text("0"))
    rows_inserted = Column(Integer, nullable=False, server_default=text("0"))
    rows_updated = Column(Integer, nullable=False, server_default=text("0"))
    rows_unchanged = Column(Integer, nullable=False, server_default=text("0"))
    rows_embedded = Column(Integer, nullable=False, server_default=text("0"))
    rows_conflicted = Column(Integer, nullable=False, server_default=text("0"))
    request_usage = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error = Column(Text, nullable=True)

#: Everything `/search` matches against, as one string.
#:
#: The endpoint used to OR four predicates: `title_english ILIKE … OR
#: title_romaji ILIKE … OR title_native ILIKE … OR
#: array_to_string(alternative_titles, ' ') ILIKE …`. An OR across four
#: expressions cannot use an index unless *every* branch is indexed, and the
#: `array_to_string` branch never could be, so the planner fell back to a
#: sequential scan over every row: measured **270-390 ms warm** on the 95,626-row
#: catalogue. One expression over the same text, indexed once, answers the same
#: question in **3-37 ms** (`Bitmap Index Scan on idx_manga_search_blob_trgm`).
#:
#: Why `mitsu_alt_titles_text` instead of `array_to_string` directly: PostgreSQL
#: marks `array_to_string(anyarray, text)` **STABLE**, because element output
#: functions may be stable, and an index expression must be IMMUTABLE. For a
#: `text[]` the conversion has no time or locale dependency, so migration 0006
#: defines an IMMUTABLE wrapper over it (this is the standard pg_trgm answer for
#: exactly this case).
#: The separators and empty-string defaults are inlined, not bound. A bound
#: parameter in the expression (`|| $1 ||`) does not match the index expression
#: (`|| ' ' ||`) and the planner would ignore the index. `text()` rather than
#: `literal_column()` because a bare `ColumnClause` has no table, and SQLAlchemy
#: then refuses to attach the functional index to `manga` at all.
_SPACE = text("' '")
_EMPTY = text("''")

SEARCH_BLOB = func.lower(
    func.coalesce(Manga.title_english, _EMPTY)
    + _SPACE
    + func.coalesce(Manga.title_romaji, _EMPTY)
    + _SPACE
    + func.coalesce(Manga.title_native, _EMPTY)
    + _SPACE
    + func.coalesce(func.mitsu_alt_titles_text(Manga.alternative_titles), _EMPTY)
)

# Indexes are defined in the schema script or alembic, but we can also define them here:
Index('idx_manga_genres', Manga.genres, postgresql_using='gin')
Index('idx_manga_tags', Manga.tags, postgresql_using='gin')
Index('idx_manga_alt_titles', Manga.alternative_titles, postgresql_using='gin')
Index('idx_manga_inferred_tags', Manga.inferred_tags, postgresql_using='gin')
Index('idx_manga_status', Manga.status)
Index('idx_manga_format_type', Manga.format_type)
Index('idx_manga_start_year', Manga.start_year)
Index('idx_manga_title_english_trgm', Manga.title_english, postgresql_using='gin', postgresql_ops={'title_english': 'gin_trgm_ops'})
Index('idx_manga_title_romaji_trgm', Manga.title_romaji, postgresql_using='gin', postgresql_ops={'title_romaji': 'gin_trgm_ops'})
Index('idx_manga_title_native_trgm', Manga.title_native, postgresql_using='gin', postgresql_ops={'title_native': 'gin_trgm_ops'})
# What `/search` actually matches on (API-08). Keyed by the expression's label so
# SQLAlchemy emits the `gin_trgm_ops` opclass for a functional index.
Index(
    'idx_manga_search_blob_trgm',
    SEARCH_BLOB.label('search_blob'),
    postgresql_using='gin',
    postgresql_ops={'search_blob': 'gin_trgm_ops'},
)
Index(
    'idx_manga_embedding_hnsw',
    Manga.embedding,
    postgresql_using='hnsw',
    postgresql_with={'m': 16, 'ef_construction': 64},
    postgresql_ops={'embedding': 'vector_cosine_ops'}
)

# --- P1 database optimization: covering / partial indexes for hot query paths ---
# Filter combinations used by search + roulette (status + year slice).
Index('idx_manga_status_year', Manga.status, Manga.start_year)
# Ranking / min_score filters.
Index('idx_manga_score_popularity', Manga.average_score.desc(), Manga.popularity.desc())
Index('idx_manga_year_score', Manga.start_year, Manga.average_score.desc())
Index('idx_manga_chapters', Manga.chapters)
Index('idx_manga_updated_at', Manga.updated_at)
# Roulette always requires a cover image; a partial index keeps it small.
Index(
    'idx_manga_cover_notnull',
    Manga.id,
    postgresql_where=text('cover_image_url IS NOT NULL'),
)

# Graph traversal from a seed manga (reverse edges).
Index('idx_reco_edges_to', RecommendationsEdge.manga_id_to)
# Newest-first listings: the audit log is read by recency and by status.
Index('idx_sync_runs_started', SyncRun.started_at.desc())
Index('idx_sync_runs_status', SyncRun.status, SyncRun.started_at.desc())
Index('idx_reco_edges_votes', RecommendationsEdge.vote_count.desc())

# Enrichment workers poll pending rows by source.
Index(
    'idx_discovery_queue_pending',
    DiscoveryQueue.source,
    DiscoveryQueue.discovered_at,
    postgresql_where=text('enriched = false'),
)
Index('idx_discovery_queue_external', DiscoveryQueue.external_id)
