"""Contract edge cases closed in this pass.

Four small behaviours, all of which used to answer wrongly instead of answering
nothing:

* pagination input is bounded, so `page=0` is a 422 and not a negative-OFFSET 500;
* an empty roulette is a 404, not a fake card with `id=0`;
* `/similar` serves the stored `similar_mangas` edges for a row without an
  embedding, and no longer pre-slices the edge list before the NSFW filter;
* the trending DB fallback binds the caller's `genre` instead of pasting it into
  the SQL text.

Every test seeds its own rows, so it runs on an empty test database.
"""

import math

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import AsyncSessionLocal
from app.db_models import Manga
from app.main import app
from app.services.cache import BROWSER_CACHE_SECONDS


def _embedding(seed: int) -> list[float]:
    theta = 0.05 * seed
    vector = [0.0] * 384
    vector[0] = math.cos(theta)
    vector[1] = math.sin(theta)
    return vector


def _row(title: str, seed: int, **overrides) -> Manga:
    values = dict(
        title_english=title,
        title_romaji=title,
        synopsis=f"{title} synopsis.",
        genres=["Action"],
        tags=[{"name": "Action", "rank": 100}],
        status="RELEASING",
        start_year=2024,
        average_score=80,
        popularity=500 + seed,
        cover_image_url=f"https://example.invalid/{seed}.jpg",
        embedding=_embedding(seed),
        is_nsfw=False,
    )
    values.update(overrides)
    return Manga(**values)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


# --------------------------------------------------------------------------
# API-04 - pagination input is bounded
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"query": "anything", "limit": 0},
        {"query": "anything", "limit": -5},
        {"query": "anything", "limit": 10_000},
        {"query": "anything", "page": 0},
        {"query": "anything", "page": -1},
        {"query": "anything", "page": 10_000},
    ],
)
async def test_recommend_rejects_out_of_range_paging(client, payload):
    res = await client.post("/recommend", json=payload)
    assert res.status_code == 422, f"{payload} was accepted with {res.status_code}"


async def test_roulette_rejects_out_of_range_count(client):
    res = await client.post("/roulette", json={"count": 0})
    assert res.status_code == 422


@pytest.mark.parametrize("payload", [{"limit": 0}, {"limit": -5}, {"limit": 5000}, {"page": 0}, {"page": -1}])
async def test_trending_rejects_out_of_range_paging(client, payload):
    """ARCH-08: the slice and the page are bounded before any work is done.

    Unbounded, `?limit=5000` built a 5000-row page and cached it in Redis under
    its own key (the cache key includes the limit), and a negative page became a
    negative OFFSET. The bound lives in the handler, so this never reaches the
    database or the cache.
    """
    res = await client.get("/manga/trending", params=payload)
    assert res.status_code == 422, f"{payload} was accepted with {res.status_code}"


@pytest.mark.parametrize(
    "payload",
    [{"limit": 0}, {"limit": -5}, {"limit": 5000}, {"page": 0}, {"page": -1}, {"page": 50}],
)
async def test_similar_pages_rejects_out_of_range_paging(client, payload):
    """The full similar page is bounded like every other paged endpoint."""
    res = await client.get("/manga/1/similar/pages", params=payload)
    assert res.status_code == 422, f"{payload} was accepted with {res.status_code}"


@pytest.fixture
async def catalogue_pair():
    """Two rows with a stored edge, so detail and /similar both answer 200.

    A row is needed because the error path does not carry the endpoint's header:
    `app/main.py` sets `no-cache, no-store` on error responses, so a 404 would
    test the wrong header.
    """
    async with AsyncSessionLocal() as session:
        neighbour = _row("Cache Header Neighbour", 8)
        subject = _row("Cache Header Subject", 9)
        session.add_all([neighbour, subject])
        await session.flush()
        subject.similar_mangas = [{"id": neighbour.id, "score": 0.9}]
        await session.commit()
        return subject.id


async def test_browser_cache_is_a_hint_not_a_second_cache(client, catalogue_pair):
    """One copy of the answer: Redis.

    Every catalogue endpoint cached its response in Redis **and** told the
    browser to keep its own copy for the same long window (900 s on
    trending/featured, 3600 s on detail/similar, 300 s on search). Two copies of
    one answer, and the browser's cannot be revoked when a sync changes a row.
    `invalidate_catalog_caches()` reaches the Redis copy on every catalogue
    write, so the header is now one transport hint (`BROWSER_CACHE_SECONDS`) and
    the comparison is against that constant, not a hand-typed number.
    """
    subject_id = catalogue_pair
    for path in (
        "/manga/trending",
        "/manga/featured",
        f"/manga/{subject_id}",
        f"/manga/{subject_id}/similar?limit=6",
        f"/manga/{subject_id}/similar/pages?limit=6",
        "/search?q=cache+header",
    ):
        res = await client.get(path)
        assert res.status_code == 200, f"{path}: {res.text}"
        header = res.headers["cache-control"]
        max_age = int(header.split("max-age=")[1].split(",")[0])
        assert max_age == BROWSER_CACHE_SECONDS, f"{path} hands out {max_age}s: {header}"
        assert "stale-while-revalidate" not in header, header


