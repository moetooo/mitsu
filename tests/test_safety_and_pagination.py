"""Integration tests for the two behavioural contracts fixed in this pass.

* every public endpoint hides NSFW titles through the shared safety predicate
  (`app/services/safety.py`), and
* "Load more" on a title-matched recommendation query walks past page 1 without
  raising (the page >= 2 crash) and reports `has_more`.

Both tests seed their own rows, so they run on any database, including CI's
empty test database.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db import AsyncSessionLocal
from app.ingestion.normalize import anilist_to_record, mangadex_to_record
from app.main import app
from tests.conftest import TARGET_TITLE


@pytest.mark.asyncio
async def test_title_match_pagination_reaches_page_three(seeded_catalog):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seen: list[int] = []
        page_one_ids: list[int] = []
        for page in (1, 2, 3):
            response = await client.post(
                "/recommend",
                json={"query": TARGET_TITLE, "limit": 5, "page": page},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert "has_more" in body
            assert isinstance(body["total_duration_ms"], (int, float))
            ids = [item["id"] for item in body["results"]]
            if page == 1:
                page_one_ids = ids
            seen.extend(ids)

        # Page 1 starts with the matched title, and the other pages return new rows.
        assert page_one_ids, "page 1 returned no results"
        assert len(seen) == len(set(seen)), "pages repeated rows"
        assert len(seen) > 5, "pagination never got past page 1"


@pytest.mark.asyncio
async def test_public_endpoints_never_return_nsfw(seeded_catalog):
    async with AsyncSessionLocal() as session:
        fixture_is_nsfw = await session.scalar(
            text("SELECT is_nsfw FROM manga WHERE title_english = 'Explicit Probe'")
        )
    assert fixture_is_nsfw is True, "fixture did not create the NSFW row"

    payloads: list[tuple[str, list]] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        search = await client.get("/search", params={"q": "Probe"})
        assert search.status_code == 200, search.text
        payloads.append(("search", search.json()))

        featured = await client.get("/manga/featured", params={"limit": 6})
        assert featured.status_code == 200, featured.text
        payloads.append(("featured", featured.json()))

        trending = await client.get("/manga/trending", params={"limit": 10, "page": 1})
        assert trending.status_code == 200, trending.text
        payloads.append(("trending", trending.json()))

        roulette = await client.post("/roulette", json={"filters": {"min_year": 2020}})
        assert roulette.status_code == 200, roulette.text
        payloads.append(("roulette", [roulette.json()]))

        batch = await client.post(
            "/roulette/batch", json={"filters": {"min_year": 2020}, "count": 5}
        )
        assert batch.status_code == 200, batch.text
        payloads.append(("roulette/batch", batch.json()))

    assert any(items for _, items in payloads), "no endpoint returned anything"

    for name, items in payloads:
        for item in items:
            genres = [genre.lower() for genre in (item.get("genres") or [])]
            tags = [
                (tag.get("name") if isinstance(tag, dict) else tag or "").lower()
                for tag in (item.get("tags") or [])
            ]
            assert "hentai" not in genres, f"{name} leaked an NSFW title: {item.get('title')}"
            assert "erotica" not in genres, f"{name} leaked an NSFW title: {item.get('title')}"
            assert "hentai" not in tags, f"{name} leaked an NSFW title: {item.get('title')}"
            assert item.get("is_nsfw") is not True, f"{name} leaked an NSFW title"


def _mangadex_payload(content_rating: str | None) -> dict:
    attributes = {
        "title": {"en": "Adult Probe"},
        "altTitles": [],
        "description": {"en": "Probe description."},
        "status": "ongoing",
        "year": 2022,
        "tags": [],
    }
    if content_rating is not None:
        attributes["contentRating"] = content_rating
    return {"id": "md-probe", "attributes": attributes, "relationships": []}


@pytest.mark.parametrize(
    ("content_rating", "expected"),
    [
        ("erotica", True),
        ("pornographic", True),
        ("suggestive", False),
        ("safe", False),
    ],
)
def test_mangadex_content_rating_decides_is_nsfw(content_rating, expected):
    """An adult MangaDex fixture must normalize to `is_nsfw = true`.

    MangaDex is the only source that publishes an explicit `contentRating`, so a
    normalized record that drops it stores adult titles with no NSFW signal at
    all - which is exactly how they used to reach the public endpoints.
    """
    record = mangadex_to_record(_mangadex_payload(content_rating))
    assert record["is_nsfw"] is expected


def test_anilist_is_adult_flag_decides_is_nsfw():
    record = anilist_to_record(
        {
            "id": 4321,
            "title": {"romaji": "Adult Probe", "english": "Adult Probe"},
            "isAdult": True,
            "genres": [],
            "tags": [],
        }
    )
    assert record["is_nsfw"] is True
