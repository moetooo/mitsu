"""Filter-only discovery and result sorting on POST /recommend.

These are DB-free by construction: the browse query is exercised against a stub
session that records the statement, and the endpoint tests override `get_db` and
the cache so no Postgres or Redis is required here. Catalogue-backed ordering is
covered separately by the `requires_catalog` suite.
"""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db import get_db
from app.services import retrieval
from app.services.retrieval import (
    _browse_order_clause,
    _text_order_clause,
    normalize_sort,
    retrieve_catalog_page,
    retrieve_similar_manga,
)


def _row(index: int, *, popularity: int = 100, score: int = 80):
    """One row as the raw retrieval SQL returns it (no similarity columns)."""
    return SimpleNamespace(
        id=index,
        anilist_id=1000 + index,
        mal_id=2000 + index,
        mangadex_id=f"md-{index}",
        title_romaji=f"Title {index}",
        title_english=f"Title {index}",
        title_native=None,
        synopsis="A story.",
        genres=["Action"],
        tags=[{"name": "Adventure"}],
        inferred_tags=None,
        status="FINISHED",
        start_year=2010,
        chapters=50,
        volumes=5,
        average_score=score,
        popularity=popularity,
        cover_image_url=None,
        banner_image=None,
        site_url=None,
        alternative_titles=[],
        format_type="MANGA",
    )


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), dict(params or {})))
        return _Rows(self.rows)


def test_sort_ids_normalise_and_keep_a_total_order():
    assert normalize_sort("popularity") == "popularity"
    assert normalize_sort("relevance") == "relevance"
    assert normalize_sort("unknown") == "default"
    assert normalize_sort(None) == "default"

    # Every ordering ends in `id`, otherwise offset paging can repeat or skip
    # rows that tie on score/popularity.
    for clause in (_text_order_clause("default"), _text_order_clause("relevance"),
                   _text_order_clause("popularity"), _browse_order_clause("default"),
                   _browse_order_clause("popularity")):
        assert clause.rstrip().endswith("id ASC")


def test_relevance_collapses_to_default_without_a_query():
    assert _browse_order_clause("relevance") == _browse_order_clause("default")


@pytest.mark.asyncio
async def test_browse_query_applies_filters_and_uses_catalogue_order():
    session = _FakeSession([_row(1), _row(2), _row(3)])

    candidates = await retrieve_catalog_page(
        session,
        filters={"genres": ["Action"], "status": ["FINISHED"]},
        sort="popularity",
        limit=2,
        offset=2,
    )

    assert [c["manga"].id for c in candidates] == [1, 2, 3]
    assert all(c["similarity_score"] is None for c in candidates)

    sql, params = session.executed[0]
    assert "FROM manga" in sql
    assert "WHERE" in sql
    assert "ORDER BY popularity DESC NULLS LAST" in sql
    assert params["limit"] == 2
    assert params["offset"] == 2
    # The genre predicate is bound, never interpolated.
    assert any("Action" in str(value) for value in params.values())
    assert "Action" not in sql


