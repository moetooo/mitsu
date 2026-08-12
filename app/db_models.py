from sqlalchemy import Column, Integer, String, Text, JSON, DateTime, ForeignKey, Index, Boolean, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from pgvector.sqlalchemy import Vector
from .db import Base

class Manga(Base):
    __tablename__ = "manga"

    id = Column(Integer, primary_key=True, index=True)
    anilist_id = Column(Integer, unique=True, nullable=True)
    mal_id = Column(Integer, unique=True, nullable=True)
    mangadex_id = Column(String, unique=True, nullable=True)
    title_romaji = Column(Text)
    title_english = Column(Text)
    title_native = Column(Text)
    synopsis = Column(Text)
    genres = Column(ARRAY(Text))
    tags = Column(JSONB) # [{"name": "Survival", "rank": 87}, ...]
    status = Column(Text)
    start_year = Column(Integer)
    chapters = Column(Integer)
    volumes = Column(Integer)
    average_score = Column(Integer)
    popularity = Column(Integer)
    cover_image_url = Column(Text)
    banner_image = Column(Text)
    site_url = Column(Text)
    embedding = Column(Vector(384))
    created_at = Column(DateTime(timezone=True), server_default=text('now()'))
    updated_at = Column(DateTime(timezone=True), server_default=text('now()'))

class DiscoveryQueue(Base):
    __tablename__ = "discovery_queue"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False)          # 'jikan' | 'mangadex'
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

    manga_id_from = Column(Integer, ForeignKey("manga.id"), primary_key=True)
    manga_id_to = Column(Integer, ForeignKey("manga.id"), primary_key=True)
    vote_count = Column(Integer)

# Indexes are defined in the schema script or alembic, but we can also define them here:
Index('idx_manga_genres', Manga.genres, postgresql_using='gin')
Index('idx_manga_status', Manga.status)
Index('idx_manga_start_year', Manga.start_year)
