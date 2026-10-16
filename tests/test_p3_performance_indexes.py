"""
Tests for P3 Performance Index Definitions (HNSW & pg_trgm Trigram Indexes)
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db_models import Manga
from scripts.migrate_p3_indexes import MIGRATION_STATEMENTS


def test_manga_model_has_p3_indexes():
    """Verify that Manga.__table__.indexes includes the required HNSW and GIN trigram indexes."""
    index_names = {idx.name: idx for idx in Manga.__table__.indexes}

    # 1. Verify GIN trigram indexes on title columns
    assert "idx_manga_title_english_trgm" in index_names, "Missing idx_manga_title_english_trgm"
    assert "idx_manga_title_romaji_trgm" in index_names, "Missing idx_manga_title_romaji_trgm"
    assert "idx_manga_title_native_trgm" in index_names, "Missing idx_manga_title_native_trgm"

    idx_en = index_names["idx_manga_title_english_trgm"]
    assert idx_en.dialect_options["postgresql"]["using"] == "gin"
    assert idx_en.dialect_options["postgresql"]["ops"]["title_english"] == "gin_trgm_ops"

    idx_ro = index_names["idx_manga_title_romaji_trgm"]
    assert idx_ro.dialect_options["postgresql"]["using"] == "gin"
    assert idx_ro.dialect_options["postgresql"]["ops"]["title_romaji"] == "gin_trgm_ops"

    idx_nat = index_names["idx_manga_title_native_trgm"]
    assert idx_nat.dialect_options["postgresql"]["using"] == "gin"
    assert idx_nat.dialect_options["postgresql"]["ops"]["title_native"] == "gin_trgm_ops"

    # 2. Verify HNSW vector index on embedding column
    assert "idx_manga_embedding_hnsw" in index_names, "Missing idx_manga_embedding_hnsw"
    idx_hnsw = index_names["idx_manga_embedding_hnsw"]
    assert idx_hnsw.dialect_options["postgresql"]["using"] == "hnsw"
    assert idx_hnsw.dialect_options["postgresql"]["ops"]["embedding"] == "vector_cosine_ops"
    assert idx_hnsw.dialect_options["postgresql"]["with"] == {"m": 16, "ef_construction": 64}


def test_migration_statements_completeness():
    """Verify migration statements list covers all required operations."""
    sqls = [sql for _, sql in MIGRATION_STATEMENTS]
    full_sql = " ".join(sqls)

    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm;" in full_sql
    assert "DROP INDEX IF EXISTS idx_manga_embedding;" in full_sql
    assert "idx_manga_embedding_hnsw" in full_sql
    assert "hnsw (embedding vector_cosine_ops)" in full_sql
    assert "idx_manga_title_english_trgm" in full_sql
    assert "idx_manga_title_romaji_trgm" in full_sql
    assert "idx_manga_title_native_trgm" in full_sql
