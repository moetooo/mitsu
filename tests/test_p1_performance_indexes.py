import os, sys
import pytest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.db_models import Manga, RecommendationsEdge, DiscoveryQueue
from app.services.retrieval import build_genre_sql_condition
from pathlib import Path

BASELINE = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "0001_baseline.py"

EXPECTED = {"idx_manga_status_year","idx_manga_score_popularity","idx_manga_year_score","idx_manga_chapters","idx_manga_updated_at","idx_manga_cover_notnull","idx_reco_edges_to","idx_reco_edges_votes","idx_discovery_queue_pending","idx_discovery_queue_external"}

def test_models_define_p1_indexes():
    names = {i.name for t in (Manga.__table__, RecommendationsEdge.__table__, DiscoveryQueue.__table__) for i in t.indexes}
    assert EXPECTED.issubset(names), EXPECTED - names

def test_partial_cover_index():
    idx = {i.name: i for i in Manga.__table__.indexes}["idx_manga_cover_notnull"]
    assert "cover_image_url IS NOT NULL" in str(idx.dialect_options["postgresql"]["where"])

def test_baseline_revision_creates_the_schema_from_the_models():
    """A fresh database is created by Alembic, not by whichever process boots.

    The baseline revision is the frozen starting point: it creates every table
    and index from the model metadata, so the index set asserted above reaches a
    new deployment through `alembic upgrade head`.
    """
    source = BASELINE.read_text(encoding="utf-8")
    assert "Base.metadata.create_all" in source
    assert "revision = \"0001_baseline\"" in source

def test_genre_params():
    p = {}
    c = build_genre_sql_condition(["Action"], params=p)
    assert "genre_0_arr" in c and "genre_0_tag" in c and "Action" not in c
    assert p["genre_0_arr"] == ["Action"]

def test_genre_exclude_is_parameterised_too():
    """SVC-10: the exclude path is bound as well, so an apostrophe is never in SQL text."""
    p = {}
    c = build_genre_sql_condition(["Boys' Love"], params=p, exclude=True)
    assert c.startswith("NOT (") and "Boys' Love" not in c
    assert p["exclude_genre_0_arr"] == ["Boys' Love"]

def test_ann_ordering():
    import inspect, app.services.retrieval as r
    s = inspect.getsource(r.retrieve_similar_manga)
    assert "ORDER BY embedding <=> CAST(:emb AS vector)" in s and "pool_limit" in s

def test_no_per_request_set():
    import inspect, app.services.retrieval as r
    s = inspect.getsource(r)
    assert "SET pg_trgm" not in s and "set_config('pg_trgm" in s