def _override_db(session):
    async def _get_db():
        yield session

    app.dependency_overrides[get_db] = _get_db


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    async def no_read(_key):
        return None

    async def no_write(_key, _value, ttl=0):
        return None

    monkeypatch.setattr("app.routers.recommend.get_cached", no_read)
    monkeypatch.setattr("app.routers.recommend.set_cached", no_write)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_empty_query_browses_the_catalogue_without_paid_paths(monkeypatch, client):
    session = _FakeSession([_row(1), _row(2), _row(3)])
    _override_db(session)

    async def paid(*_args, **_kwargs):
        raise AssertionError("browse must not call the embedding or LLM path")

    monkeypatch.setattr("app.routers.recommend.generate_embedding", paid)
    monkeypatch.setattr("app.routers.recommend.generate_reasoning", paid)
    monkeypatch.setattr("app.routers.recommend.autocorrect_query", paid)

    async with client as ac:
        response = await ac.post(
            "/recommend",
            json={
                "filters": {"genres": ["Action"]},
                "sort": "popularity",
                "limit": 2,
                "page": 1,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 2
    assert body["has_more"] is True
    assert body["corrected_query"] is None
    assert body["title_suggestion"] is None
    assert body["llm_ms"] == 0.0
    # `popularity` is on the wire now, so the client can show/verify the sort.
    assert body["results"][0]["popularity"] == 100
    assert body["results"][0]["similarity_score"] is None

    sql = session.executed[0][0]
    assert "ORDER BY popularity DESC NULLS LAST" in sql


@pytest.mark.asyncio
async def test_text_query_forwards_sort_to_retrieval(monkeypatch, client):
    _override_db(_FakeSession([]))
    captured = {}

    async def no_embedding(_query):
        return [0.1] * 8

    async def no_exact_title(_db, _query):
        return None

    async def no_suggestion(_db, _query):
        return None

    async def same_query(query, _db):
        return query

    async def fake_similar(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("app.routers.recommend.generate_embedding", no_embedding)
    monkeypatch.setattr("app.routers.recommend.find_exact_title", no_exact_title)
    monkeypatch.setattr("app.routers.recommend.find_title_suggestion", no_suggestion)
    monkeypatch.setattr("app.routers.recommend.autocorrect_query", same_query)
    monkeypatch.setattr("app.routers.recommend.retrieve_similar_manga", fake_similar)

    async with client as ac:
        response = await ac.post(
            "/recommend",
            json={"query": "dark fantasy", "sort": "relevance", "limit": 4, "page": 1},
        )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert captured["sort"] == "relevance"


@pytest.mark.asyncio
async def test_unknown_sort_is_rejected(client):
    async with client as ac:
        response = await ac.post(
            "/recommend",
            json={"query": "x", "sort": "trending"},
        )

    assert response.status_code == 422


def test_recommend_request_defaults_to_browse_and_default_sort():
    from app.models import RecommendRequest

    request = RecommendRequest()
    assert request.query == ""
    assert request.sort == "default"
    assert retrieval.normalize_sort(request.sort) == "default"


@pytest.mark.asyncio
async def test_exact_title_neighbours_use_a_similarity_floor(monkeypatch, client):
    """A title search must not append rows outside the seed's neighbourhood.

    The regression: with no query text, the seed path built no relevance
    condition at all, so a sparse pool returned whatever the ANN query found --
    e.g. "Black Witch Mirror" (sim 0.33-0.39) under Berserk, Monogatari and
    Bakemonogatari.
    """
    from app.services.retrieval import SEED_MIN_SIMILARITY

    _override_db(_FakeSession([]))
    captured = {}

    async def matched(_db, _query):
        return (100419, "Berserk", [0.1] * 8, 1.0)

    async def no_target(_db, _mid):
        return None

    async def no_suggestion(_db, _query):
        return None

    async def fake_similar(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr("app.routers.recommend.find_exact_title", matched)
    monkeypatch.setattr("app.routers.recommend.find_title_suggestion", no_suggestion)
    monkeypatch.setattr("app.routers.recommend.catalog.get_manga", no_target)
    monkeypatch.setattr("app.routers.recommend.retrieve_similar_manga", fake_similar)

    async with client as ac:
        response = await ac.post(
            "/recommend",
            json={"query": "berserk", "limit": 4, "page": 1},
        )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert captured["min_similarity"] == SEED_MIN_SIMILARITY
    # The word rule needs the query text; without it "Berserk of Gluttony"
    # can never be admitted below the floor.
    assert captured["query_text"] == "berserk"


@pytest.mark.asyncio
async def test_similarity_floor_is_bound_in_the_scored_filter():
    session = _FakeSession([_row(1)])

    await retrieve_similar_manga(
        session,
        [0.1] * 8,
        filters={},
        limit=2,
        min_similarity=0.44,
    )

    scored_sql = [sql for sql, params in session.executed if "min_similarity" in params]
    assert scored_sql, "the floor must reach the SQL, not only the call site"
    assert all("sim >= :min_similarity" in sql for sql in scored_sql)
    bound = [params["min_similarity"] for _, params in session.executed if "min_similarity" in params]
    assert set(bound) == {0.44}


@pytest.mark.asyncio
async def test_title_word_matches_bypass_the_absolute_floor():
    """The word rule and the floor are alternatives, never ANDed.

    Text queries have used `(title_boost > 0 OR sim >= 0.44)` for a while.
    A seed search now passes the same query text, so it must keep that single
    gate: adding `sim >= 0.44` on top would exclude every title-word match that
    is not also an embedding neighbour.
    """
    session = _FakeSession([_row(1)])

    await retrieve_similar_manga(
        session,
        [0.1] * 8,
        filters={},
        limit=2,
        query_text="berserk",
        min_similarity=0.44,
    )

    sql, params = session.executed[-1]
    assert "title_boost > 0 OR sim >= 0.44" in sql
    assert "min_similarity" not in params
    # Same work under two titles (AniList and MAL rows) must collapse too.
    assert "rn_work = 1" in sql