# --------------------------------------------------------------------------
# API-03 - an empty roulette is an explicit 404, not a placeholder card
# --------------------------------------------------------------------------


async def test_roulette_is_404_when_nothing_matches(client):
    res = await client.post("/roulette", json={"count": 1})
    assert res.status_code == 404
    assert "id" not in res.json()


# --------------------------------------------------------------------------
# API-10 - /similar works from stored edges without an embedding
# --------------------------------------------------------------------------


async def test_similar_uses_precomputed_edges_without_embedding(client):
    async with AsyncSessionLocal() as session:
        neighbour = _row("Edge Neighbour", 1)
        # Deliberately no embedding: the stored edges are the whole answer.
        subject = _row("Edge Subject", 2, embedding=None, similar_mangas=[{"id": 99, "score": 0.9}])
        session.add_all([neighbour, subject])
        await session.flush()
        subject.similar_mangas = [{"id": neighbour.id, "score": 0.9}]
        await session.commit()
        subject_id, neighbour_id = subject.id, neighbour.id

    res = await client.get(f"/manga/{subject_id}/similar")
    assert res.status_code == 200, res.text
    ids = [item["id"] for item in res.json()]
    assert ids == [neighbour_id]


async def test_similar_pages_paginate_edges_with_has_more(client):
    """Page N is the next slice of the same ordered edge list.

    Stored edges are a fixed list, so the service slices them after the NSFW
    filter; asking for page 2 must not repeat page 1 or claim `has_more` when
    the list has ended.
    """
    async with AsyncSessionLocal() as session:
        neighbours = [_row(f"Page Neighbour {i}", 20 + i) for i in range(3)]
        # No embedding: forces the stored-edge source, which is the one being
        # paginated here (the live ANN path has its own offset test).
        subject = _row("Page Subject", 19, embedding=None)
        session.add_all(neighbours + [subject])
        await session.flush()
        subject.similar_mangas = [
            {"id": row.id, "score": 0.9 - index * 0.01}
            for index, row in enumerate(neighbours)
        ]
        await session.commit()
        subject_id = subject.id
        neighbour_ids = [row.id for row in neighbours]

    first = await client.get(
        f"/manga/{subject_id}/similar/pages", params={"limit": 2, "page": 1}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["id"] for item in body["results"]] == neighbour_ids[:2]
    assert body["has_more"] is True
    # Same facts as a grid card: the rail renders MangaCard too.
    card = body["results"][0]
    assert card["start_year"] == 2024
    assert card["average_score"] == 80
    assert card["status"] == "RELEASING"

    second = await client.get(
        f"/manga/{subject_id}/similar/pages", params={"limit": 2, "page": 2}
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert [item["id"] for item in body["results"]] == neighbour_ids[2:]
    assert body["has_more"] is False

    third = await client.get(
        f"/manga/{subject_id}/similar/pages", params={"limit": 2, "page": 3}
    )
    assert third.status_code == 200, third.text
    assert third.json()["results"] == []
    assert third.json()["has_more"] is False


async def test_similar_still_404s_without_edges_or_embedding(client):
    async with AsyncSessionLocal() as session:
        subject = _row("Bare Subject", 3, embedding=None, similar_mangas=None)
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    res = await client.get(f"/manga/{subject_id}/similar")
    assert res.status_code == 404


# --------------------------------------------------------------------------
# API-09 - the trending genre filter binds instead of interpolating
# --------------------------------------------------------------------------


async def test_trending_binds_genre_instead_of_interpolating(client):
    async with AsyncSessionLocal() as session:
        session.add(_row("Trending Genre Probe", 4, genres=["Action"]))
        await session.commit()

    # Trending is catalog-backed now, so there is no provider path to force.
    ok = await client.get("/manga/trending", params={"genre": "Action"})
    assert ok.status_code == 200, ok.text
    assert [item["title"] for item in ok.json()] == ["Trending Genre Probe"]

    # Quoting and boolean syntax used to be pasted straight into the SQL text.
    injection = await client.get(
        "/manga/trending", params={"genre": "Action') OR ('1'='1"}
    )
    assert injection.status_code == 200, injection.text
    assert injection.json() == []
