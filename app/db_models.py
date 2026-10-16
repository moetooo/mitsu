from typing import Any
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, Index, Boolean, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from pgvector.sqlalchemy import Vector
from .db import Base

class Manga(Base):
    __tablename__ = "manga"
    __table_args__ = (
        UniqueConstraint("anilist_id", "start_year", name="uq_manga_anilist_id"),
        UniqueConstraint("mal_id", "start_year", name="uq_manga_mal_id"),
        UniqueConstraint("mangadex_id", "start_year", name="uq_manga_mangadex_id"),
        {'postgresql_partition_by': 'RANGE (start_year)'}
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    anilist_id = Column(Integer, nullable=True)
    mal_id = Column(Integer, nullable=True)
    mangadex_id = Column(String, nullable=True)
    title_romaji = Column(Text)
    title_english = Column(Text)
    title_native = Column(Text)
    synopsis = Column(Text)
    genres = Column(ARRAY(Text))
    tags: Any = Column(JSONB) # [{"name": "Survival", "rank": 87}, ...]
    status = Column(Text)
    start_year = Column(Integer, primary_key=True)
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

    manga_id_from = Column(Integer, primary_key=True)
    manga_id_to = Column(Integer, primary_key=True)
    vote_count = Column(Integer)

# Indexes are defined in the schema script or alembic, but we can also define them here:
Index('idx_manga_genres', Manga.genres, postgresql_using='gin')
Index('idx_manga_tags', Manga.tags, postgresql_using='gin')
Index('idx_manga_alt_titles', Manga.alternative_titles, postgresql_using='gin')
Index('idx_manga_inferred_tags', Manga.inferred_tags, postgresql_using='gin')
Index('idx_manga_status', Manga.status)
Index('idx_manga_start_year', Manga.start_year)
Index('idx_manga_title_english_trgm', Manga.title_english, postgresql_using='gin', postgresql_ops={'title_english': 'gin_trgm_ops'})
Index('idx_manga_title_romaji_trgm', Manga.title_romaji, postgresql_using='gin', postgresql_ops={'title_romaji': 'gin_trgm_ops'})
Index('idx_manga_title_native_trgm', Manga.title_native, postgresql_using='gin', postgresql_ops={'title_native': 'gin_trgm_ops'})
Index(
    'idx_manga_embedding_hnsw',
    Manga.embedding,
    postgresql_using='hnsw',
    postgresql_with={'m': 16, 'ef_construction': 64},
    postgresql_ops={'embedding': 'vector_cosine_ops'}
)


