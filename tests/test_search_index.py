"""API-08, Stage 7A: `/search` is one indexed predicate, paged.

The endpoint's shape is asserted here rather than in a request test because the
defect was the *statement*: four `ILIKE`s ORed together, one of them over
`array_to_string(alternative_titles, ' ')`, which no index can serve. The tests
that need the catalogue (`requires_catalog`) prove the index is actually used and
that `offset` paging is stable; the rest run with no database at all.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from app.db import AsyncSessionLocal
from app.main import app
from app.services import catalog


def _sql(term: str = "berserk", limit: int = 10, offset: int = 0) -> str:
    stmt = catalog.build_search_statement(term, limit=limit, offset=offset)
    return str(stmt.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------- statement shape
def test_search_matches_through_one_expression():
    """Four ORed predicates became one, and `array_to_string` is gone.

    The old SQL text contained `array_to_string`, which is the reason the planner
    could not use an index for any branch of the OR.
    """
    sql = _sql()
    assert "array_to_string" not in sql
    assert "ILIKE" not in sql
    # Exactly one LIKE: the matching predicate is a single expression. The `OR`
    # that remains in the statement belongs to the NSFW safety predicate.
    assert sql.count(" LIKE ") == 1


def test_search_expression_is_the_indexed_one():
    """The statement matches the expression migration 0006 indexes.

    If these drift apart the query still returns the right rows, but silently
    goes back to a sequential scan, so the text is asserted directly.
    """
    sql = _sql()
    for fragment in (
        "lower(coalesce(manga.title_english",
        "coalesce(manga.title_romaji",
        "coalesce(manga.title_native",
        "mitsu_alt_titles_text(manga.alternative_titles)",
    ):
        assert fragment in sql
    assert "mitsu_alt_titles_text" in sql


def test_search_like_metacharacters_are_escaped():
    """`%` and `_` in the term are literals, and the pattern is a bound parameter."""
    stmt = catalog.build_search_statement("100%")
    params = stmt.compile(dialect=postgresql.dialect()).params
    pattern = params["lower_1"]
    assert pattern == "%100\\%%"
    assert "ESCAPE" in str(stmt.compile(dialect=postgresql.dialect()))


def test_search_is_paged_and_ordered_totally():
    """`limit`/`offset` are applied and the ordering has a tiebreak."""
    sql = _sql(limit=5, offset=20)
    assert "LIMIT " in sql
    assert "OFFSET " in sql
    order_by = sql.split("ORDER BY", 1)[1].split("LIMIT", 1)[0]
    assert "manga.id" in order_by


def test_search_keeps_the_safety_predicate():
    """A public endpoint must not trust a caller to ask for safety."""
    sql = _sql()
    assert "is_nsfw" in sql


# ---------------------------------------------------------------- request bounds
@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "offset=-1"])
async def test_out_of_range_paging_is_rejected(client, query):
    """Bounded paging: an unbounded `limit` is unbounded work (API-04's rule)."""
    resp = await client.get(f"/search?q=berserk&{query}")
    assert resp.status_code == 422


async def test_empty_query_is_an_empty_page(client):
    resp = await client.get("/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []


# ------------------------------------------------------- against the real catalogue
async def _explain(db, term: str) -> str:
    statement = text(
        "EXPLAIN SELECT id FROM manga "
        "WHERE lower(coalesce(title_english, '') || ' ' || coalesce(title_romaji, '') || ' ' "
        "|| coalesce(title_native, '') || ' ' "
        "|| coalesce(mitsu_alt_titles_text(alternative_titles), '')) LIKE :pattern "
        "ORDER BY popularity DESC NULLS LAST, id LIMIT 10"
    )
    rows = (await db.execute(statement, {"pattern": f"%{term}%"})).scalars().all()
    return "\n".join(rows)


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_index_is_actually_used():
    """The query plan names the index, so API-08's seq scan is really gone."""
    async with AsyncSessionLocal() as db:
        plan = await _explain(db, "frieren")
    assert "idx_manga_search_blob_trgm" in plan, plan
    assert "Seq Scan" not in plan, plan


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_pages_are_disjoint_and_ordered():
    """Two pages of different offsets do not overlap, together they equal one page."""
    async with AsyncSessionLocal() as db:
        first = await catalog.search_titles(db, "one", limit=10, offset=0)
        second = await catalog.search_titles(db, "one", limit=10, offset=10)
        both = await catalog.search_titles(db, "one", limit=20, offset=0)

    first_ids = [row.id for row in first]
    second_ids = [row.id for row in second]
    assert len(first_ids) == len(set(first_ids))
    assert not set(first_ids) & set(second_ids)
    assert first_ids + second_ids == [row.id for row in both]


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_percent_is_not_a_wildcard():
    """`q=%` used to match every row in the table."""
    async with AsyncSessionLocal() as db:
        matches = await catalog.search_titles(db, "%", limit=catalog.SEARCH_MAX_LIMIT)

    assert len(matches) < 100
    for row in matches:
        haystack = " ".join(
            [
                row.title_english or "",
                row.title_romaji or "",
                row.title_native or "",
                " ".join(row.alternative_titles or []),
            ]
        )
        assert "%" in haystack


@pytest.mark.requires_catalog
@pytest.mark.asyncio
async def test_alternative_titles_are_still_searchable():
    """The index covers the alternative titles, so an alt-title hit still resolves."""
    async with AsyncSessionLocal() as db:
        matches = await catalog.search_titles(db, "shingeki no kyojin", limit=5)
    assert matches, "expected a title or alternative title to match"
