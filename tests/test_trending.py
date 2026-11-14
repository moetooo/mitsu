"""Trending is a catalogue ranking and nothing else (ARCH-08).

The endpoint used to call AniList live on the request path, inside a 2.5s
timeout, with no provider budget. A provider row has no local primary key, so
those rows either lied about `id` or had to be dropped -- which is why the live
path is deleted rather than budgeted: a "top-up" could only ever contribute rows
the catalogue already held.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.services import trending
from app.services.cache import set_cached


def test_trending_module_makes_no_network_calls():
    """The whole point: no HTTP client, no provider, no budget to spend."""
    tree = ast.parse(inspect.getsource(trending))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"httpx", "aiohttp", "requests", "urllib", "urllib3"}), (
        "services/trending.py must not import an HTTP client; trending is a catalogue query"
    )
    # And no provider host may appear anywhere, including in a string constant.
    source = inspect.getsource(trending)
    for host in ("graphql.anilist.co", "kitsu.io", "api.mangadex.org", "api.jikan.moe"):
        assert host not in source, f"services/trending.py must not reference {host!r}"


def test_router_trending_endpoint_does_not_reach_for_a_client():
    """The router must not reintroduce the call it used to make."""
    from app.routers import manga as manga_router

    source = inspect.getsource(manga_router)
    assert "graphql.anilist.co" not in source
    assert "anilist_circuit_open" not in source
    assert "import httpx" not in source


def test_cache_key_treats_all_and_none_alike():
    """`all`, `None` and a blank genre must land on one cache key, or the cache fragments."""
    for genre in (None, "", "   ", "all", "ALL"):
        assert trending.cache_key("all", genre, 1, 12) == "manga:trending:all:all:1:12"
    assert trending.cache_key(None, None, 1, 12) == trending.cache_key("ALL", "", 1, 12)
    # A real filter still separates keys.
    assert trending.cache_key("all", "Action", 1, 12) != trending.cache_key("all", None, 1, 12)


def test_genre_predicate_comes_from_the_shared_builder():
    """ARCH-07: the router's inline `ILIKE '%Yaoi%'` variants are gone.

    `yaoi` must expand to the same alias set the retrieval filter uses, and it
    must be bound rather than pasted into the SQL text.
    """
    stmt, params, used = trending.build_query("all", "yaoi")
    compiled = str(stmt)
    assert used is True
    assert "genre_0_arr" in compiled
    assert params["genre_0_arr"] == ["Boys' Love"]
    assert "Yaoi" not in compiled, "the alias must be a bind value, not SQL text"


def test_trending_does_not_filter_by_year():
    """API-19: recency was expressed as a WHERE clause and hid half the catalogue.

    `start_year >= 2020 OR status = RELEASING` kept only 36.6% of rows (34,977 of
    95,661) and removed 7 of the all-time top 10 -- Chainsaw Man, Solo Leveling,
    Jujutsu Kaisen, Attack on Titan, Tokyo Ghoul, Demon Slayer, Oyasumi Punpun --
    because they started before 2020. If freshness should matter it belongs in the
    ORDER BY as a weight, where it reorders rows instead of deleting them.
    """
    stmt, _params, _used = trending.build_query("all", None)
    # The column list of a whole-row select mentions `start_year` either way; the
    # predicate is the thing under test.
    predicate = str(stmt.whereclause)
    assert "start_year" not in predicate, predicate


def test_unknown_format_reports_that_it_could_not_filter():
    """An unrecognised format must not silently look like a working filter."""
    _stmt, _params, used = trending.build_query("not-a-real-format", None)
    assert used is False


@pytest.mark.asyncio
async def test_trending_rows_always_carry_a_local_id(seeded_catalog):
    """Every returned row is openable: `id` is the local PK, never None."""
    async with AsyncSessionLocal() as session:
        rows = await trending.trending_page(session, page=1, limit=10)
    assert rows, "the seeded catalogue should produce at least one trending row"
    for row in rows:
        assert isinstance(row.id, int), "a trending row without a local PK cannot be opened"


@pytest.mark.asyncio
async def test_trending_excludes_adult_titles(seeded_catalog):
    """`is_nsfw` comes from services/safety.py, the single owner of that decision."""
    async with AsyncSessionLocal() as session:
        rows = await trending.trending_page(session, page=1, limit=200)
        nsfw_titles = set(
            (await session.execute(
                text("SELECT title_english FROM manga WHERE is_nsfw IS TRUE")
            )).scalars().all()
        )
    assert nsfw_titles, "fixture did not create an NSFW row"
    served = {row.title_english or row.title_romaji for row in rows}
    assert not (served & nsfw_titles)


@pytest.mark.asyncio
async def test_get_trending_serves_the_cache_before_the_database(seeded_catalog):
    """A warmed cache must answer without touching the catalogue."""
    key = trending.cache_key("all", None, 1, 5)
    sentinel = [{"id": 1, "title": "From Cache"}]
    await set_cached(key, sentinel, ttl=60)

    async with AsyncSessionLocal() as session:
        rows = await trending.get_trending(session, page=1, limit=5)
    assert rows == sentinel


@pytest.mark.asyncio
async def test_top10_only_overrides_page_and_limit(seeded_catalog):
    """The dashboard widget always gets ten rows from page one."""
    key = trending.cache_key("all", None, 1, trending.TOP10_LIMIT)
    await set_cached(key, [{"id": 2, "title": "Top Ten"}], ttl=60)

    async with AsyncSessionLocal() as session:
        rows = await trending.get_trending(session, page=7, limit=40, top10_only=True)
    assert rows == [{"id": 2, "title": "Top Ten"}]
