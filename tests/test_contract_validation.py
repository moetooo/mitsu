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
from app.services.cache import set_cached


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


async def test_similar_still_404s_without_edges_or_embedding(client):
    async with AsyncSessionLocal() as session:
        subject = _row("Bare Subject", 3, embedding=None, similar_mangas=None)
        session.add(subject)
        await session.commit()
        subject_id = subject.id

    res = await client.get(f"/manga/{subject_id}/similar")
    assert res.status_code == 404


# --------------------------------------------------------------------------
# API-09 - the trending DB fallback binds the genre
# --------------------------------------------------------------------------


async def test_trending_fallback_binds_genre_instead_of_interpolating(client):
    async with AsyncSessionLocal() as session:
        session.add(_row("Trending Genre Probe", 4, genres=["Action"]))
        await session.commit()

    # Force the DB fallback path so the test never touches AniList.
    await set_cached("manga:anilist_circuit_open", True, ttl=60)

    ok = await client.get("/manga/trending", params={"genre": "Action"})
    assert ok.status_code == 200, ok.text
    assert [item["title"] for item in ok.json()] == ["Trending Genre Probe"]

    # Quoting and boolean syntax used to be pasted straight into the SQL text.
    injection = await client.get(
        "/manga/trending", params={"genre": "Action') OR ('1'='1"}
    )
    assert injection.status_code == 200, injection.text
    assert injection.json() == []
